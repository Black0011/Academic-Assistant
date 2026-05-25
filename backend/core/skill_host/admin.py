"""HTTP-driven skill management.

This module is the *only* thing that mutates ``skills/`` from the request
path. The runtime (``SkillLoader`` / ``SkillExecutor``) stays read-only —
admin writes go through a staging dir and an atomic ``rename``, then
trigger a single-name reload so the in-memory registry reflects the new
state without restarting the process.

Layout under ``<skills_root>``::

    <skills_root>/
    ├── <name>/                 # active skills (loader scans these)
    │   ├── SKILL.md
    │   └── scripts/*.py
    ├── _disabled/              # disabled-but-recoverable
    │   └── <name>/
    └── _pending/               # transient staging area
        └── <name>-<timestamp>/

Why a staging dir? Two reasons:

1. We want to validate the payload (frontmatter, magic comments, file
   sizes, path safety) **before** the loader can see half of a skill.
2. ``os.rename`` is atomic on POSIX — once the staged dir is sane we can
   swap it into place even if a concurrent loader scan is running, and
   either it sees the old state or the new state, never something
   half-written.

Design constraints
------------------
* No PyYAML in the validator's body (we already use ``frontmatter`` in
  the loader; reusing it keeps a single source of parsing truth).
* Path-safety is rigorous: only ``SKILL.md`` and ``scripts/*.py`` are
  allowed; any ``..``, absolute path, hidden file, or symlink is
  rejected with a structured error.
* Every write path bumps the loader generation via
  :meth:`SkillHost.reload(name)` so caches in the matcher (embeddings)
  invalidate on the next ``select_and_inject`` call.
* The runtime invariant from ``backend/core/skill_host/AGENTS.md`` —
  *"never edit skills/<name>/ in place from a request handler"* — is
  enforced here by structural construction, not by policy alone: every
  `commit_*` helper writes to the pending dir and then renames into
  place; nothing else is exposed.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import frontmatter
import structlog
from pydantic import BaseModel, ConfigDict, Field

from .registry import SkillHost

log = structlog.get_logger(__name__)

# --- limits ----------------------------------------------------------------
MAX_SKILL_NAME_LEN = 64
MAX_SCRIPTS_PER_SKILL = 20
MAX_SCRIPT_BYTES = 64 * 1024  # 64 KB
MAX_TOTAL_BYTES = 1024 * 1024  # 1 MB across SKILL.md + every script
MAX_BODY_BYTES = 256 * 1024  # 256 KB for SKILL.md body
ALLOWED_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ALLOWED_SCRIPT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\.py$")

DISABLED_DIR = "_disabled"
PENDING_DIR = "_pending"
TRASH_DIR = "_trash"


# --- input DTOs ------------------------------------------------------------


class SkillScriptInput(BaseModel):
    """One script body inside :class:`SkillInstallInput`.

    ``content`` is the literal Python source; magic comments are honoured
    by the loader at scan time.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="filename stem; '<name>.py' on disk")
    content: str = Field(..., description="UTF-8 Python source; ≤ 64 KB")


class SkillInstallInput(BaseModel):
    """JSON body accepted by ``POST /api/skills`` and ``PATCH /api/skills/{name}``.

    Tarball uploads will land in a follow-up; the JSON form already
    covers the "script + SKILL.md" pair which is the core use case
    (creating / editing a skill in the UI).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=MAX_SKILL_NAME_LEN)
    body_md: str = Field(..., description="Full SKILL.md content including frontmatter")
    scripts: list[SkillScriptInput] = Field(default_factory=list)
    overwrite: bool = Field(False, description="True allows replacing an existing skill")


# --- error type ------------------------------------------------------------


class SkillAdminError(Exception):
    """Raised by every validator/installer in this module.

    ``code`` is a stable string the router can map to an HTTP status:
    ``"validation"`` → 400, ``"conflict"`` → 409, ``"not_found"`` → 404,
    ``"limit"`` → 413, anything else → 500.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- result DTOs -----------------------------------------------------------


@dataclass(frozen=True)
class SkillSnapshot:
    """Read-only summary used by the admin layer's return values.

    The router maps this to its own response model — we keep the admin
    return surface minimal so transport schemas evolve independently.
    """

    name: str
    enabled: bool
    version_hash: str
    loaded_from: Path
    body_md: str = ""
    scripts: list[Path] = field(default_factory=list)


