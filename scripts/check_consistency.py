#!/usr/bin/env python3
"""Mechanical consistency gate for the Academic Agent Framework.

This script is the merge bar. It enforces invariants that documentation
can't (because docs rot). Every violation is reported with an inline
``Fix:`` hint; agents and humans should fix the artefact, not the check.

Run locally:
    python3 scripts/check_consistency.py
    make consistency

Run in CI:
    .github/workflows/consistency.yml triggers this on every push / PR.

Adding a check:
    Each check is a top-level function ``check_<thing>(repo, errors)`` that
    appends ``Issue`` records. Register it in :func:`run_checks`. Keep
    checks fast and **import-free** — the goal is a reliable signal in <5s
    on a cold cache, not exhaustive correctness.

The script is import-free for the backend code under test: we parse YAML
frontmatter and Python AST, never executing application code.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Issue model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """A single consistency violation. ``fix`` MUST be actionable."""

    where: str
    msg: str
    fix: str
    severity: str = "error"  # "error" | "warn"

    def render(self) -> str:
        prefix = "ERROR" if self.severity == "error" else "WARN "
        return f"  [{prefix}] {self.where}\n         {self.msg}\n         Fix: {self.fix}"


# ---------------------------------------------------------------------------
# Frontmatter parsing (no PyYAML dependency — keep this script stdlib-only)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    """Best-effort YAML-frontmatter parser for our flat schemas.

    Handles the subset we actually use:

    * Scalar k/v (``key: value``)
    * Flow-style lists (``key: [a, b, c]``)
    * Block lists (``key:`` followed by ``  - a``)
    * One-level nested maps (``key:`` followed by ``  sub: val``)
    * Multi-line scalars (``key: >-`` or ``key: |``)

    Decision is made at the *first* indented child line. Anything beyond
    this subset should keep its own parser — but our schemas are flat by
    design (see SKILL.md / rule frontmatter docs) so this stays simple.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    body = m.group(1)
    lines = body.splitlines()
    out: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw.startswith(" "):
            i += 1  # stray indented line at top level — skip
            continue
        if ":" not in raw:
            i += 1
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        i += 1
        if value == "":
            # Block — peek indented children, decide list vs map at first child.
            children: list[str] = []
            while i < len(lines):
                line = lines[i]
                if not line.strip():
                    i += 1
                    continue
                if not line.startswith("  "):
                    break
                children.append(line)
                i += 1
            if not children:
                out[key] = ""
            elif children[0].lstrip().startswith("- "):
                out[key] = [
                    _scalar(c.lstrip()[2:].strip()) for c in children if c.lstrip().startswith("- ")
                ]
            else:
                nested: dict[str, Any] = {}
                for c in children:
                    s = c.strip()
                    if ":" in s and not s.startswith("- "):
                        k, v = s.split(":", 1)
                        nested[k.strip()] = _scalar(v.strip())
                out[key] = nested
        elif value in {">-", ">", "|", "|-"}:
            # Multi-line scalar — collapse indented continuation.
            scalar_lines: list[str] = []
            while i < len(lines):
                line = lines[i]
                if not line.strip():
                    i += 1
                    continue
                if not line.startswith("  "):
                    break
                scalar_lines.append(line.lstrip())
                i += 1
            out[key] = " ".join(scalar_lines).strip()
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            out[key] = [_scalar(p.strip()) for p in inner.split(",") if p.strip()] if inner else []
        else:
            out[key] = _scalar(value)
    return out


def _scalar(v: str) -> Any:
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if v in {"true", "True"}:
        return True
    if v in {"false", "False"}:
        return False
    return v


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

ALLOWED_DOMAINS = {
    "research",
    "writing",
    "revision",
    "rebuttal",
    "survey",
    "presentation",
    "ideation",
    "meta",
}

REQUIRED_AGENTS_DIRS = (
    "",
    "skills",
    "rules",
    "backend",
    "backend/api",
    "backend/workflows",
    "backend/core/skill_host",
    "backend/memory",
    "frontend",
)


def check_agents_files(repo: Path, errors: list[Issue]) -> None:
    """Every directory listed as a navigation entry must have AGENTS.md."""
    for rel in REQUIRED_AGENTS_DIRS:
        target = repo / rel / "AGENTS.md"
        if not target.exists():
            errors.append(
                Issue(
                    where=str(target.relative_to(repo)),
                    msg="missing AGENTS.md (navigation entry promised by root AGENTS.md)",
                    fix=f"create `{rel}/AGENTS.md` (≤150 lines, point to deeper docs); "
                    f"see existing AGENTS.md files for the shape.",
                )
            )


