"""HeuristicStore (L3) — in-memory + YAML backends.

Layout on disk (PLAN §11.3 / §23.3)::

    data/skills/
      ├─ research/
      │   ├─ _index.yaml          # { skills: { <id>: {name, trigger_pattern, success_count, updated_at} } }
      │   ├─ skill_<id>.yaml      # full Heuristic
      │   └─ ...
      ├─ writing/...
      ├─ revision/...
      ├─ rebuttal/...
      └─ survey/...

Matching uses the L2 keyword overlap (``trigger_pattern`` splits on commas)
with an optional embedder for semantic boost — the same philosophy as the
L1 skill matcher to keep behaviour predictable.

``frozen`` skills are hidden from :meth:`match` but retained on disk so
users can un-freeze them via the API.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml

from backend.core.errors import MemoryNotFound

from .base import keyword_score
from .models import Heuristic

log = structlog.get_logger(__name__)


_MIN_SCORE = 0.05


# ---------------------------------------------------------------------------
# In-memory
# ---------------------------------------------------------------------------


class InMemoryHeuristicStore:
    def __init__(self) -> None:
        self._items: dict[str, Heuristic] = {}
        self._lock = asyncio.Lock()

    async def add(self, skill: Heuristic) -> None:
        async with self._lock:
            self._items[skill.id] = skill

    async def get(self, id_: str) -> Heuristic | None:
        return self._items.get(id_)

    async def list_by_domain(self, domain: str) -> list[Heuristic]:
        return [s for s in self._items.values() if s.domain == domain]

    async def match(
        self, query: str, *, domain: str | None = None, top_k: int = 3
    ) -> list[Heuristic]:
        pool = [s for s in self._items.values() if not s.frozen]
        if domain:
            pool = [s for s in pool if s.domain == domain]
        return _rank_heuristics(query, pool, top_k)

    async def bump_success(self, id_: str) -> None:
        await self._bump(id_, success=1)

    async def bump_failure(self, id_: str) -> None:
        await self._bump(id_, failure=1)

    async def freeze(self, id_: str) -> None:
        async with self._lock:
            s = self._items.get(id_)
            if s is None:
                raise MemoryNotFound(f"heuristic not found: {id_}", store="heuristic", id=id_)
            self._items[id_] = s.model_copy(
                update={"frozen": True, "updated_at": datetime.now(UTC)}
            )

    async def delete(self, id_: str) -> bool:
        async with self._lock:
            return self._items.pop(id_, None) is not None

    async def rollback_run(self, run_id: str) -> int:
        async with self._lock:
            victims = [i for i, s in self._items.items() if s.source_run_id == run_id]
            for i in victims:
                self._items.pop(i)
            return len(victims)

    async def _bump(self, id_: str, *, success: int = 0, failure: int = 0) -> None:
        async with self._lock:
            s = self._items.get(id_)
            if s is None:
                raise MemoryNotFound(f"heuristic not found: {id_}", store="heuristic", id=id_)
            self._items[id_] = s.model_copy(
                update={
                    "success_count": s.success_count + success,
                    "failure_count": s.failure_count + failure,
                    "updated_at": datetime.now(UTC),
                }
            )


# ---------------------------------------------------------------------------
# YAML-backed
# ---------------------------------------------------------------------------


class YamlHeuristicStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    # ---- CRUD -------------------------------------------------------

    async def add(self, skill: Heuristic) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write_sync, skill)

    async def get(self, id_: str) -> Heuristic | None:
        return await asyncio.to_thread(self._get_sync, id_)

    async def list_by_domain(self, domain: str) -> list[Heuristic]:
        return await asyncio.to_thread(self._list_domain_sync, domain)

    async def match(
        self, query: str, *, domain: str | None = None, top_k: int = 3
    ) -> list[Heuristic]:
        items = await asyncio.to_thread(self._list_all_sync)
        pool = [s for s in items if not s.frozen]
        if domain:
            pool = [s for s in pool if s.domain == domain]
        return _rank_heuristics(query, pool, top_k)

    async def bump_success(self, id_: str) -> None:
        await self._mutate(id_, {"success_count": 1})

    async def bump_failure(self, id_: str) -> None:
        await self._mutate(id_, {"failure_count": 1})

    async def freeze(self, id_: str) -> None:
        await self._mutate(id_, {"frozen": True})

    async def delete(self, id_: str) -> bool:
        async with self._lock:
            return await asyncio.to_thread(self._delete_sync, id_)

    async def rollback_run(self, run_id: str) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._rollback_sync, run_id)

    # ---- sync helpers (thread-pool) ---------------------------------

    def _domain_dir(self, domain: str) -> Path:
        return self._root / domain

    def _skill_path(self, domain: str, id_: str) -> Path:
        return self._domain_dir(domain) / f"skill_{id_}.yaml"

    def _index_path(self, domain: str) -> Path:
        return self._domain_dir(domain) / "_index.yaml"

    def _write_sync(self, skill: Heuristic) -> None:
        dom = self._domain_dir(skill.domain)
        dom.mkdir(parents=True, exist_ok=True)
        _atomic_yaml_write(self._skill_path(skill.domain, skill.id), skill.model_dump(mode="json"))
        self._refresh_index(skill.domain)

    def _get_sync(self, id_: str) -> Heuristic | None:
        if not self._root.exists():
            return None
        for dom_dir in self._root.iterdir():
            if not dom_dir.is_dir():
                continue
            path = dom_dir / f"skill_{id_}.yaml"
            if path.exists():
                return _load_skill(path)
        return None

    def _list_domain_sync(self, domain: str) -> list[Heuristic]:
        dom = self._domain_dir(domain)
        if not dom.is_dir():
            return []
        out: list[Heuristic] = []
        for p in sorted(dom.glob("skill_*.yaml")):
            s = _load_skill(p)
            if s is not None:
                out.append(s)
        return out

    def _list_all_sync(self) -> list[Heuristic]:
        if not self._root.exists():
            return []
        out: list[Heuristic] = []
        for dom_dir in sorted(self._root.iterdir()):
            if not dom_dir.is_dir():
                continue
            for p in sorted(dom_dir.glob("skill_*.yaml")):
                s = _load_skill(p)
                if s is not None:
                    out.append(s)
        return out

    def _delete_sync(self, id_: str) -> bool:
        current = self._get_sync(id_)
        if current is None:
            return False
        path = self._skill_path(current.domain, id_)
        path.unlink(missing_ok=True)
        self._refresh_index(current.domain)
        return True

    def _rollback_sync(self, run_id: str) -> int:
        victims: list[Heuristic] = [s for s in self._list_all_sync() if s.source_run_id == run_id]
        for v in victims:
            self._skill_path(v.domain, v.id).unlink(missing_ok=True)
        for dom in {v.domain for v in victims}:
            self._refresh_index(dom)
        return len(victims)

    def _refresh_index(self, domain: str) -> None:
        dom = self._domain_dir(domain)
        if not dom.is_dir():
            return
        index: dict[str, dict[str, Any]] = {}
        for p in sorted(dom.glob("skill_*.yaml")):
            s = _load_skill(p)
            if s is None:
                continue
            index[s.id] = {
                "name": s.name,
                "trigger_pattern": s.trigger_pattern,
                "success_count": s.success_count,
                "failure_count": s.failure_count,
                "frozen": s.frozen,
                "updated_at": s.updated_at.isoformat(),
            }
        _atomic_yaml_write(self._index_path(domain), {"skills": index})

    async def _mutate(self, id_: str, inc: dict[str, Any]) -> None:
        async with self._lock:

            def _work() -> None:
                s = self._get_sync(id_)
                if s is None:
                    raise MemoryNotFound(f"heuristic not found: {id_}", store="heuristic", id=id_)
                updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
                if "success_count" in inc:
                    updates["success_count"] = s.success_count + inc["success_count"]
                if "failure_count" in inc:
                    updates["failure_count"] = s.failure_count + inc["failure_count"]
                if "frozen" in inc:
                    updates["frozen"] = bool(inc["frozen"])
                updated = s.model_copy(update=updates)
                self._write_sync(updated)

            await asyncio.to_thread(_work)


# ---------------------------------------------------------------------------
# Free helpers
# ---------------------------------------------------------------------------


def _rank_heuristics(query: str, pool: list[Heuristic], top_k: int) -> list[Heuristic]:
    scored: list[tuple[Heuristic, float]] = []
    for s in pool:
        trig_tokens = ", ".join(s.trigger_pattern.split(","))
        text = f"{s.name} {trig_tokens} {s.description}"
        score = keyword_score(query, text)
        if score >= _MIN_SCORE:
            scored.append((s, score))
    scored.sort(key=lambda t: t[1], reverse=True)
    return [s for s, _ in scored[:top_k]]


def _atomic_yaml_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".aaf-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _load_skill(path: Path) -> Heuristic | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("domain", path.parent.name)
        return Heuristic.model_validate(data)
    except Exception as exc:
        log.warning("memory.heuristic.bad_yaml", path=str(path), err=str(exc))
        return None


__all__ = ["InMemoryHeuristicStore", "YamlHeuristicStore"]
