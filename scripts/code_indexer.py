"""
Code Indexer — builds a structured, queryable code map from source files.

Produces .code-reading/index.db with a 4-layer hierarchy:
  d3_modules    — top-level business modules
  d2_directories — subdomain directories
  d1_files      — files with symbol lists
  d0_functions  — function signatures, line ranges, call edges

Uses Python's built-in ast module for Python files (deterministic, no LLM).
For TypeScript/TSX, uses heuristic regex extraction.
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import sys
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict

# ── Data structures ──────────────────────────────────────────────


@dataclass
class FunctionInfo:
    name: str
    signature: str
    line_start: int
    line_end: int
    kind: str  # function, method, async_function, component
    decorators: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)


@dataclass
class FileInfo:
    path: Path
    name: str
    language: str  # python, typescript, tsx
    loc: int
    functions: list[FunctionInfo] = field(default_factory=list)
    imports: list[tuple[str, list[str]]] = field(default_factory=list)
    top_level_classes: list[str] = field(default_factory=list)

    @property
    def symbols(self) -> list[str]:
        return [f.name for f in self.functions] + self.top_level_classes


# ── Python parser (deterministic, AST-based) ─────────────────────


class PythonParser:
    def parse(self, file_path: Path) -> FileInfo:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        loc = len(source.splitlines())
        info = FileInfo(path=file_path, name=file_path.name, language="python", loc=loc)

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return info

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    info.imports.append((alias.name, []))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names = [alias.name for alias in node.names]
                    info.imports.append((node.module, names))

        for node in ast.iter_child_nodes(tree):
            func = self._extract_function(node, source)
            if func:
                info.functions.append(func)
            elif isinstance(node, ast.ClassDef):
                info.top_level_classes.append(node.name)
                for body_item in node.body:
                    m = self._extract_function(body_item, source)
                    if m:
                        m.kind = "method"
                        info.functions.append(m)

        return info

    def _extract_function(self, node: ast.AST, source: str) -> FunctionInfo | None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [
                ast.unparse(d) if hasattr(ast, "unparse") else ast.dump(d)
                for d in node.decorator_list
            ]
            args = [a.arg for a in node.args.args]
            kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            sig = f"def {node.name}({', '.join(args)})"
            calls = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    call_name = self._call_name(child)
                    if call_name:
                        calls.append(call_name)
            return FunctionInfo(
                name=node.name,
                signature=sig,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                kind=kind,
                decorators=decorators,
                calls=calls,
            )
        return None

    @staticmethod
    def _call_name(call: ast.Call) -> str | None:
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None


# ── TypeScript/TSX parser (heuristic regex) ──────────────────────


TS_FUNC_RE = re.compile(
    r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
    re.MULTILINE,
)
TS_ARROW_RE = re.compile(
    r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*[:=]\s*(?:async\s*)?\([^)]*\)\s*=>',
    re.MULTILINE,
)
TS_CLASS_RE = re.compile(r'(?:export\s+)?class\s+(\w+)', re.MULTILINE)
TS_IMPORT_RE = re.compile(
    r'import\s+\{([^}]+)\}\s+from\s+[\'"]([^\'"]+)[\'"]',
    re.MULTILINE,
)
TS_DEFAULT_IMPORT_RE = re.compile(
    r'import\s+(\w+)\s+from\s+[\'"]([^\'"]+)[\'"]',
    re.MULTILINE,
)
TS_CALL_RE = re.compile(r'(\w+)\s*\(', re.MULTILINE)


class TypeScriptParser:
    def parse(self, file_path: Path) -> FileInfo:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        loc = len(lines)
        lang = "tsx" if file_path.suffix == ".tsx" else "typescript"
        info = FileInfo(path=file_path, name=file_path.name, language=lang, loc=loc)

        for m in TS_IMPORT_RE.finditer(source):
            names = [n.strip().split(" as ")[0].strip() for n in m.group(1).split(",")]
            info.imports.append((m.group(2), names))
        for m in TS_DEFAULT_IMPORT_RE.finditer(source):
            info.imports.append((m.group(2), [m.group(1)]))

        for m in TS_CLASS_RE.finditer(source):
            info.top_level_classes.append(m.group(1))

        for m in TS_FUNC_RE.finditer(source):
            name, args = m.group(1), m.group(2)
            line_no = source[: m.start()].count("\n") + 1
            info.functions.append(
                FunctionInfo(
                    name=name,
                    signature=f"function {name}({args})",
                    line_start=line_no,
                    line_end=line_no,
                    kind="function",
                )
            )

        for m in TS_ARROW_RE.finditer(source):
            name = m.group(1)
            line_no = source[: m.start()].count("\n") + 1
            if name and name[0].isupper():
                kind = "component"
            else:
                kind = "function"
            info.functions.append(
                FunctionInfo(
                    name=name,
                    signature=f"const {name} = (...) => ...",
                    line_start=line_no,
                    line_end=line_no,
                    kind=kind,
                )
            )

        return info


# ── SQLite store ──────────────────────────────────────────────────


class IndexStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
        DROP TABLE IF EXISTS calls;
        DROP TABLE IF EXISTS imports;
        DROP TABLE IF EXISTS d0_functions;
        DROP TABLE IF EXISTS d1_files;
        DROP TABLE IF EXISTS d2_directories;
        DROP TABLE IF EXISTS d3_modules;

        CREATE TABLE d3_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            path TEXT,
            file_count INTEGER DEFAULT 0,
            function_count INTEGER DEFAULT 0,
            language TEXT
        );

        CREATE TABLE d2_directories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            path TEXT UNIQUE,
            module_id INTEGER REFERENCES d3_modules(id),
            file_count INTEGER DEFAULT 0
        );

        CREATE TABLE d1_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            path TEXT UNIQUE,
            directory_id INTEGER REFERENCES d2_directories(id),
            loc INTEGER DEFAULT 0,
            language TEXT,
            symbols TEXT
        );

        CREATE TABLE d0_functions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            signature TEXT,
            file_id INTEGER REFERENCES d1_files(id),
            line_start INTEGER,
            line_end INTEGER,
            kind TEXT,
            decorators TEXT
        );

        CREATE TABLE calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_file TEXT,
            caller_func TEXT,
            callee_name TEXT,
            callee_file TEXT,
            relationship TEXT DEFAULT 'unconfirmed'
        );

        CREATE TABLE imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            imported_module TEXT,
            imported_names TEXT
        );

        CREATE INDEX idx_d0_file ON d0_functions(file_id);
        CREATE INDEX idx_d1_dir ON d1_files(directory_id);
        CREATE INDEX idx_d2_module ON d2_directories(module_id);
        CREATE INDEX idx_calls_callee ON calls(callee_name);
        CREATE INDEX idx_calls_caller ON calls(caller_func);
        """)

    def insert_module(self, name: str, path: str, file_count: int, func_count: int, lang: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO d3_modules (name, path, file_count, function_count, language) VALUES (?, ?, ?, ?, ?)",
            (name, path, file_count, func_count, lang),
        )
        self.conn.commit()
        return cur.lastrowid

    def insert_directory(self, name: str, path: str, module_id: int, file_count: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO d2_directories (name, path, module_id, file_count) VALUES (?, ?, ?, ?)",
            (name, path, module_id, file_count),
        )
        self.conn.commit()
        return cur.lastrowid

    def insert_file(self, info: FileInfo, directory_id: int) -> int:
        symbols_json = json.dumps(info.symbols, ensure_ascii=False)
        cur = self.conn.execute(
            "INSERT INTO d1_files (name, path, directory_id, loc, language, symbols) VALUES (?, ?, ?, ?, ?, ?)",
            (info.name, str(info.path), directory_id, info.loc, info.language, symbols_json),
        )
        self.conn.commit()
        file_id = cur.lastrowid

        for func in info.functions:
            decorators_json = json.dumps(func.decorators, ensure_ascii=False)
            self.conn.execute(
                "INSERT INTO d0_functions (name, signature, file_id, line_start, line_end, kind, decorators) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (func.name, func.signature, file_id, func.line_start, func.line_end, func.kind, decorators_json),
            )

        for module_name, names in info.imports:
            names_json = json.dumps(names, ensure_ascii=False)
            self.conn.execute(
                "INSERT INTO imports (file_path, imported_module, imported_names) VALUES (?, ?, ?)",
                (str(info.path), module_name, names_json),
            )

        self.conn.commit()
        return file_id

    def insert_calls(self, file_path: str, func_info: FunctionInfo):
        """Resolve call edges where possible; mark external vs direct."""
        for callee in func_info.calls:
            # Check if callee is defined in the project
            cur = self.conn.execute(
                "SELECT f.path FROM d0_functions d JOIN d1_files f ON d.file_id = f.id WHERE d.name = ?",
                (callee,),
            )
            row = cur.fetchone()
            if row:
                self.conn.execute(
                    "INSERT INTO calls (caller_file, caller_func, callee_name, callee_file, relationship) VALUES (?, ?, ?, ?, 'direct')",
                    (file_path, func_info.name, callee, row[0]),
                )
            else:
                self.conn.execute(
                    "INSERT INTO calls (caller_file, caller_func, callee_name, callee_file, relationship) VALUES (?, ?, ?, NULL, 'unconfirmed')",
                    (file_path, func_info.name, callee),
                )
        self.conn.commit()

    def close(self):
        self.conn.close()