# --- P14.C: edge-edit DTOs -------------------------------------------------


EdgeKind = Literal["downstream", "upstream"]


@dataclass(frozen=True)
class EdgeOp:
    """One edge mutation operation, scoped to ``<source>``'s frontmatter.

    ``kind="downstream"`` ⇒ ``source.compatibility.downstream`` += target;
    ``kind="upstream"``   ⇒ ``source.compatibility.upstream``   += target.

    Removes search the legacy top-level ``downstream_skills`` field too,
    because nine in-tree skills use that form (writing-core, peer-review,
    paper-orchestration, brainstorming-research, evidence-driven-writing,
    experiment-results-planning, writing-chapters, prompts-collection,
    verification). Without this the graph view's "delete edge" button
    would silently no-op for those.
    """

    kind: EdgeKind
    target: str


@dataclass(frozen=True)
class EdgeUpdateReport:
    """Side-band metadata about a successful ``update_edges`` call.

    Used by the router to surface UX-relevant hints. Notably, ``warnings``
    flags decorative-comment loss so the UI can show a one-time tooltip
    rather than the user discovering a missing comment days later.
    """

    added: list[tuple[str, str]] = field(default_factory=list)  # (kind, target)
    removed: list[tuple[str, str]] = field(default_factory=list)
    skipped_dup: list[tuple[str, str]] = field(default_factory=list)
    skipped_missing: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- the service -----------------------------------------------------------


