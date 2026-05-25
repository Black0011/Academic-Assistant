"""KnowledgeStore — paper cards, typed-links, rollback.

Two implementations:

* :class:`InMemoryKnowledgeStore` — dict-backed, for tests & dev.
* :class:`YamlKnowledgeStore`     — persists cards under
  ``<root>/<paper_id>.yaml`` with atomic tmp+rename writes (§11.9).

Both agree on the same protocol. ``find_related`` uses a keyword overlap
over ``PaperCard.search_text()``; swap in a vector-backed finder by
composing the YamlKnowledgeStore with a VectorStore at a later stage.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import structlog
import yaml

from backend.core.errors import MemoryNotFound

from .base import keyword_score
from .models import LinkType, PaperCard, SynthesisNote, TypedLink

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory impl
# ---------------------------------------------------------------------------


class InMemoryKnowledgeStore:
    def __init__(self) -> None:
        self._cards: dict[str, PaperCard] = {}
        self._synthesis: dict[str, SynthesisNote] = {}
        self._lock = asyncio.Lock()

    async def write_card(self, card: PaperCard) -> None:
        async with self._lock:
            existing = self._cards.get(card.paper_id)
            if existing is not None:
                # Preserve created_at, refresh updated_at, retain manual links.
                preserved_links = _merge_links(existing.typed_links, card.typed_links)
                merged_meta = _merge_card_metadata(existing, card)
                card = card.model_copy(
                    update={
                        "created_at": existing.created_at,
                        "updated_at": datetime.now(UTC),
                        "typed_links": preserved_links,
                        **merged_meta,
                    }
                )
            self._cards[card.paper_id] = card

    async def get(self, paper_id: str) -> PaperCard | None:
        return self._cards.get(paper_id)

    async def list_all(self) -> list[PaperCard]:
        return list(self._cards.values())

    async def find_related(self, query: str, *, k: int = 5) -> list[PaperCard]:
        if not self._cards:
            return []
        scored = [(c, keyword_score(query, c.search_text())) for c in self._cards.values()]
        scored.sort(key=lambda t: t[1], reverse=True)
        return [c for c, s in scored[: max(0, k)] if s > 0]

    async def link(
        self,
        a: str,
        b: str,
        link_type: str,
        *,
        evidence: str = "",
        bidirectional: bool = True,
    ) -> None:
        _validate_link_type(link_type)
        async with self._lock:
            await self._attach(a, b, link_type, evidence)
            if bidirectional:
                await self._attach(b, a, _inverse_link(link_type), evidence)

    async def delete(self, paper_id: str) -> bool:
        async with self._lock:
            present = paper_id in self._cards
            self._cards.pop(paper_id, None)
            # Scrub inbound links that pointed at the deleted card.
            for c in self._cards.values():
                if any(link.target_paper_id == paper_id for link in c.typed_links):
                    c.typed_links[:] = [
                        link for link in c.typed_links if link.target_paper_id != paper_id
                    ]
            return present

    async def rollback_run(self, run_id: str) -> int:
        async with self._lock:
            victims = [pid for pid, c in self._cards.items() if c.source_run_id == run_id]
            for pid in victims:
                self._cards.pop(pid)
            for c in self._cards.values():
                c.typed_links[:] = [
                    link for link in c.typed_links if link.target_paper_id not in victims
                ]
            return len(victims)

    # ---- synthesis --------------------------------------------------

    async def write_synthesis(self, note: SynthesisNote) -> None:
        async with self._lock:
            existing = self._synthesis.get(note.cluster_tag)
            if existing is not None and note.version <= existing.version:
                note = note.model_copy(update={"version": existing.version + 1})
            self._synthesis[note.cluster_tag] = note.model_copy(
                update={"updated_at": datetime.now(UTC)}
            )

    async def get_synthesis(self, cluster_tag: str) -> SynthesisNote | None:
        return self._synthesis.get(cluster_tag)

    async def list_synthesis(self) -> list[SynthesisNote]:
        return list(self._synthesis.values())

    async def delete_synthesis(self, cluster_tag: str) -> bool:
        async with self._lock:
            return self._synthesis.pop(cluster_tag, None) is not None

    # ---- internals --------------------------------------------------

    async def _attach(self, paper_id: str, target: str, link_type: str, evidence: str) -> None:
        card = self._cards.get(paper_id)
        if card is None:
            raise MemoryNotFound(f"paper not found: {paper_id}", store="knowledge", id=paper_id)
        # Dedup on (target, type).
        for existing in card.typed_links:
            if existing.target_paper_id == target and existing.link_type == link_type:
                return
        card.typed_links.append(
            TypedLink(
                target_paper_id=target,
                link_type=cast(LinkType, link_type),
                evidence=evidence,
            )
        )
        card.updated_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# YAML-backed impl (atomic tmp + rename)
# ---------------------------------------------------------------------------


class YamlKnowledgeStore:
    """Persists cards as ``<root>/<paper_id>.yaml``. Safe for single-process use."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._synthesis_dir = self._root / "_synthesis"
        self._lock = asyncio.Lock()

    # ---- writes -----------------------------------------------------

    async def write_card(self, card: PaperCard) -> None:
        async with self._lock:
            existing = await asyncio.to_thread(self._read_one, card.paper_id)
            if existing is not None:
                merged_meta = _merge_card_metadata(existing, card)
                merged = card.model_copy(
                    update={
                        "created_at": existing.created_at,
                        "updated_at": datetime.now(UTC),
                        "typed_links": _merge_links(existing.typed_links, card.typed_links),
                        **merged_meta,
                    }
                )
            else:
                merged = card
            await asyncio.to_thread(self._write_atomic, merged)

    async def link(
        self,
        a: str,
        b: str,
        link_type: str,
        *,
        evidence: str = "",
        bidirectional: bool = True,
    ) -> None:
        _validate_link_type(link_type)
        async with self._lock:
            await asyncio.to_thread(self._append_link, a, b, link_type, evidence)
            if bidirectional:
                await asyncio.to_thread(self._append_link, b, a, _inverse_link(link_type), evidence)

    async def delete(self, paper_id: str) -> bool:
        async with self._lock:
            path = self._path_for(paper_id)
            if not path.exists():
                return False
            await asyncio.to_thread(path.unlink)
            await asyncio.to_thread(self._scrub_inbound_links, paper_id)
            return True

    async def rollback_run(self, run_id: str) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._rollback_sync, run_id)

    # ---- reads ------------------------------------------------------

    async def get(self, paper_id: str) -> PaperCard | None:
        return await asyncio.to_thread(self._read_one, paper_id)

    async def list_all(self) -> list[PaperCard]:
        return await asyncio.to_thread(self._list_sync)

    async def find_related(self, query: str, *, k: int = 5) -> list[PaperCard]:
        cards = await self.list_all()
        scored = [(c, keyword_score(query, c.search_text())) for c in cards]
        scored.sort(key=lambda t: t[1], reverse=True)
        return [c for c, s in scored[: max(0, k)] if s > 0]

    # ---- synthesis --------------------------------------------------

    async def write_synthesis(self, note: SynthesisNote) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write_synthesis_sync, note)

    async def get_synthesis(self, cluster_tag: str) -> SynthesisNote | None:
        return await asyncio.to_thread(self._read_synthesis_sync, cluster_tag)

    async def list_synthesis(self) -> list[SynthesisNote]:
        return await asyncio.to_thread(self._list_synthesis_sync)

    async def delete_synthesis(self, cluster_tag: str) -> bool:
        async with self._lock:
            path = self._synthesis_path(cluster_tag)
            if not path.exists():
                return False
            await asyncio.to_thread(path.unlink)
            return True

    # ---- synchronous helpers (executed in a thread) -----------------

    def _path_for(self, paper_id: str) -> Path:
        return self._root / f"{paper_id}.yaml"

    def _read_one(self, paper_id: str) -> PaperCard | None:
        path = self._path_for(paper_id)
        if not path.exists():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return PaperCard.model_validate(data)
        except Exception as exc:
            log.warning("memory.knowledge.bad_yaml", path=str(path), err=str(exc))
            return None

    def _write_atomic(self, card: PaperCard) -> None:
        _atomic_write_yaml(self._path_for(card.paper_id), card.model_dump(mode="json"))

    def _list_sync(self) -> list[PaperCard]:
        if not self._root.exists():
            return []
        out: list[PaperCard] = []
        for p in sorted(self._root.glob("*.yaml")):
            card = self._read_one(p.stem)
            if card is not None:
                out.append(card)
        return out

    def _append_link(self, paper_id: str, target: str, link_type: str, evidence: str) -> None:
        card = self._read_one(paper_id)
        if card is None:
            raise MemoryNotFound(f"paper not found: {paper_id}", store="knowledge", id=paper_id)
        for existing in card.typed_links:
            if existing.target_paper_id == target and existing.link_type == link_type:
                return
        card.typed_links.append(
            TypedLink(
                target_paper_id=target,
                link_type=cast(LinkType, link_type),
                evidence=evidence,
            )
        )
        card.updated_at = datetime.now(UTC)
        self._write_atomic(card)

    def _scrub_inbound_links(self, paper_id: str) -> None:
        for p in list(self._root.glob("*.yaml")):
            card = self._read_one(p.stem)
            if card is None:
                continue
            before = len(card.typed_links)
            card.typed_links[:] = [
                link for link in card.typed_links if link.target_paper_id != paper_id
            ]
            if len(card.typed_links) != before:
                card.updated_at = datetime.now(UTC)
                self._write_atomic(card)

    def _synthesis_path(self, cluster_tag: str) -> Path:
        # Tag may contain spaces / slashes — slugify minimally.
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in cluster_tag)
        return self._synthesis_dir / f"{safe}.yaml"

    def _write_synthesis_sync(self, note: SynthesisNote) -> None:
        self._synthesis_dir.mkdir(parents=True, exist_ok=True)
        existing = self._read_synthesis_sync(note.cluster_tag)
        if existing is not None and note.version <= existing.version:
            note = note.model_copy(update={"version": existing.version + 1})
        note = note.model_copy(update={"updated_at": datetime.now(UTC)})
        _atomic_write_yaml(self._synthesis_path(note.cluster_tag), note.model_dump(mode="json"))

    def _read_synthesis_sync(self, cluster_tag: str) -> SynthesisNote | None:
        path = self._synthesis_path(cluster_tag)
        if not path.exists():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return SynthesisNote.model_validate(data)
        except Exception as exc:
            log.warning("memory.knowledge.bad_synthesis_yaml", path=str(path), err=str(exc))
            return None

    def _list_synthesis_sync(self) -> list[SynthesisNote]:
        if not self._synthesis_dir.exists():
            return []
        out: list[SynthesisNote] = []
        for p in sorted(self._synthesis_dir.glob("*.yaml")):
            s = self._read_synthesis_sync(p.stem)
            if s is not None:
                out.append(s)
        return out

    def _rollback_sync(self, run_id: str) -> int:
        victims: list[str] = []
        for p in list(self._root.glob("*.yaml")):
            card = self._read_one(p.stem)
            if card is None:
                continue
            if card.source_run_id == run_id:
                p.unlink(missing_ok=True)
                victims.append(card.paper_id)
        for v in victims:
            self._scrub_inbound_links(v)
        return len(victims)


