"""Load skills from disk.

Scans `<root>/skills/*/SKILL.md`, parses frontmatter, scripts, and
references. Malformed SKILL.md files are skipped with a warning.

Thread-safe: the `SkillRegistry` can be reloaded from a background task
while queries happen on the main task (reader-writer via asyncio.Lock +
a monotonically-incremented generation counter).
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Literal, cast

import frontmatter  # python-frontmatter
import structlog

from .types import ScriptMeta, SkillMeta

log = structlog.get_logger(__name__)

_MAGIC_RE = re.compile(r"^\s*#\s*aaf:(?P<key>[a-zA-Z_-]+)(?:\s+(?P<value>.*))?\s*$")
_MAX_MAGIC_LINES = 30


class SkillRegistry:
    """Thread-safe skill registry.

    The registry holds a generation counter (`gen`) which increases every
    time the set of skills changes — clients caching expensive derivations
    (e.g. embeddings) can invalidate their cache when the number differs.
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillMeta] = {}
        self._lock = asyncio.Lock()
        self._gen = 0

    @property
    def generation(self) -> int:
        return self._gen

    def snapshot(self) -> list[SkillMeta]:
        return list(self._skills.values())

    def get(self, name: str) -> SkillMeta | None:
        return self._skills.get(name)

    async def _replace_all(self, skills: list[SkillMeta]) -> None:
        async with self._lock:
            self._skills = {s.name: s for s in skills}
            self._gen += 1

    async def _replace_one(self, skill: SkillMeta) -> None:
        async with self._lock:
            self._skills[skill.name] = skill
            self._gen += 1

    async def _drop(self, name: str) -> None:
        async with self._lock:
            if name in self._skills:
                del self._skills[name]
                self._gen += 1


class SkillLoader:
    """Discover and parse skills under a root directory."""

    def __init__(self, skills_root: Path) -> None:
        self.skills_root = Path(skills_root)
        self.registry = SkillRegistry()

    async def load_all(self) -> SkillRegistry:
        """Scan the root, replace the registry with the fresh result."""
        skills = await asyncio.to_thread(self._scan_sync)
        await self.registry._replace_all(skills)
        log.info("skill.loader.loaded", count=len(skills), root=str(self.skills_root))
        return self.registry

    async def reload(self, name: str | None = None) -> SkillRegistry:
        """Reload a single skill by name, or all skills if `name is None`."""
        if name is None:
            return await self.load_all()
        skill_dir = self.skills_root / name
        if not (skill_dir / "SKILL.md").exists():
            await self.registry._drop(name)
            log.info("skill.loader.dropped", name=name)
            return self.registry
        parsed = await asyncio.to_thread(self._parse_skill_dir, skill_dir)
        if parsed is not None:
            await self.registry._replace_one(parsed)
            log.info("skill.loader.reloaded", name=name)
        return self.registry

    # ----- synchronous scanning (runs in thread pool) ------------------

    def _scan_sync(self) -> list[SkillMeta]:
        if not self.skills_root.exists():
            log.warning("skill.loader.missing_root", path=str(self.skills_root))
            return []
        result: list[SkillMeta] = []
        for entry in sorted(self.skills_root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue
            parsed = self._parse_skill_dir(entry)
            if parsed is not None:
                result.append(parsed)
        return result

    def _parse_skill_dir(self, skill_dir: Path) -> SkillMeta | None:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            log.warning("skill.loader.no_skill_md", path=str(skill_dir))
            return None
        try:
            post = frontmatter.load(str(skill_md))
        except Exception as exc:
            log.warning("skill.loader.bad_frontmatter", path=str(skill_md), err=str(exc))
            return None

        meta = dict(post.metadata or {})
        body = (post.content or "").strip()

        # Required frontmatter fields.
        name = str(meta.get("name") or skill_dir.name).strip()

        try:
            return SkillMeta(
                name=name,
                path=skill_dir.resolve(),
                description=_as_str(meta.get("description", "")),
                domain=_as_str_or_none(meta.get("domain")),
                triggers=_as_str_list(meta.get("triggers")),
                version=_as_str(meta.get("version") or "0.0.0"),
                requires=_parse_requires(meta),
                network=_parse_network(meta),
                exclusive=bool(meta.get("exclusive", False)),
                scripts=self._parse_scripts(skill_dir / "scripts"),
                references=self._parse_references(skill_dir),
                body=body,
                raw_meta=meta,
            )
        except Exception as exc:
            log.warning("skill.loader.model_error", name=name, err=str(exc))
            return None

    def _parse_scripts(self, scripts_dir: Path) -> list[ScriptMeta]:
        if not scripts_dir.is_dir():
            return []
        out: list[ScriptMeta] = []
        for f in sorted(scripts_dir.iterdir()):
            if f.suffix != ".py" or f.name.startswith("_"):
                continue
            out.append(self._parse_script_file(f))
        return out

    def _parse_script_file(self, path: Path) -> ScriptMeta:
        try:
            source = path.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("skill.loader.bad_script_read", path=str(path), err=str(exc))
            return ScriptMeta(name=path.stem, path=path.resolve())

        description = ""
        try:
            tree = ast.parse(source)
            description = (ast.get_docstring(tree) or "").strip().split("\n", 1)[0]
        except SyntaxError:
            log.warning("skill.loader.bad_script_syntax", path=str(path))

        magic = _extract_magic_comments(source)

        return ScriptMeta(
            name=path.stem,
            path=path.resolve(),
            description=description,
            requires_network=magic.get("network", "none") == "required",
            max_duration_s=_maybe_int(magic.get("timeout")),
            uses_llm=bool(magic.get("uses-llm") is not None),
            args_schema=_maybe_json_dict(magic.get("args")),
        )

    def _parse_references(self, skill_dir: Path) -> list[Path]:
        refs: list[Path] = []
        for sub in ("references", "templates"):
            d = skill_dir / sub
            if d.is_dir():
                for f in sorted(d.rglob("*")):
                    if f.is_file():
                        refs.append(f.resolve())
        for f in sorted(skill_dir.glob("*.md")):
            if f.name in {"SKILL.md", "README.md"}:
                continue
            refs.append(f.resolve())
        return refs


# ---- helpers --------------------------------------------------------------


def _extract_magic_comments(source: str) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for line in source.splitlines()[:_MAX_MAGIC_LINES]:
        m = _MAGIC_RE.match(line)
        if m:
            out[m.group("key")] = (m.group("value") or "").strip() or None
    return out


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _as_str_or_none(v: Any) -> str | None:
    s = _as_str(v)
    return s or None


def _as_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _parse_requires(meta: dict[str, Any]) -> list[str]:
    # Accept either top-level `requires: [...]` or `compatibility.requires: [...]`
    compat = meta.get("compatibility") or {}
    if isinstance(compat, dict) and compat.get("requires"):
        return _as_str_list(compat.get("requires"))
    return _as_str_list(meta.get("requires"))


def _parse_network(meta: dict[str, Any]) -> Literal["none", "optional", "required"]:
    val = str(meta.get("network", "none")).lower()
    if val in {"none", "optional", "required"}:
        return cast(Literal["none", "optional", "required"], val)
    return "none"


def _maybe_int(v: str | None) -> int | None:
    if v is None:
        return None
    try:
        return int(v.strip())
    except (ValueError, AttributeError):
        return None


def _maybe_json_dict(v: str | None) -> dict[str, Any] | None:
    if not v:
        return None
    try:
        parsed = json.loads(v)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


__all__ = ["SkillLoader", "SkillRegistry"]