class SkillAdmin:
    """Mutating layer on top of :class:`SkillHost`."""

    def __init__(self, host: SkillHost) -> None:
        self._host = host
        self._root = host.skills_root
        self._root.mkdir(parents=True, exist_ok=True)
        # The reserved sub-dirs (``_disabled/`` / ``_pending/``) are
        # created lazily inside the methods that need them. That keeps a
        # fresh ``skills/`` checkout free of empty admin scaffolding,
        # which the consistency check would otherwise have to special-
        # case beyond the loader's "underscore-prefix is reserved" rule.

    # ---- read-only helpers ---------------------------------------------

    @property
    def host(self) -> SkillHost:
        return self._host

    def list_disabled(self) -> list[str]:
        """Return skill names currently parked under ``_disabled/``."""
        d = self._root / DISABLED_DIR
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith("_"))

    def is_enabled(self, name: str) -> bool:
        return self._host.get_skill(name) is not None

    def version_hash(self, name: str) -> str:
        """Stable content hash of the on-disk skill (SKILL.md + scripts)."""
        skill_dir = self._resolve_active_dir(name)
        return _hash_skill_dir(skill_dir) if skill_dir is not None else ""

    def snapshot(self, name: str) -> SkillSnapshot | None:
        """Best-effort read of an installed skill (active *or* disabled)."""
        meta = self._host.get_skill(name)
        if meta is not None:
            return SkillSnapshot(
                name=name,
                enabled=True,
                version_hash=_hash_skill_dir(meta.path),
                loaded_from=meta.path,
                body_md=(meta.path / "SKILL.md").read_text(encoding="utf-8"),
                scripts=[s.path for s in meta.scripts],
            )
        disabled_dir = self._root / DISABLED_DIR / name
        if disabled_dir.is_dir() and (disabled_dir / "SKILL.md").is_file():
            return SkillSnapshot(
                name=name,
                enabled=False,
                version_hash=_hash_skill_dir(disabled_dir),
                loaded_from=disabled_dir,
                body_md=(disabled_dir / "SKILL.md").read_text(encoding="utf-8"),
                scripts=sorted((disabled_dir / "scripts").glob("*.py"))
                if (disabled_dir / "scripts").is_dir()
                else [],
            )
        return None

    # ---- mutating ops ---------------------------------------------------

    async def install(self, payload: SkillInstallInput) -> SkillSnapshot:
        """Create a new skill from a JSON payload.

        Steps: validate → write to staging → atomic rename → reload one.
        """

        def _preflight() -> Path:
            target = self._root / payload.name
            if target.exists() and not payload.overwrite:
                raise SkillAdminError("conflict", f"skill {payload.name!r} already exists")
            if (self._root / DISABLED_DIR / payload.name).exists() and not payload.overwrite:
                raise SkillAdminError(
                    "conflict",
                    f"skill {payload.name!r} is disabled; enable it or pass overwrite=true",
                )
            return target

        target = await asyncio.to_thread(_preflight)
        return await self._stage_and_install(payload, target=target)

    async def update(self, name: str, payload: SkillInstallInput) -> SkillSnapshot:
        """Replace an installed skill's body + scripts.

        ``payload.name`` must equal ``name`` so renames stay explicit.
        """
        if payload.name != name:
            raise SkillAdminError(
                "validation",
                f"payload name {payload.name!r} differs from URL {name!r}",
            )

        def _preflight() -> Path:
            target = self._root / name
            if not target.exists():
                raise SkillAdminError("not_found", f"skill {name!r} is not installed")
            return target

        target = await asyncio.to_thread(_preflight)
        return await self._stage_and_install(
            payload.model_copy(update={"overwrite": True}), target=target
        )

    async def disable(self, name: str) -> SkillSnapshot:
        """Move ``skills/<name>`` → ``skills/_disabled/<name>`` and reload."""

        def _do() -> str:
            active = self._root / name
            if not active.is_dir():
                disabled_dir = self._root / DISABLED_DIR / name
                if disabled_dir.is_dir():
                    return "already_disabled"
                raise SkillAdminError("not_found", f"skill {name!r} not found")
            target = self._root / DISABLED_DIR / name
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            active.rename(target)
            return "disabled"

        outcome = await asyncio.to_thread(_do)
        if outcome == "disabled":
            await self._host.reload(name)
            log.info("skill.admin.disabled", name=name)
        snap = self.snapshot(name)
        if snap is None:  # pragma: no cover - we just wrote it
            raise SkillAdminError("internal", "disable rename succeeded but snapshot is empty")
        return snap

    async def enable(self, name: str) -> SkillSnapshot:
        """Move ``skills/_disabled/<name>`` → ``skills/<name>`` and reload."""

        def _do() -> None:
            source = self._root / DISABLED_DIR / name
            if not source.is_dir():
                raise SkillAdminError("not_found", f"disabled skill {name!r} not found")
            target = self._root / name
            if target.exists():
                raise SkillAdminError(
                    "conflict",
                    f"skill {name!r} already exists at active path; remove it first",
                )
            source.rename(target)

        await asyncio.to_thread(_do)
        await self._host.reload(name)
        log.info("skill.admin.enabled", name=name)
        snap = self.snapshot(name)
        if snap is None:  # pragma: no cover
            raise SkillAdminError("internal", "enable rename succeeded but snapshot is empty")
        return snap

    async def reload(self, name: str | None = None) -> int:
        """Force a fresh scan; returns the registry generation afterwards."""
        await self._host.reload(name)
        return self._host.generation

    async def dry_run(
        self,
        name: str,
        script: str,
        args: dict,
        *,
        timeout_s: int = 5,
    ) -> dict:
        """Run a script with a tight timeout and a sandboxed env.

        The executor's invocation history records ``status="dry_run"`` so
        UIs can distinguish exploratory calls from real workflow calls.
        """
        meta = self._host.get_skill(name)
        if meta is None:
            raise SkillAdminError("not_found", f"skill {name!r} is not enabled")
        chosen = next((s for s in meta.scripts if s.name == script), None)
        if chosen is None:
            raise SkillAdminError("not_found", f"script {script!r} not in skill {name!r}")
        result = await self._host.executor.run(
            script_path=chosen.path,
            args=args,
            tool_name=f"{name}__{script}",
            task_id=f"dry-run:{name}:{int(time.time() * 1000)}",
            timeout_s=timeout_s,
            uses_llm=False,  # dry-run never gets LLM credentials
            dry_run=True,
        )
        return {
            "ok": result.ok,
            "returncode": result.returncode,
            "duration_ms": result.duration_ms,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
        }

    # ---- P14.C: edge-only edits ----------------------------------------

    async def update_edges(
        self,
        name: str,
        *,
        add: list[EdgeOp] | None = None,
        remove: list[EdgeOp] | None = None,
    ) -> tuple[SkillSnapshot, EdgeUpdateReport]:
        """Mutate ONLY ``compatibility.{up,down}stream`` (and the legacy
        top-level ``downstream_skills`` for removes) in ``<name>/SKILL.md``.

        The full SKILL.md body is NEVER touched (we only re-emit the
        frontmatter), and scripts are untouched. This is the dedicated
        path for the graph view's drag-to-connect / right-click-delete
        edge editor — see PLAN §20.14 for the rationale (avoiding the
        body editor's parallel mutation path that would drift).

        Trade-offs vs ``update``:
        * Decorative ``# ...`` comments inside the YAML frontmatter
          block are NOT preserved (PyYAML round-trip drops them). The
          report's ``warnings`` field flags this when the original
          frontmatter contained inline comments so the UI can warn the
          user once and let them re-add comments after their session.
        * Adds always land in ``compatibility.{kind}`` (canonical form).
          Removes search both ``compatibility.*`` and the top-level
          ``downstream_skills`` legacy form so cleaning a node works
          regardless of which convention the original author used.
        """
        adds = add or []
        removes = remove or []
        if not adds and not removes:
            raise SkillAdminError(
                "validation", "update_edges requires at least one add or remove"
            )

        for op in adds + removes:
            if op.target == name:
                raise SkillAdminError(
                    "validation", f"skill {name!r} cannot reference itself"
                )
            if not ALLOWED_NAME_RE.match(op.target):
                raise SkillAdminError(
                    "validation",
                    f"target {op.target!r} is not a valid skill name",
                )

        # Find the skill on disk — active OR disabled. We allow editing
        # disabled skills' edges so a user can wire a graph up before
        # re-enabling, mirroring the body-editor's behaviour.
        skill_dir = self._resolve_active_dir(name)
        if skill_dir is None:
            disabled_dir = self._root / DISABLED_DIR / name
            if disabled_dir.is_dir() and (disabled_dir / "SKILL.md").is_file():
                skill_dir = disabled_dir
        if skill_dir is None:
            raise SkillAdminError("not_found", f"skill {name!r} is not installed")
        was_enabled = skill_dir != (self._root / DISABLED_DIR / name)

        skill_md = skill_dir / "SKILL.md"

        def _rewrite() -> tuple[str, EdgeUpdateReport]:
            original = skill_md.read_text(encoding="utf-8")
            new_body, report = _apply_edge_ops(original, adds=adds, removes=removes)
            return new_body, report

        new_body, report = await asyncio.to_thread(_rewrite)

        # Validate the resulting frontmatter — guards against an edit
        # that produces SKILL.md the loader will then reject and trigger
        # the rollback path needlessly.
        _validate_skill_md(new_body, expected_name=name)

        backup_holder: list[Path | None] = [None]

        def _commit() -> None:
            backup = skill_md.with_name(f"{skill_md.name}.bak-{int(time.time() * 1_000_000)}")
            shutil.copyfile(skill_md, backup)
            backup_holder[0] = backup
            tmp = skill_md.with_name(f"{skill_md.name}.tmp-{int(time.time() * 1_000_000)}")
            tmp.write_text(new_body, encoding="utf-8")
            tmp.replace(skill_md)  # atomic on POSIX

        await asyncio.to_thread(_commit)

        # Reload only the affected name. If reload fails, restore from
        # the backup so the registry stays coherent.
        if was_enabled:
            try:
                await self._host.reload(name)
            except Exception as exc:
                backup = backup_holder[0]

                def _rollback() -> None:
                    if backup is not None and backup.exists():
                        backup.replace(skill_md)

                await asyncio.to_thread(_rollback)
                raise SkillAdminError(
                    "internal", f"reload after edge edit failed; rolled back: {exc}"
                ) from exc

        # Cleanup backup.
        backup = backup_holder[0]

        def _cleanup() -> None:
            if backup is not None and backup.exists():
                backup.unlink(missing_ok=True)

        await asyncio.to_thread(_cleanup)

        log.info(
            "skill.admin.edges_updated",
            name=name,
            added=[(o.kind, o.target) for o in adds],
            removed=[(o.kind, o.target) for o in removes],
            warnings=report.warnings,
        )

        snap = self.snapshot(name)
        if snap is None:  # pragma: no cover - just wrote it
            raise SkillAdminError("internal", "edge edit succeeded but snapshot is empty")
        return snap, report

    # ---- internal staging pipeline -------------------------------------

    async def _stage_and_install(
        self,
        payload: SkillInstallInput,
        *,
        target: Path,
    ) -> SkillSnapshot:
        _validate_install(payload)

        # Phase 1: write staging dir + atomic rename into ``target`` —
        # all blocking I/O, executed off the event loop. We *do not*
        # call ``host.reload`` here because the loader needs the loop.
        backup_holder: list[Path | None] = [None]

        def _commit() -> None:
            (self._root / PENDING_DIR).mkdir(parents=True, exist_ok=True)
            staging = self._root / PENDING_DIR / (f"{payload.name}-{int(time.time() * 1_000_000)}")
            try:
                staging.mkdir(parents=True, exist_ok=False)
                (staging / "SKILL.md").write_text(payload.body_md, encoding="utf-8")
                scripts_dir = staging / "scripts"
                scripts_dir.mkdir(exist_ok=True)
                for script in payload.scripts:
                    (scripts_dir / f"{script.name}.py").write_text(script.content, encoding="utf-8")
                if target.exists():
                    backup = target.with_name(f"{target.name}.bak-{int(time.time() * 1_000_000)}")
                    target.rename(backup)
                    backup_holder[0] = backup
                staging.rename(target)
            except SkillAdminError:
                if staging.exists():
                    shutil.rmtree(staging)
                raise
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging)
                raise

        await asyncio.to_thread(_commit)

        # Phase 2: bump the registry; on failure, roll back to the backup.
        try:
            await self._host.reload(payload.name)
        except Exception as exc:
            backup = backup_holder[0]

            def _rollback() -> None:
                if target.exists():
                    shutil.rmtree(target)
                if backup is not None and backup.exists():
                    backup.rename(target)

            await asyncio.to_thread(_rollback)
            raise SkillAdminError("internal", f"reload failed; rolled back: {exc}") from exc

        # Phase 3: cleanup backup, log, return.
        backup = backup_holder[0]

        def _cleanup() -> None:
            if backup is not None and backup.exists():
                shutil.rmtree(backup)

        await asyncio.to_thread(_cleanup)
        log.info(
            "skill.admin.installed",
            name=payload.name,
            target=str(target),
            scripts=[s.name for s in payload.scripts],
        )
        snap = self.snapshot(payload.name)
        if snap is None:  # pragma: no cover - we just wrote it
            raise SkillAdminError("internal", "install succeeded but snapshot is empty")
        return snap

    # ---- helpers --------------------------------------------------------

    def _resolve_active_dir(self, name: str) -> Path | None:
        meta = self._host.get_skill(name)
        return meta.path if meta is not None else None