# ── Indexer orchestrator ──────────────────────────────────────────


def _is_test_file(path: Path) -> bool:
    return "test" in path.name.lower() or "__pycache__" in str(path)


def _classify_module(dir_name: str) -> str:
    """Classify a top-level directory into a business module."""
    module_map = {
        "backend": "Backend Core",
        "frontend": "Frontend",
        "skills": "Runtime Skills",
        "rules": "Runtime Rules",
        "mcp-servers": "MCP Servers",
        "sdk": "Python SDK",
        "deploy": "Deployment",
        "scripts": "Admin Scripts",
        "docs": "Documentation",
        "prompts": "Prompt Templates",
        "config": "Configuration",
        "cli": "CLI",
        ".github": "CI/CD",
        ".claude": "Claude Config",
        "data": "Runtime Data",
    }
    return module_map.get(dir_name, dir_name)


def index_project(root: Path) -> IndexStore:
    root = root.resolve()
    db_path = root / ".code-reading" / "index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = IndexStore(db_path)

    py_parser = PythonParser()
    ts_parser = TypeScriptParser()

    # Collect all source files
    py_files: list[Path] = []
    ts_files: list[Path] = []

    scan_dirs = ["backend", "frontend/src", "sdk", "mcp-servers", "scripts", "cli", "skills", "rules"]
    for scan_dir in scan_dirs:
        scan_path = root / scan_dir
        if not scan_path.exists():
            continue
        for ext, collector in [("*.py", py_files), ("*.ts", ts_files), ("*.tsx", ts_files)]:
            for f in scan_path.rglob(ext):
                if not _is_test_file(f) and f.name != "__init__.py":
                    collector.append(f)

    # Also add top-level standalone Python files
    for f in root.glob("*.py"):
        if not _is_test_file(f):
            py_files.append(f)

    top_dirs: dict[str, list[Path]] = defaultdict(list)
    for f in py_files + ts_files:
        try:
            rel = f.relative_to(root)
        except ValueError:
            continue
        part = rel.parts[0]
        top_dirs[part].append(f)

    # Build hierarchy: module → directory → file → function
    for dir_name, files in sorted(top_dirs.items()):
        module_name = _classify_module(dir_name)
        total_funcs = 0
        total_files = len(files)

        # Determine primary language for the module
        langs = set()
        for f in files:
            if f.suffix == ".py":
                langs.add("python")
            elif f.suffix in (".ts", ".tsx"):
                langs.add("typescript")
        lang = ", ".join(sorted(langs)) if langs else "unknown"

        module_id = store.insert_module(module_name, dir_name, total_files, 0, lang)

        # Group by subdirectory (d2)
        sub_dirs: dict[str, list[Path]] = defaultdict(list)
        for f in files:
            try:
                rel = f.relative_to(root / dir_name)
            except ValueError:
                sub_dirs[""].append(f)
                continue
            sub = str(rel.parent) if rel.parent != Path(".") else ""
            sub_dirs[sub].append(f)

        module_func_count = 0
        for sub, sub_files in sorted(sub_dirs.items()):
            sub_name = sub if sub else "(root)"
            sub_path = f"{dir_name}/{sub}" if sub else dir_name
            dir_id = store.insert_directory(sub_name, sub_path, module_id, len(sub_files))

            for f in sorted(sub_files):
                if f.suffix == ".py":
                    info = py_parser.parse(f)
                else:
                    info = ts_parser.parse(f)

                file_id = store.insert_file(info, dir_id)
                module_func_count += len(info.functions)

                for func in info.functions:
                    store.insert_calls(str(f), func)

        # Update function count
        store.conn.execute(
            "UPDATE d3_modules SET function_count = ? WHERE id = ?",
            (module_func_count, module_id),
        )
        store.conn.commit()

    # Build call graph edges: resolve unconfirmed → external where possible
    _resolve_call_edges(store)

    return store


