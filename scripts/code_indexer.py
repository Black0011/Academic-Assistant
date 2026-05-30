"""Code Indexer — builds a structured, queryable code map from source files.

Produces .code-reading/index.db with a 4-layer hierarchy:
  d3_modules    — top-level business modules
  d2_directories — subdomain directories
  d1_files      — files with symbol lists
  d0_functions  — function signatures, line ranges, call edges
"""
from __future__ import annotations
import ast, json, re, sqlite3, sys
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict

@dataclass
class FunctionInfo:
    name: str; signature: str; line_start: int; line_end: int
    kind: str = "function"; decorators: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

@dataclass
class FileInfo:
    path: Path; name: str; language: str; loc: int
    functions: list[FunctionInfo] = field(default_factory=list)
    imports: list[tuple[str, list[str]]] = field(default_factory=list)
    top_level_classes: list[str] = field(default_factory=list)
    @property
    def symbols(self) -> list[str]:
        return [f.name for f in self.functions] + self.top_level_classes

class PythonParser:
    def parse(self, file_path: Path) -> FileInfo:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        info = FileInfo(path=file_path, name=file_path.name, language="python", loc=len(source.splitlines()))
        try: tree = ast.parse(source)
        except SyntaxError: return info
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names: info.imports.append((alias.name, []))
            elif isinstance(node, ast.ImportFrom) and node.module:
                info.imports.append((node.module, [a.name for a in node.names]))
        for node in ast.iter_child_nodes(tree):
            func = self._extract(node, source)
            if func: info.functions.append(func)
            elif isinstance(node, ast.ClassDef):
                info.top_level_classes.append(node.name)
                for body_item in node.body:
                    m = self._extract(body_item, source)
                    if m: m.kind = "method"; info.functions.append(m)
        return info

    def _extract(self, node, source) -> FunctionInfo | None:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): return None
        decorators = [ast.unparse(d) if hasattr(ast, "unparse") else ast.dump(d) for d in node.decorator_list]
        args = [a.arg for a in node.args.args]
        kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
        sig = f"def {node.name}({', '.join(args)})"
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                n = child.func.id if isinstance(child.func, ast.Name) else (child.func.attr if isinstance(child.func, ast.Attribute) else None)
                if n: calls.append(n)
        return FunctionInfo(name=node.name, signature=sig, line_start=node.lineno, line_end=node.end_lineno or node.lineno, kind=kind, decorators=decorators, calls=calls)

TS_FUNC_RE = re.compile(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)', re.MULTILINE)
TS_ARROW_RE = re.compile(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*[:=]\s*(?:async\s*)?\([^)]*\)\s*=>', re.MULTILINE)
TS_CLASS_RE = re.compile(r'(?:export\s+)?class\s+(\w+)', re.MULTILINE)
TS_IMPORT_RE = re.compile(r'import\s+\{([^}]+)\}\s+from\s+[\'"]([^\'"]+)[\'"]', re.MULTILINE)
TS_DEFAULT_IMPORT_RE = re.compile(r'import\s+(\w+)\s+from\s+[\'"]([^\'"]+)[\'"]', re.MULTILINE)

class TypeScriptParser:
    def parse(self, file_path: Path) -> FileInfo:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        info = FileInfo(path=file_path, name=file_path.name, language="tsx" if file_path.suffix == ".tsx" else "typescript", loc=len(source.splitlines()))
        for m in TS_IMPORT_RE.finditer(source):
            names = [n.strip().split(" as ")[0].strip() for n in m.group(1).split(",")]
            info.imports.append((m.group(2), names))
        for m in TS_DEFAULT_IMPORT_RE.finditer(source):
            info.imports.append((m.group(2), [m.group(1)]))
        for m in TS_CLASS_RE.finditer(source): info.top_level_classes.append(m.group(1))
        for m in TS_FUNC_RE.finditer(source):
            name, args, line_no = m.group(1), m.group(2), source[:m.start()].count("\n") + 1
            info.functions.append(FunctionInfo(name=name, signature=f"function {name}({args})", line_start=line_no, line_end=line_no, kind="function"))
        for m in TS_ARROW_RE.finditer(source):
            name, line_no = m.group(1), source[:m.start()].count("\n") + 1
            if name and name[0].isupper(): kind = "component"
            else: kind = "function"
            info.functions.append(FunctionInfo(name=name, signature=f"const {name} = (...) => ...", line_start=line_no, line_end=line_no, kind=kind))
        return info

class IndexStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self._init_schema()
    def _init_schema(self):
        self.conn.executescript("""
        DROP TABLE IF EXISTS calls; DROP TABLE IF EXISTS imports;
        DROP TABLE IF EXISTS d0_functions; DROP TABLE IF EXISTS d1_files;
        DROP TABLE IF EXISTS d2_directories; DROP TABLE IF EXISTS d3_modules;
        CREATE TABLE d3_modules (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, path TEXT, file_count INTEGER DEFAULT 0, function_count INTEGER DEFAULT 0, language TEXT);
        CREATE TABLE d2_directories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, path TEXT UNIQUE, module_id INTEGER REFERENCES d3_modules(id), file_count INTEGER DEFAULT 0);
        CREATE TABLE d1_files (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, path TEXT UNIQUE, directory_id INTEGER REFERENCES d2_directories(id), loc INTEGER DEFAULT 0, language TEXT, symbols TEXT);
        CREATE TABLE d0_functions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, signature TEXT, file_id INTEGER REFERENCES d1_files(id), line_start INTEGER, line_end INTEGER, kind TEXT, decorators TEXT);
        CREATE TABLE calls (id INTEGER PRIMARY KEY AUTOINCREMENT, caller_file TEXT, caller_func TEXT, callee_name TEXT, callee_file TEXT, relationship TEXT DEFAULT 'unconfirmed');
        CREATE TABLE imports (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT, imported_module TEXT, imported_names TEXT);
        CREATE INDEX idx_d0_file ON d0_functions(file_id);
        CREATE INDEX idx_d1_dir ON d1_files(directory_id);
        CREATE INDEX idx_d2_module ON d2_directories(module_id);
        CREATE INDEX idx_calls_callee ON calls(callee_name);
        CREATE INDEX idx_calls_caller ON calls(caller_func);
        """)
    def insert_module(self, name, path, fc, func_count, lang):
        c = self.conn.execute("INSERT INTO d3_modules (name,path,file_count,function_count,language) VALUES(?,?,?,?,?)", (name,path,fc,func_count,lang)); self.conn.commit(); return c.lastrowid
    def insert_directory(self, name, path, mid, fc):
        c = self.conn.execute("INSERT INTO d2_directories (name,path,module_id,file_count) VALUES(?,?,?,?)", (name,path,mid,fc)); self.conn.commit(); return c.lastrowid
    def insert_file(self, info: FileInfo, did: int) -> int:
        symbols_json = json.dumps(info.symbols, ensure_ascii=False)
        c = self.conn.execute("INSERT INTO d1_files (name,path,directory_id,loc,language,symbols) VALUES(?,?,?,?,?,?)", (info.name, str(info.path), did, info.loc, info.language, symbols_json))
        self.conn.commit(); fid = c.lastrowid
        for func in info.functions:
            self.conn.execute("INSERT INTO d0_functions (name,signature,file_id,line_start,line_end,kind,decorators) VALUES(?,?,?,?,?,?,?)", (func.name, func.signature, fid, func.line_start, func.line_end, func.kind, json.dumps(func.decorators, ensure_ascii=False)))
        for mod, names in info.imports:
            self.conn.execute("INSERT INTO imports (file_path,imported_module,imported_names) VALUES(?,?,?)", (str(info.path), mod, json.dumps(names, ensure_ascii=False)))
        self.conn.commit(); return fid
    def insert_calls(self, fp, func):
        for callee in func.calls:
            c = self.conn.execute("SELECT f.path FROM d0_functions d JOIN d1_files f ON d.file_id=f.id WHERE d.name=?", (callee,))
            row = c.fetchone()
            if row: self.conn.execute("INSERT INTO calls (caller_file,caller_func,callee_name,callee_file,relationship) VALUES(?,?,?,?,'direct')", (fp, func.name, callee, row[0]))
            else: self.conn.execute("INSERT INTO calls (caller_file,caller_func,callee_name,callee_file,relationship) VALUES(?,?,?,NULL,'unconfirmed')", (fp, func.name, callee))
        self.conn.commit()
    def close(self): self.conn.close()