# ---------------------------------------------------------------------------
# Validators (pure, side-effect-free)
# ---------------------------------------------------------------------------


def _validate_install(payload: SkillInstallInput) -> None:
    if not ALLOWED_NAME_RE.match(payload.name):
        raise SkillAdminError(
            "validation",
            f"skill name {payload.name!r} must match {ALLOWED_NAME_RE.pattern}",
        )
    if len(payload.scripts) > MAX_SCRIPTS_PER_SKILL:
        raise SkillAdminError(
            "limit",
            f"too many scripts: {len(payload.scripts)} > {MAX_SCRIPTS_PER_SKILL}",
        )

    body_bytes = payload.body_md.encode("utf-8")
    if len(body_bytes) > MAX_BODY_BYTES:
        raise SkillAdminError("limit", "SKILL.md exceeds 256 KB limit")

    seen_scripts: set[str] = set()
    total_size = len(body_bytes)
    for script in payload.scripts:
        if not ALLOWED_NAME_RE.match(script.name):
            raise SkillAdminError(
                "validation",
                f"script name {script.name!r} must match {ALLOWED_NAME_RE.pattern}",
            )
        if script.name in seen_scripts:
            raise SkillAdminError("validation", f"duplicate script name {script.name!r}")
        seen_scripts.add(script.name)
        size = len(script.content.encode("utf-8"))
        if size > MAX_SCRIPT_BYTES:
            raise SkillAdminError(
                "limit",
                f"script {script.name!r} exceeds 64 KB limit",
            )
        total_size += size
        _validate_script_body(script.content, script_name=script.name)
    if total_size > MAX_TOTAL_BYTES:
        raise SkillAdminError("limit", "total skill payload exceeds 1 MB limit")

    _validate_skill_md(payload.body_md, expected_name=payload.name)