def check_skill_frontmatter(repo: Path, errors: list[Issue]) -> None:
    """Every skill folder under ``skills/`` must have a valid SKILL.md."""
    skills_dir = repo / "skills"
    if not skills_dir.is_dir():
        return
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith((".", "_")) or child.name == "__pycache__":
            # Underscore-prefixed dirs are reserved by the SkillLoader for
            # framework use (e.g. ``_disabled/``, ``_pending/`` from the
            # admin layer). They never hold user skills and must not have
            # SKILL.md files.
            continue
        skill_md = child / "SKILL.md"
        rel = skill_md.relative_to(repo)
        if not skill_md.is_file():
            errors.append(
                Issue(
                    where=str(rel),
                    msg=f"skill folder `{child.name}` has no SKILL.md",
                    fix=f"create `skills/{child.name}/SKILL.md` with the frontmatter schema "
                    f"in `skills/AGENTS.md`.",
                )
            )
            continue
        text = skill_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm is None:
            errors.append(
                Issue(
                    where=str(rel),
                    msg="missing or malformed YAML frontmatter (need `---` … `---` at top)",
                    fix="add a YAML block at the very top with `name`, `description`, "
                    "`domain`, `triggers`, `version` — see `skills/AGENTS.md`.",
                )
            )
            continue
        # name == folder
        name = fm.get("name")
        if not isinstance(name, str) or not name:
            errors.append(
                Issue(
                    where=str(rel),
                    msg="frontmatter `name` is required and must be a string",
                    fix=f"set `name: {child.name}` (must equal the folder name).",
                )
            )
        elif name != child.name:
            errors.append(
                Issue(
                    where=str(rel),
                    msg=f"frontmatter `name: {name}` does not match folder `{child.name}`",
                    fix=f"either rename the folder to `{name}` or set `name: {child.name}`.",
                )
            )
        # description
        if not fm.get("description"):
            errors.append(
                Issue(
                    where=str(rel),
                    msg="frontmatter `description` missing or empty",
                    fix="set `description: >-` followed by a one-paragraph capability "
                    'summary ending with "Use when …".',
                )
            )
        # domain
        domain = fm.get("domain")
        if not isinstance(domain, str) or not domain:
            errors.append(
                Issue(
                    where=str(rel),
                    msg="frontmatter `domain` missing",
                    fix=f"set `domain:` to one of {sorted(ALLOWED_DOMAINS)}.",
                )
            )
        elif domain not in ALLOWED_DOMAINS:
            errors.append(
                Issue(
                    where=str(rel),
                    msg=f"frontmatter `domain: {domain}` is not in the allowed set",
                    fix=f"use one of {sorted(ALLOWED_DOMAINS)} or extend "
                    f"`scripts/check_consistency.py:ALLOWED_DOMAINS` in the same PR.",
                )
            )
        # triggers
        triggers = fm.get("triggers")
        if not isinstance(triggers, list) or not triggers:
            errors.append(
                Issue(
                    where=str(rel),
                    msg="frontmatter `triggers` missing or empty (need ≥1)",
                    fix="add a list `triggers:` with ≥1 string the matcher can hash, "
                    "e.g. `triggers:\\n  - search papers`.",
                )
            )
        # version
        version = fm.get("version")
        if not isinstance(version, str) or not re.match(r"^\d+\.\d+\.\d+$", version):
            errors.append(
                Issue(
                    where=str(rel),
                    msg=f"frontmatter `version` must be SemVer (got {version!r})",
                    fix='set `version: "1.0.0"` (or whatever SemVer fits the change).',
                )
            )


def check_rule_frontmatter(repo: Path, errors: list[Issue]) -> None:
    """Every ``rules/*.md`` file must have ``description`` + ``alwaysApply``."""
    rules_dir = repo / "rules"
    if not rules_dir.is_dir():
        return
    for path in sorted(rules_dir.glob("*.md")):
        if path.name == "AGENTS.md":
            continue
        rel = path.relative_to(repo)
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm is None:
            errors.append(
                Issue(
                    where=str(rel),
                    msg="rule file missing YAML frontmatter",
                    fix="prepend `---\\ndescription: …\\nalwaysApply: true\\n---` "
                    "(see `rules/AGENTS.md`).",
                )
            )
            continue
        if not fm.get("description"):
            errors.append(
                Issue(
                    where=str(rel),
                    msg="rule frontmatter missing `description`",
                    fix="add `description: <one-line summary>`.",
                )
            )
        if "alwaysApply" not in fm:
            errors.append(
                Issue(
                    where=str(rel),
                    msg="rule frontmatter missing `alwaysApply`",
                    fix="add `alwaysApply: true` (or `false` plus a `triggers:` list).",
                )
            )
        elif fm.get("alwaysApply") is False and not fm.get("triggers"):
            errors.append(
                Issue(
                    where=str(rel),
                    msg="rule has `alwaysApply: false` but no `triggers`",
                    fix="add a non-empty `triggers:` list, or set `alwaysApply: true`.",
                )
            )