def _resolve_call_edges(store: IndexStore):
    """Mark remaining unconfirmed calls as external."""
    store.conn.execute(
        "UPDATE calls SET relationship = 'external' WHERE relationship = 'unconfirmed' AND callee_file IS NULL"
    )
    store.conn.commit()


# ── Analysis / reporting ──────────────────────────────────────────


def print_report(store: IndexStore):
    """Print a summary report of the indexed codebase."""
    conn = store.conn

    print("\n" + "=" * 72)
    print("  CODE INDEX — Project Analysis Report")
    print("=" * 72)

    # Module summary
    modules = conn.execute("SELECT name, file_count, function_count, language FROM d3_modules ORDER BY file_count DESC").fetchall()
    print(f"\n{'Module':<24} {'Files':>6} {'Functions':>10}  Language")
    print("-" * 60)
    total_files = 0
    total_funcs = 0
    for name, fc, fnc, lang in modules:
        print(f"{name:<24} {fc:>6} {fnc:>10}  {lang}")
        total_files += fc
        total_funcs += fnc
    print("-" * 60)
    print(f"{'TOTAL':<24} {total_files:>6} {total_funcs:>10}")

    # Largest files
    print(f"\n{'— Top 15 largest files by LOC —':^72}")
    print(f"{'File':<56} {'LOC':>6}")
    print("-" * 62)
    large_files = conn.execute(
        "SELECT path, loc FROM d1_files ORDER BY loc DESC LIMIT 15"
    ).fetchall()
    for path, loc in large_files:
        short = path.replace("E:\\Academic-Agent-F\\academic-agent-framework\\", "").replace("E:/Academic-Agent-F/academic-agent-framework/", "")
        if len(short) > 54:
            short = "..." + short[-51:]
        print(f"{short:<56} {loc:>6}")

    # Most-called functions
    print(f"\n{'— Top 15 most-called internal functions —':^72}")
    print(f"{'Function':<40} {'Callers':>8}")
    print("-" * 48)
    most_called = conn.execute(
        "SELECT callee_name, COUNT(*) as cnt FROM calls WHERE relationship='direct' GROUP BY callee_name ORDER BY cnt DESC LIMIT 15"
    ).fetchall()
    for name, cnt in most_called:
        print(f"{name:<40} {cnt:>8}")

    # Call edges
    direct = conn.execute("SELECT COUNT(*) FROM calls WHERE relationship='direct'").fetchone()[0]
    external = conn.execute("SELECT COUNT(*) FROM calls WHERE relationship='external'").fetchone()[0]
    print(f"\nCall edges: {direct} direct, {external} external")

    # Files with most functions
    print(f"\n{'— Top 10 files with most functions/methods —':^72}")
    print(f"{'File':<56} {'Funcs':>6}")
    print("-" * 62)
    dense_files = conn.execute(
        "SELECT f.path, COUNT(d.id) as cnt FROM d0_functions d JOIN d1_files f ON d.file_id = f.id GROUP BY f.id ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    for path, cnt in dense_files:
        short = path.replace("E:\\Academic-Agent-F\\academic-agent-framework\\", "").replace("E:/Academic-Agent-F/academic-agent-framework/", "")
        if len(short) > 54:
            short = "..." + short[-51:]
        print(f"{short:<56} {cnt:>6}")

    # Entry points (top-level functions decorated with route/event handlers)
    print(f"\n{'— API Route files (backend/api/routers/) —':^72}")
    route_files = conn.execute(
        "SELECT path, symbols FROM d1_files WHERE path LIKE '%backend/api/routers%' ORDER BY path"
    ).fetchall()
    for path, symbols in route_files:
        short = path.replace("E:\\Academic-Agent-F\\academic-agent-framework\\", "").replace("E:/Academic-Agent-F/academic-agent-framework/", "")
        syms = json.loads(symbols) if symbols else []
        print(f"  {short}  →  {', '.join(syms[:8])}{'...' if len(syms) > 8 else ''}")

    print("\n" + "=" * 72)
    print(f"  Index database: {store.db_path}")
    print("=" * 72 + "\n")


# ── CLI ───────────────────────────────────────────────────────────


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if not root.exists():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    print(f"Indexing: {root}")
    store = index_project(root)
    print_report(store)
    store.close()
    print("Done.")


if __name__ == "__main__":
    main()
