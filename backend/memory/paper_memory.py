"""A-Mem evolution engine — framework-native port.

Migrates the core of ``Academic-Agent/memory/paper_memory.py`` into the new
framework with a **clean dependency boundary**: the evolver only talks to
:class:`MemoryBundle` and :class:`LLMProvider`. No direct filesystem
access, no Chroma client, no tools.paper_reader coupling.

Three public entry points (PLAN §11.7):

* :meth:`PaperMemoryEvolver.evolve_new_paper` — called right after a new
  :class:`PaperCard` is written. Looks up k neighbours via the
  vector store, asks the LLM to infer typed-links and tag updates, and
  writes them back through :class:`KnowledgeStore.link` and
  :meth:`KnowledgeStore.write_card`.
* :meth:`PaperMemoryEvolver.check_synthesis_trigger` — when a ``tag``
  has accumulated enough cards, synthesise a cluster-level note.
* :meth:`PaperMemoryEvolver.write_session_reflection` — builds a short
  reflection from a finished workflow and appends it to the episodic
  store.

All three degrade gracefully: if no ``LLMProvider`` is wired, a pure
heuristic path keeps typed-links honest (tag overlap → ``applies``) and
synthesis/reflection fall back to structured templates.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from .base import MemoryBundle, gen_id
from .models import (
    LinkType,
    PaperCard,
    Reflection,
    SynthesisNote,
    TypedLink,
)

if TYPE_CHECKING:
    from backend.core.llm.base import LLMProvider

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass
class EvolutionResult:
    """Summary of one :meth:`PaperMemoryEvolver.evolve_new_paper` call."""

    paper_id: str
    mode: str  # "llm" | "heuristic" | "skip"
    typed_links_added: list[TypedLink] = field(default_factory=list)
    tags_added: list[str] = field(default_factory=list)
    neighbors_considered: int = 0
    reason: str = ""


# ---------------------------------------------------------------------------
# Vocabulary mapping
# ---------------------------------------------------------------------------


# Old A-Mem vocabulary → new TypedLink vocabulary (PLAN §11.7).
# Accept both spellings on input; always emit the canonical form.
_LINK_VOCAB: dict[str, LinkType] = {
    "extends": "extends",
    "contradicts": "contradicts",
    "applies": "applies",
    "motivates": "motivated_by",
    "motivated_by": "motivated_by",
    "benchmarks": "baseline_of",
    "baseline_of": "baseline_of",
    "baselines": "baseline_of",
}


def _canonical_link_type(raw: str | None) -> LinkType | None:
    if not raw:
        return None
    return _LINK_VOCAB.get(raw.strip().lower())


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json(text: str) -> dict | list | None:
    """Best-effort JSON extractor tolerant of markdown fences and prose."""
    if not text:
        return None
    candidate = text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    m = _JSON_FENCE_RE.search(candidate)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Fallback: scan for the first { … } balanced block.
    start = candidate.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(candidate[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


async def _collect_completion(
    llm: LLMProvider,
    messages: list,
    *,
    model: str | None = None,
    temperature: float = 0.1,
) -> str:
    """Drain a streaming completion into a plain string.

    Raises on error chunks so callers can decide whether to fall back.
    """
    from backend.core.errors import LLMAPIError

    stream = await llm.complete(messages, model=model, temperature=temperature, stream=True)
    parts: list[str] = []
    async for chunk in stream:
        if chunk.type == "delta" and chunk.delta:
            parts.append(chunk.delta)
        elif chunk.type == "error":
            raise LLMAPIError(chunk.error or "llm error")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Evolver
# ---------------------------------------------------------------------------


_DEFAULT_EVOLVE_SYSTEM = (
    "You are an academic knowledge-graph evolution agent. "
    "Decide how a newly ingested paper relates to its neighbours. "
    "Respond with STRICT JSON only — no markdown fences, no prose."
)


class PaperMemoryEvolver:
    """Framework-native A-Mem evolver.

    Parameters
    ----------
    bundle: :class:`MemoryBundle` — read/write all memory through this.
    llm:    optional LLM; when absent the evolver uses the heuristic path.
    neighbors_k: how many similar papers to consider for typed-link
        inference.
    synthesis_threshold: minimum papers per cluster before a synthesis
        note is generated.
    model: optional model override forwarded to the LLM.
    """

    def __init__(
        self,
        bundle: MemoryBundle,
        *,
        llm: LLMProvider | None = None,
        neighbors_k: int = 5,
        synthesis_threshold: int = 5,
        model: str | None = None,
    ) -> None:
        self.bundle = bundle
        self.llm = llm
        self.neighbors_k = max(0, neighbors_k)
        self.synthesis_threshold = max(1, synthesis_threshold)
        self.model = model

    # ---------------- evolve_new_paper ------------------------------

    async def evolve_new_paper(
        self, card: PaperCard, *, run_id: str | None = None
    ) -> EvolutionResult:
        if self.neighbors_k == 0:
            return EvolutionResult(
                paper_id=card.paper_id,
                mode="skip",
                reason="neighbors_k=0",
            )

        # Over-fetch a little so we can drop the card itself.
        hits = await self.bundle.vector.query(card.search_text(), k=self.neighbors_k + 1)
        neighbours: list[PaperCard] = []
        for h in hits:
            if h.doc_id == card.paper_id:
                continue
            neighbour = await self.bundle.knowledge.get(h.doc_id)
            if neighbour is not None:
                neighbours.append(neighbour)
            if len(neighbours) >= self.neighbors_k:
                break

        if not neighbours:
            return EvolutionResult(
                paper_id=card.paper_id,
                mode="skip",
                reason="no_neighbours",
            )

        decision: dict
        mode: str
        if self.llm is not None:
            try:
                decision = await self._call_llm_evolution(card, neighbours)
                mode = "llm"
            except Exception as exc:
                log.warning("memory.evolver.llm_failed", err=str(exc))
                decision = _heuristic_evolution(card, neighbours)
                mode = "heuristic"
        else:
            decision = _heuristic_evolution(card, neighbours)
            mode = "heuristic"

        return await self._apply_decision(
            card=card,
            neighbours=neighbours,
            decision=decision,
            mode=mode,
        )

    async def _apply_decision(
        self,
        *,
        card: PaperCard,
        neighbours: list[PaperCard],
        decision: dict,
        mode: str,
    ) -> EvolutionResult:
        added_links: list[TypedLink] = []
        added_tags: list[str] = []

        for entry in decision.get("typed_connections", []) or []:
            target_id = entry.get("paper_id") if isinstance(entry, dict) else None
            if not target_id:
                continue
            if target_id == card.paper_id:
                continue
            if not any(n.paper_id == target_id for n in neighbours):
                # Refuse to link to papers outside the neighbour set.
                continue
            link_type = _canonical_link_type(
                entry.get("relation_type") if isinstance(entry, dict) else None
            )
            if link_type is None:
                continue
            evidence = (
                (entry.get("note") or entry.get("evidence") or "").strip()
                if isinstance(entry, dict)
                else ""
            )
            try:
                await self.bundle.knowledge.link(
                    card.paper_id, target_id, link_type, evidence=evidence, bidirectional=True
                )
            except Exception as exc:
                log.warning("memory.evolver.link_failed", err=str(exc))
                continue
            added_links.append(
                TypedLink(target_paper_id=target_id, link_type=link_type, evidence=evidence)
            )

        # Tag updates — additive only; we never drop user-authored tags.
        new_tags = [t for t in (decision.get("tags_to_update") or []) if t and t not in card.tags]
        if new_tags:
            merged = list(card.tags) + new_tags
            refreshed = card.model_copy(update={"tags": merged})
            await self.bundle.knowledge.write_card(refreshed)
            added_tags = new_tags

        return EvolutionResult(
            paper_id=card.paper_id,
            mode=mode,
            typed_links_added=added_links,
            tags_added=added_tags,
            neighbors_considered=len(neighbours),
        )

    # ---------------- synthesis -------------------------------------

    async def check_synthesis_trigger(
        self, tag: str, *, run_id: str | None = None, force: bool = False
    ) -> SynthesisNote | None:
        if not tag:
            return None
        all_cards = await self.bundle.knowledge.list_all()
        tagged = [c for c in all_cards if tag in c.tags]
        if len(tagged) < self.synthesis_threshold:
            return None

        existing = await self.bundle.knowledge.get_synthesis(tag)
        if existing is not None and not force:
            existing_ids = set(existing.paper_ids)
            current_ids = {c.paper_id for c in tagged}
            if existing_ids == current_ids:
                return existing
        note = await self._generate_synthesis(tag, tagged, run_id=run_id, existing=existing)
        await self.bundle.knowledge.write_synthesis(note)
        return note

    async def _generate_synthesis(
        self,
        tag: str,
        cards: list[PaperCard],
        *,
        run_id: str | None,
        existing: SynthesisNote | None,
    ) -> SynthesisNote:
        paper_ids = sorted(c.paper_id for c in cards)
        next_version = (existing.version + 1) if existing is not None else 1
        summary = f"{len(cards)} papers in cluster `{tag}`"
        content = _template_synthesis(tag, cards)

        if self.llm is not None:
            try:
                content = await self._call_llm_synthesis(tag, cards)
            except Exception as exc:
                log.warning("memory.evolver.synthesis_llm_failed", err=str(exc))
        return SynthesisNote(
            cluster_tag=tag,
            version=next_version,
            paper_ids=paper_ids,
            content=content,
            summary=summary,
            source_run_id=run_id,
        )

    # ---------------- session reflection ----------------------------

    async def write_session_reflection(
        self,
        *,
        task_id: str,
        query: str,
        outcomes: dict,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> Reflection:
        content = _template_reflection(query=query, outcomes=outcomes)
        if self.llm is not None:
            try:
                content = await self._call_llm_reflection(query, outcomes)
            except Exception as exc:
                log.warning("memory.evolver.reflection_llm_failed", err=str(exc))

        reflection = Reflection(
            id=gen_id("r_"),
            type="reflection",
            content=content,
            session_id=session_id,
            user_id=user_id,
            source_run_id=task_id,
        )
        await self.bundle.episodic.append(reflection)
        return reflection

    # ---------------- LLM calls (private) ---------------------------

    async def _call_llm_evolution(self, card: PaperCard, neighbours: list[PaperCard]) -> dict:
        from backend.core.llm.base import ChatMessage

        assert self.llm is not None
        user_prompt = _build_evolution_prompt(card, neighbours)
        messages = [
            ChatMessage(role="system", content=_DEFAULT_EVOLVE_SYSTEM),
            ChatMessage(role="user", content=user_prompt),
        ]
        raw = await _collect_completion(self.llm, messages, model=self.model)
        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            raise ValueError("LLM did not return a JSON object")
        return parsed

    async def _call_llm_synthesis(self, tag: str, cards: list[PaperCard]) -> str:
        from backend.core.llm.base import ChatMessage

        assert self.llm is not None
        user_prompt = _build_synthesis_prompt(tag, cards)
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are a research synthesis writer. Produce a concise, "
                    "well-structured markdown synthesis note. No fences."
                ),
            ),
            ChatMessage(role="user", content=user_prompt),
        ]
        return (await _collect_completion(self.llm, messages, model=self.model)).strip()

    async def _call_llm_reflection(self, query: str, outcomes: dict) -> str:
        from backend.core.llm.base import ChatMessage

        assert self.llm is not None
        user_prompt = _build_reflection_prompt(query, outcomes)
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are a reflective research agent. Summarise what was "
                    "learnt in 2-4 short sentences. No fences."
                ),
            ),
            ChatMessage(role="user", content=user_prompt),
        ]
        return (await _collect_completion(self.llm, messages, model=self.model)).strip()


# ---------------------------------------------------------------------------
# Heuristic + prompt + template helpers (free functions for testability)
# ---------------------------------------------------------------------------


def _heuristic_evolution(card: PaperCard, neighbours: list[PaperCard]) -> dict:
    """Tag / keyword overlap → conservative ``applies`` links.

    Port of the legacy ``_heuristic_evolution`` — ensures the knowledge
    graph still gains some structure when no LLM is available.
    """
    if not neighbours:
        return {"typed_connections": [], "tags_to_update": []}

    own_tags = {t.lower() for t in card.tags}
    own_title_tokens = _tokenize(card.title + " " + card.summary)

    scored: list[tuple[float, PaperCard]] = []
    for nb in neighbours:
        nb_tags = {t.lower() for t in nb.tags}
        nb_tokens = _tokenize(nb.title + " " + nb.summary)
        tag_overlap = len(own_tags & nb_tags)
        token_overlap = len(own_title_tokens & nb_tokens)
        if tag_overlap == 0 and token_overlap == 0:
            continue
        confidence = min(0.6, tag_overlap * 0.3 + token_overlap * 0.08)
        scored.append((confidence, nb))
    if not scored:
        return {"typed_connections": [], "tags_to_update": []}

    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[:3]
    typed = [
        {
            "paper_id": nb.paper_id,
            "relation_type": "applies",
            "confidence": round(conf, 2),
            "note": "heuristic: tag/title overlap",
        }
        for conf, nb in top
    ]
    return {"typed_connections": typed, "tags_to_update": []}


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z\u4e00-\u9fa5]{3,}", text or "")}


def _build_evolution_prompt(card: PaperCard, neighbours: list[PaperCard]) -> str:
    neighbour_lines = "\n".join(
        f"- paper_id={nb.paper_id} title={nb.title!r} tags={nb.tags}" for nb in neighbours
    )
    return (
        f"New paper:\n"
        f"  paper_id: {card.paper_id}\n"
        f"  title: {card.title}\n"
        f"  tags: {card.tags}\n"
        f"  summary: {card.summary[:400]}\n\n"
        f"Neighbours (count={len(neighbours)}):\n{neighbour_lines}\n\n"
        "Decide typed connections between the new paper and its neighbours.\n"
        "Allowed relation_type values: extends | contradicts | applies | "
        "motivated_by | baseline_of.\n"
        "Only link to papers listed above. Confidence is in [0.0, 1.0].\n\n"
        "Respond with STRICT JSON of shape:\n"
        "{\n"
        '  "typed_connections": [\n'
        '    {"paper_id": "...", "relation_type": "extends", '
        '"confidence": 0.8, "note": "..."}\n'
        "  ],\n"
        '  "tags_to_update": ["new_tag"]\n'
        "}"
    )


def _build_synthesis_prompt(tag: str, cards: list[PaperCard]) -> str:
    lines = "\n".join(f"- {c.paper_id}: {c.title} — {c.summary[:300]}" for c in cards)
    return (
        f"Cluster tag: `{tag}` ({len(cards)} papers)\n\n"
        f"Papers:\n{lines}\n\n"
        "Write a 200-400 word markdown synthesis covering: shared problem, "
        "distinctive methods, consistent findings, open questions."
    )


def _build_reflection_prompt(query: str, outcomes: dict) -> str:
    return (
        f"Workflow query: {query}\n"
        f"Outcomes: {json.dumps(outcomes, ensure_ascii=False)[:1000]}\n\n"
        "Write 2-4 short sentences capturing what was learnt, what worked, "
        "and what did not."
    )


def _template_synthesis(tag: str, cards: list[PaperCard]) -> str:
    lines = [f"# Synthesis: {tag}", "", f"_{len(cards)} papers in cluster._", ""]
    for c in cards:
        authors = ", ".join(c.authors[:3]) or "anon"
        year = str(c.year) if c.year else "n.d."
        lines.append(f"- **{c.title}** ({authors}, {year}) — {c.summary[:240] or c.abstract[:240]}")
    return "\n".join(lines)


def _template_reflection(*, query: str, outcomes: dict) -> str:
    highlights = []
    for k, v in outcomes.items():
        if isinstance(v, (str, int, float, bool)):
            highlights.append(f"{k}={v}")
        elif isinstance(v, list):
            highlights.append(f"{k}[{len(v)}]")
    body = "; ".join(highlights) or "no outcomes captured"
    return f"query={query!r} — {body}"


__all__ = [
    "EvolutionResult",
    "PaperMemoryEvolver",
    "extract_json",
]