def check_routers_wired(repo: Path, errors: list[Issue]) -> None:
    """Every ``backend/api/routers/*.py`` is included in ``backend/app.py``."""
    routers_dir = repo / "backend" / "api" / "routers"
    app_py = repo / "backend" / "app.py"
    if not routers_dir.is_dir() or not app_py.is_file():
        return
    app_text = app_py.read_text(encoding="utf-8")
    for path in sorted(routers_dir.glob("*.py")):
        if path.name.startswith("_") or path.name == "__init__.py":
            continue
        stem = path.stem
        rel = path.relative_to(repo)
        # Lightweight match: any of three idioms is fine
        idioms = (
            f"include_router({stem}_router.router)",
            f"include_router({stem}.router)",
            f".routers.{stem} import",
        )
        if not any(idiom in app_text for idiom in idioms):
            errors.append(
                Issue(
                    where=str(rel),
                    msg=f"router `{stem}` exists but is not included in backend/app.py",
                    fix=f"add `from backend.api.routers import {stem} as {stem}_router` "
                    f"and `app.include_router({stem}_router.router)` in `backend/app.py`.",
                )
            )


def check_workflow_names(repo: Path, errors: list[Issue]) -> None:
    """Every concrete BaseWorkflow subclass must declare a non-empty ``name``."""
    wf_dir = repo / "backend" / "workflows"
    if not wf_dir.is_dir():
        return
    seen_names: dict[str, str] = {}
    for path in sorted(wf_dir.glob("*.py")):
        if path.name in {"__init__.py", "base.py", "primitives.py", "registry.py"}:
            continue
        rel = path.relative_to(repo)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(
                Issue(
                    where=str(rel),
                    msg=f"failed to parse: {exc}",
                    fix="fix the syntax error before resubmitting.",
                )
            )
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not _inherits_from(node, {"BaseWorkflow"}):
                continue
            name_value: str | None = None
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name) and tgt.id == "name":
                            if isinstance(stmt.value, ast.Constant) and isinstance(
                                stmt.value.value, str
                            ):
                                name_value = stmt.value.value
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.target.id == "name" and isinstance(stmt.value, ast.Constant):
                        if isinstance(stmt.value.value, str):
                            name_value = stmt.value.value
            if not name_value:
                errors.append(
                    Issue(
                        where=f"{rel}:{node.lineno}",
                        msg=f"workflow class `{node.name}` has no string `name` attribute",
                        fix=f'add `name = "<unique-kebab>"` to `{node.name}`; the registry '
                        f"refuses to discover nameless workflows.",
                    )
                )
                continue
            if name_value in seen_names:
                errors.append(
                    Issue(
                        where=f"{rel}:{node.lineno}",
                        msg=f"workflow name `{name_value}` already used by "
                        f"{seen_names[name_value]}",
                        fix="rename one of the workflows; names must be unique across "
                        "`backend/workflows/`.",
                    )
                )
            else:
                seen_names[name_value] = f"{rel}:{node.lineno}"