def _validate_skill_md(body: str, *, expected_name: str) -> None:
    """Ensure SKILL.md has frontmatter the loader will accept."""
    try:
        post = frontmatter.loads(body)
    except Exception as exc:  # pragma: no cover - python-frontmatter is permissive
        raise SkillAdminError("validation", f"SKILL.md frontmatter unparseable: {exc}") from exc
    meta = dict(post.metadata or {})
    if not meta:
        raise SkillAdminError(
            "validation",
            "SKILL.md must start with a YAML frontmatter block (--- … ---)",
        )
    name_in_md = str(meta.get("name") or "").strip()
    if name_in_md and name_in_md != expected_name:
        raise SkillAdminError(
            "validation",
            f"frontmatter name={name_in_md!r} does not match payload name {expected_name!r}",
        )
    description = str(meta.get("description") or "").strip()
    if not description:
        raise SkillAdminError("validation", "frontmatter `description` is required")
    triggers = meta.get("triggers")
    if triggers is None or (isinstance(triggers, list) and not triggers):
        raise SkillAdminError(
            "validation",
            "frontmatter `triggers` must be a non-empty list — the matcher needs them",
        )
    domain = str(meta.get("domain") or "").strip()
    if not domain:
        raise SkillAdminError("validation", "frontmatter `domain` is required")