def index_project(root: Path) -> IndexStore:
    root = root.resolve()
    db_path = root / ".code-reading" / "index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = IndexStore(db_path)
    py_parser, ts_parser = PythonParser(), TypeScriptParser()
    py_files, ts_files = [], []
    for scan_dir in ["backend", "frontend/src", "sdk", "mcp-servers", "scripts", "cli"]:
        sp = root / scan_dir
        if not sp.exists(): continue
        for f in sp.rglob("*.py"):
            if "test" not in f.name.lower() and "__pycache__" not in str(f) and f.name != "__init__.py": py_files.append(f)
        for f in sp.rglob("*.ts"): ts_files.append(f)
        for f in sp.rglob("*.tsx"): ts_files.append(f)
    top_dirs = defaultdict(list)
    for f in py_files + ts_files:
        try: rel = f.relative_to(root)
        except ValueError: continue
        top_dirs[rel.parts[0]].append(f)
    module_map = {"backend":"Backend Core","frontend":"Frontend","sdk":"Python SDK","mcp-servers":"MCP Servers","scripts":"Admin Scripts","cli":"CLI","skills":"Runtime Skills","rules":"Runtime Rules"}
    for dir_name, files in sorted(top_dirs.items()):
        mod_name = module_map.get(dir_name, dir_name)
        langs = set(); _ = [langs.add("python") if f.suffix==".py" else langs.add("typescript") for f in files]
        mid = store.insert_module(mod_name, dir_name, len(files), 0, ", ".join(sorted(langs)) if langs else "unknown")
        sub_dirs = defaultdict(list)
        for f in files:
            try: rel = f.relative_to(root/dir_name)
            except ValueError: sub_dirs[""].append(f); continue
            sub = str(rel.parent) if rel.parent != Path(".") else ""
            sub_dirs[sub].append(f)
        mfc = 0
        for sub, sfiles in sorted(sub_dirs.items()):
            sub_name = sub if sub else "(root)"
            sub_path = f"{dir_name}/{sub}" if sub else dir_name
            did = store.insert_directory(sub_name, sub_path, mid, len(sfiles))
            for f in sorted(sfiles):
                info = py_parser.parse(f) if f.suffix==".py" else ts_parser.parse(f)
                store.insert_file(info, did)
                mfc += len(info.functions)
                for func in info.functions: store.insert_calls(str(f), func)
        store.conn.execute("UPDATE d3_modules SET function_count=? WHERE id=?", (mfc, mid)); store.conn.commit()
    store.conn.execute("UPDATE calls SET relationship='external' WHERE relationship='unconfirmed' AND callee_file IS NULL"); store.conn.commit()
    return store

def print_report(store: IndexStore, root: Path):
    conn = store.conn
    root_str = str(root)
    print("\n" + "="*60)
    print("  CODE INDEX — Project Structure Report")
    print("="*60)
    modules = conn.execute("SELECT name,file_count,function_count,language FROM d3_modules ORDER BY file_count DESC").fetchall()
    print(f"\n{'Module':<24} {'Files':>6} {'Funcs':>8}  Language")
    print("-"*56)
    tf, tfn = 0, 0
    for n, fc, fnc, l in modules: print(f"{n:<24} {fc:>6} {fnc:>8}  {l}"); tf+=fc; tfn+=fnc
    print("-"*56); print(f"{'TOTAL':<24} {tf:>6} {tfn:>8}")
    print(f"\n{'Top 10 files by LOC':^60}")
    for p, loc in conn.execute("SELECT path,loc FROM d1_files ORDER BY loc DESC LIMIT 10").fetchall():
        s = p.replace(root_str + "\\", "").replace(root_str + "/", "")
        if len(s)>55: s="..."+s[-52:]
        print(f"  {loc:>5} LOC  {s}")
    direct = conn.execute("SELECT COUNT(*) FROM calls WHERE relationship='direct'").fetchone()[0]
    ext = conn.execute("SELECT COUNT(*) FROM calls WHERE relationship='external'").fetchone()[0]
    print(f"\nDirect call edges: {direct}")
    print(f"External calls:    {ext}")
    print(f"\nIndex: {store.db_path}")
    print("="*60+"\n")

def main():
    root = Path(sys.argv[1]) if len(sys.argv)>1 else Path.cwd()
    if not root.exists(): print(f"Error: {root}", file=sys.stderr); sys.exit(1)
    print(f"Indexing: {root}")
    store = index_project(root)
    print_report(store, root)
    store.close()

if __name__ == "__main__":
    main()