def check_router_integration_tests(repo: Path, errors: list[Issue]) -> None:
    """Each router resource MUST have a matching integration test.

    The test file's existence is the gate; coverage of every endpoint inside
    the file is the human reviewer's job. We use the standard naming
    convention ``backend/tests/integration/test_app_<resource>.py`` so the
    pairing is mechanical.
    """
    routers_dir = repo / "backend" / "api" / "routers"
    tests_dir = repo / "backend" / "tests" / "integration"
    if not routers_dir.is_dir() or not tests_dir.is_dir():
        return
    test_files = {p.name for p in tests_dir.glob("test_app_*.py")}
    for path in sorted(routers_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        stem = path.stem
        expected = f"test_app_{stem}.py"
        if expected not in test_files:
            errors.append(
                Issue(
                    where=str(path.relative_to(repo)),
                    msg=f"no integration test `tests/integration/{expected}` for router `{stem}`",
                    fix=f"create `backend/tests/integration/{expected}` with at least one "
                    f"happy-path AsyncClient call against `/api/{stem}` "
                    f"(see existing siblings for the fixture pattern).",
                )
            )


def check_no_print_statements(repo: Path, errors: list[Issue]) -> None:
    """`print(` is banned inside backend/ — use structlog instead."""
    backend = repo / "backend"
    if not backend.is_dir():
        return
    for path in backend.rglob("*.py"):
        if any(
            part in {"tests", "scripts", "__pycache__"} for part in path.relative_to(repo).parts
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # Quick filter to keep this pass O(N).
        if "print(" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "print(" in stripped and not stripped.startswith(("logger", "log")):
                # Allow inline opt-outs via the marker string ``noqa-print``.
                if "noqa-print" in line:
                    continue
                errors.append(
                    Issue(
                        where=f"{path.relative_to(repo)}:{lineno}",
                        msg="`print(` is banned in backend code (silent in JSON logs)",
                        fix="replace with `log = structlog.get_logger(__name__); "
                        'log.info("event_name", k=v)`. To silence intentionally, '
                        "append `# noqa-print` to that line.",
                        severity="warn",
                    )
                )
                break  # one warning per file is enough


def check_frontend_no_inline_fetch(repo: Path, errors: list[Issue]) -> None:
    """Frontend must call backend through `lib/api.ts` only."""
    fe_src = repo / "frontend" / "src"
    if not fe_src.is_dir():
        return
    allowed = {fe_src / "lib" / "api.ts"}
    for path in fe_src.rglob("*.ts*"):
        if path in allowed:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "fetch(" not in text and "new EventSource(" not in text:
            continue
        # Match a `fetch(` call where the preceding character is NOT a letter,
        # digit or underscore — this filters out React Query's `.refetch()` /
        # `.prefetch()` and `fetchEventSource(`.
        fetch_call = re.compile(r"(?<![A-Za-z0-9_])fetch\(")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith(("//", "/*", "*")):
                continue
            if "fetchEventSource(" in line:
                continue  # @microsoft/fetch-event-source is fine
            if fetch_call.search(stripped):
                errors.append(
                    Issue(
                        where=f"{path.relative_to(repo)}:{lineno}",
                        msg="raw `fetch(` outside `lib/api.ts` — bypasses error/timeout/auth",
                        fix="route the call through `api<T>(path, opts)` from "
                        "`@/lib/api`. If you need to attach auth headers, fix it in api.ts.",
                    )
                )
                break
            if "new EventSource(" in stripped:
                errors.append(
                    Issue(
                        where=f"{path.relative_to(repo)}:{lineno}",
                        msg="`new EventSource(` cannot carry auth headers",
                        fix="use `useTaskStream` (or `fetchEventSource` from "
                        "`@microsoft/fetch-event-source`) instead.",
                    )
                )
                break


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _inherits_from(node: ast.ClassDef, names: set[str]) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in names:
            return True
        if isinstance(base, ast.Attribute) and base.attr in names:
            return True
    return False


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


CHECKS: tuple[tuple[str, Any], ...] = (
    ("agents-files", check_agents_files),
    ("skills", check_skill_frontmatter),
    ("rules", check_rule_frontmatter),
    ("routers-wired", check_routers_wired),
    ("workflows", check_workflow_names),
    ("integration-tests", check_router_integration_tests),
    ("no-print", check_no_print_statements),
    ("no-inline-fetch", check_frontend_no_inline_fetch),
)


def run_checks(repo: Path, only: Iterable[str] | None) -> list[Issue]:
    selected = set(only) if only else None
    issues: list[Issue] = []
    for name, fn in CHECKS:
        if selected is not None and name not in selected:
            continue
        fn(repo, issues)
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AAF mechanical consistency check")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[name for name, _ in CHECKS],
        help="run a subset of checks (default: all)",
    )
    parser.add_argument(
        "--no-warn-fail", action="store_true", help="exit 0 even if there are warnings"
    )
    args = parser.parse_args(argv)

    issues = run_checks(REPO_ROOT, args.only)
    if not issues:
        print("OK · all consistency checks passed")
        return 0

    errs = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]

    if errs:
        print(f"\n{len(errs)} error(s):")
        for i in errs:
            print(i.render())
    if warns:
        print(f"\n{len(warns)} warning(s):")
        for i in warns:
            print(i.render())

    if errs:
        return 1
    if warns and not args.no_warn_fail:
        return 0  # warnings don't fail by default; CI promotes via flag
    return 0


if __name__ == "__main__":
    sys.exit(main())