# ---------------------------------------------------------------------------
# P14.C — pure helper: apply add/remove edge ops to a SKILL.md body
# ---------------------------------------------------------------------------


def _coerce_name_list(raw: object) -> list[str]:
    """Frontmatter accepts both ``downstream: foo`` (string) and
    ``downstream: [foo, bar]`` (list). Normalise to list[str], dropping
    blanks. Anything else (dict / int / None) ⇒ empty list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        v = raw.strip()
        return [v] if v else []
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            if isinstance(item, str):
                v = item.strip()
                if v:
                    out.append(v)
        return out
    return []


def _apply_edge_ops(
    body: str,
    *,
    adds: list[EdgeOp],
    removes: list[EdgeOp],
) -> tuple[str, EdgeUpdateReport]:
    """Pure transform: SKILL.md text + ops → new SKILL.md text + report.

    Pulled out as a free function so unit tests can pin the YAML
    surgery deterministically without the loader / FS dance. The
    SkillAdmin method is a thin async wrapper around this.

    Adds always land in ``compatibility.{kind}`` (canonical form).
    Removes search BOTH ``compatibility.*`` AND the legacy top-level
    ``downstream_skills`` so cleaning up dangling references works
    regardless of which convention the original author used.
    """
    try:
        post = frontmatter.loads(body)
    except Exception as exc:
        raise SkillAdminError(
            "validation", f"SKILL.md frontmatter unparseable: {exc}"
        ) from exc

    meta: dict = dict(post.metadata or {})
    if not meta:
        raise SkillAdminError(
            "validation",
            "SKILL.md must start with a YAML frontmatter block (--- … ---)",
        )

    compat_raw = meta.get("compatibility")
    compat: dict = dict(compat_raw) if isinstance(compat_raw, dict) else {}

    downs = _coerce_name_list(compat.get("downstream"))
    ups = _coerce_name_list(compat.get("upstream"))
    top_downs = _coerce_name_list(meta.get("downstream_skills"))

    report = EdgeUpdateReport()

    # ---- removes: search BOTH conventions ------------------------------
    for op in removes:
        target = op.target
        hit = False
        if op.kind == "downstream":
            if target in downs:
                downs = [d for d in downs if d != target]
                hit = True
            if target in top_downs:
                top_downs = [d for d in top_downs if d != target]
                hit = True
        else:  # upstream
            if target in ups:
                ups = [u for u in ups if u != target]
                hit = True
        if hit:
            report.removed.append((op.kind, target))
        else:
            report.skipped_missing.append((op.kind, target))

    # ---- adds: always canonical form -----------------------------------
    for op in adds:
        target = op.target
        if op.kind == "downstream":
            if target in downs:
                report.skipped_dup.append((op.kind, target))
                continue
            downs.append(target)
        else:
            if target in ups:
                report.skipped_dup.append((op.kind, target))
                continue
            ups.append(target)
        report.added.append((op.kind, target))

    # ---- write back into the metadata dict -----------------------------
    # Strategy: keep the metadata key order stable. We update existing
    # keys in place; we only insert ``compatibility`` if it wasn't there.
    # ``downs`` / ``ups`` are sorted on emit so the on-disk diff is
    # deterministic — important for reviews of UI-driven edits.
    new_compat: dict = {}
    if ups:
        new_compat["upstream"] = sorted(ups) if len(ups) > 1 else ups[0]
    if downs:
        new_compat["downstream"] = sorted(downs) if len(downs) > 1 else downs[0]
    if new_compat:
        meta["compatibility"] = new_compat
    elif "compatibility" in meta:
        # Drop the empty-after-edit key entirely so we don't leave
        # ``compatibility: {}`` cruft.
        del meta["compatibility"]

    if "downstream_skills" in meta:
        if top_downs:
            meta["downstream_skills"] = (
                sorted(top_downs) if len(top_downs) > 1 else top_downs[0]
            )
        else:
            del meta["downstream_skills"]

    # ---- detect comments-in-frontmatter to surface a UX warning --------
    # Cheap heuristic: parse the original frontmatter chunk (everything
    # between the first two ``---`` lines) and look for ``#`` lines that
    # aren't quoted. False positives are fine — we just nudge the user.
    if _frontmatter_has_inline_comments(body):
        report.warnings.append(
            "frontmatter inline comments are not preserved by edge edits; "
            "re-add them through the body editor if needed"
        )

    post.metadata = meta
    new_body = frontmatter.dumps(post, sort_keys=False)
    # ``frontmatter.dumps`` doesn't always end with a trailing newline;
    # the loader is forgiving but git/POSIX prefer one.
    if not new_body.endswith("\n"):
        new_body += "\n"
    return new_body, report


_FM_COMMENT_LINE_RE = re.compile(r"^\s*#")


def _frontmatter_has_inline_comments(body: str) -> bool:
    """Return True if the YAML frontmatter has at least one ``#`` comment
    line. Used only to set the ``warnings`` field — not as a hard error."""
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        if _FM_COMMENT_LINE_RE.match(line):
            return True
    return False


_PROHIBITED_RE = re.compile(r"(?:^|\W)(__import__|os\.system|subprocess\.Popen)\b")


def _validate_script_body(source: str, *, script_name: str) -> None:
    """Quick sanity sweep for script source.

    We are *not* trying to sandbox malicious code — the executor's
    subprocess + env whitelist + timeout do that. We simply reject the
    most obvious "I am a footgun" patterns so admin UI users don't ship
    a script that will brick their installation.
    """
    if not source.strip():
        raise SkillAdminError("validation", f"script {script_name!r} body is empty")
    if "\x00" in source:
        raise SkillAdminError(
            "validation",
            f"script {script_name!r} contains a NUL byte (binary upload?)",
        )
    if _PROHIBITED_RE.search(source):
        log.warning(
            "skill.admin.script_warning",
            script=script_name,
            reason="footgun_pattern",
        )
        # We log a warning but do *not* refuse — some skills legitimately
        # need subprocess. The loader's `aaf:network`/`aaf:timeout` magic
        # comments + the executor's process-group kill are the real
        # safety net.


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------


def _hash_skill_dir(skill_dir: Path) -> str:
    """Stable hash of SKILL.md + every script file, in sorted order.

    Good for "did this skill change since the UI last saw it?" without
    enumerating filesystem mtimes.
    """
    if not skill_dir.is_dir():
        return ""
    h = hashlib.sha256()
    files: list[Path] = []
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        files.append(skill_md)
    scripts = skill_dir / "scripts"
    if scripts.is_dir():
        files.extend(sorted(scripts.glob("*.py")))
    for path in files:
        h.update(path.name.encode("utf-8"))
        h.update(b"\x00")
        h.update(path.read_bytes())
        h.update(b"\xff")
    return f"sha256:{h.hexdigest()}"


# ---------------------------------------------------------------------------
# Convenience for routers
# ---------------------------------------------------------------------------


def admin_error_to_status(err: SkillAdminError) -> tuple[int, str]:
    """Map an admin error code to ``(http_status, detail)``."""
    mapping: dict[str, int] = {
        "validation": 400,
        "limit": 413,
        "conflict": 409,
        "not_found": 404,
    }
    return mapping.get(err.code, 500), str(err)


__all__ = [
    "MAX_BODY_BYTES",
    "MAX_SCRIPTS_PER_SKILL",
    "MAX_SCRIPT_BYTES",
    "MAX_TOTAL_BYTES",
    "SkillAdmin",
    "SkillAdminError",
    "SkillInstallInput",
    "SkillScriptInput",
    "SkillSnapshot",
    "admin_error_to_status",
]