# ---------------------------------------------------------------------------
# Free-standing helpers
# ---------------------------------------------------------------------------


def _atomic_write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".aaf-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


_VALID_LINK_TYPES = {"extends", "contradicts", "applies", "motivated_by", "baseline_of"}
_LINK_INVERSES = {
    "extends": "motivated_by",
    "motivated_by": "extends",
    "baseline_of": "applies",
    "applies": "baseline_of",
    "contradicts": "contradicts",  # symmetric
}


def _validate_link_type(link_type: str) -> None:
    if link_type not in _VALID_LINK_TYPES:
        from backend.core.errors import ValidationError

        raise ValidationError(f"unknown link_type: {link_type}", link_type=link_type)


def _inverse_link(link_type: str) -> str:
    return _LINK_INVERSES.get(link_type, link_type)


def _merge_links(old: list[TypedLink], new: list[TypedLink]) -> list[TypedLink]:
    seen: set[tuple[str, str]] = set()
    merged: list[TypedLink] = []
    for link in [*old, *new]:
        key = (link.target_paper_id, link.link_type)
        if key in seen:
            continue
        seen.add(key)
        merged.append(link)
    return merged


def _merge_card_metadata(existing: PaperCard, incoming: PaperCard) -> dict[str, str | None]:
    fields = [
        "url",
        "field_major",
        "field_minor",
        "citation_url",
        "citation_bibtex",
        "experiment_results",
    ]
    merged: dict[str, str | None] = {}
    for name in fields:
        new_val = getattr(incoming, name)
        if new_val is None or (isinstance(new_val, str) and not new_val.strip()):
            merged[name] = getattr(existing, name)
    return merged


__all__ = ["InMemoryKnowledgeStore", "YamlKnowledgeStore"]
