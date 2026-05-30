"""Match a natural-language query against the skill registry.

Scoring:
    score = 0.4 * keyword_score + 0.6 * semantic_score

where:
    keyword_score  = normalised count of trigger-keyword hits in query+context
    semantic_score = cosine similarity between query embedding and the
                     skill description embedding

Semantic scoring is lazy: embeddings are computed on the first call and
cached per-skill. If the embedder is unavailable the matcher falls back
to pure keyword scoring.

See PLAN §6.2 and the aaf-skill-host SKILL.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from .loader import SkillRegistry
from .types import SkillMeta

if TYPE_CHECKING:
    from backend.core.llm.base import LLMProvider

log = structlog.get_logger(__name__)

KW_WEIGHT = 0.4
SEM_WEIGHT = 0.6

_DEFAULT_TOP_K = 3
_DEFAULT_MIN_SCORE = 0.3
_WORD_RE = re.compile(r"[A-Za-z\u4e00-\u9fa5]+")


@dataclass
class MatchResult:
    skill: SkillMeta
    score: float
    kw_score: float
    sem_score: float


def _builtin_fallback() -> SkillMeta:
    return SkillMeta(
        name="general-assistant",
        path=Path("<builtin>"),
        description="General-purpose assistant behaviour when no specialised skill matches.",
        body="You are a helpful, careful assistant. Answer accurately and ask for clarification when the request is ambiguous.",
    )


class SkillMatcher:
    def __init__(
        self,
        registry: SkillRegistry,
        *,
        embedder: LLMProvider | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self._registry = registry
        self._embedder = embedder
        self._embedding_model = embedding_model
        self._embed_cache: dict[str, list[float]] = {}
        self._cache_gen: int = -1
        self._embed_disabled = False

    def set_embedder(self, embedder: LLMProvider | None) -> None:
        self._embedder = embedder
        self._embed_disabled = False

    async def match(
        self,
        query: str,
        *,
        context: str = "",
        top_k: int = _DEFAULT_TOP_K,
        min_score: float = _DEFAULT_MIN_SCORE,
        domain: str | None = None,
    ) -> list[MatchResult]:
        skills = self._registry.snapshot()
        if domain:
            skills = [s for s in skills if s.domain == domain]
        if not skills:
            return [
                MatchResult(skill=_builtin_fallback(), score=min_score, kw_score=0.0, sem_score=0.0)
            ]

        query_text = (query + " " + context).strip()

        query_vec: list[float] | None = None
        if self._embedder is not None and not self._embed_disabled:
            try:
                query_vec = (await self._embedder.embed([query_text], model=self._embedding_model))[
                    0
                ]
                await self._ensure_skill_embeddings(skills)
            except Exception as exc:
                log.warning("skill.matcher.embed_failed", err=str(exc))
                self._embed_disabled = True
                query_vec = None

        scored: list[MatchResult] = []
        for s in skills:
            kw = _keyword_score(query_text, s)
            if query_vec is not None:
                desc_vec = self._embed_cache.get(s.name)
                sem = _cosine(query_vec, desc_vec) if desc_vec else 0.0
                score = KW_WEIGHT * kw + SEM_WEIGHT * sem
            else:
                sem = 0.0
                score = kw  # pure keyword fallback
            scored.append(MatchResult(skill=s, score=score, kw_score=kw, sem_score=sem))

        scored.sort(key=lambda r: r.score, reverse=True)
        filtered = [r for r in scored if r.score >= min_score][:top_k]

        # Exclusive collision: if two results both declare exclusive, keep
        # only the highest-scoring one.
        exclusive_seen = False
        deduped: list[MatchResult] = []
        for r in filtered:
            if r.skill.exclusive:
                if exclusive_seen:
                    continue
                exclusive_seen = True
            deduped.append(r)

        if not deduped:
            log.info("skill.matcher.fallback", query=query[:80])
            return [
                MatchResult(skill=_builtin_fallback(), score=min_score, kw_score=0.0, sem_score=0.0)
            ]
        return deduped

    # ----- embedding cache -------------------------------------------

    async def _ensure_skill_embeddings(self, skills: list[SkillMeta]) -> None:
        """Recompute the cache lazily when the registry generation changes."""
        if self._embedder is None:
            return
        if self._cache_gen == self._registry.generation and self._embed_cache:
            # still valid
            missing = [s for s in skills if s.name not in self._embed_cache]
        else:
            missing = skills
            self._embed_cache.clear()

        if not missing:
            self._cache_gen = self._registry.generation
            return

        texts = [f"{s.description}\n\nTriggers: {', '.join(s.triggers)}" for s in missing]
        vectors = await self._embedder.embed(texts, model=self._embedding_model)
        for s, v in zip(missing, vectors, strict=False):
            self._embed_cache[s.name] = v
        self._cache_gen = self._registry.generation


# ---- scoring helpers ------------------------------------------------------


def _tokenise(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def _keyword_score(query_text: str, skill: SkillMeta) -> float:
    """Fraction of triggers whose tokens all appear in the query."""
    query_tokens = set(_tokenise(query_text))
    if not skill.triggers:
        # fall back to description tokens
        desc_tokens = set(_tokenise(skill.description))
        if not desc_tokens:
            return 0.0
        overlap = query_tokens & desc_tokens
        return min(1.0, len(overlap) / max(4, len(desc_tokens) // 4))

    hits = 0
    for trig in skill.triggers:
        trig_tokens = set(_tokenise(trig))
        if trig_tokens and trig_tokens.issubset(query_tokens):
            hits += 1
    return hits / len(skill.triggers)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    cos = dot / (na * nb)
    # map [-1, 1] → [0, 1]
    return (cos + 1.0) / 2.0


__all__ = ["MatchResult", "SkillMatcher"]
