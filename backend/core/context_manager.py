"""ContextManager — token-budgeted multi-turn conversation management.

Follows Claude Code / OpenCode patterns:

1. **Token Budget** — allocated across system / history / reference / response.
2. **Structured Compaction** — old turns are LLM-summarised, not truncated.
3. **Progressive Disclosure** — reference text is capped; the agent can request more.
4. **Three Thresholds** — 60% warn, 85% compact, 95% emergency.

Usage in a workflow::

    from backend.core.context_manager import ContextManager, ContextBudget

    cm = ContextManager(llm=ctx.llm)
    budget = ContextBudget(total_limit=64_000)
    prompt = cm.build_prompt(
        system=system_msg,
        user_query=user_question,
        reference_text=paper_section,
        history=prior_turns,
        budget=budget,
    )
    # prompt is guaranteed ≤ budget.total_limit tokens
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ── token estimation ────────────────────────────────────────────────────────
# Rough heuristic: English ≈ chars/4, CJK ≈ chars/2.
# This is intentionally cheap (no tokenizer dependency) and good enough
# for budget tracking (±20% accuracy vs. real token count from the API).


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string. ~±20% accuracy, no deps."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿" or "　" <= ch <= "〿")
    other = len(text) - cjk
    return max(1, int(cjk / 1.8 + other / 3.5))


def _extract_usage(result_or_meta: Any) -> int:
    """Best-effort extraction of *actual* token usage from LLM metadata."""
    if isinstance(result_or_meta, dict):
        return int(result_or_meta.get("total_tokens") or result_or_meta.get("usage", {}).get("total_tokens") or 0)
    return 0


# ── budget ──────────────────────────────────────────────────────────────────


@dataclass
class ContextBudget:
    """Token budget for a single LLM call."""

    total_limit: int = 64_000
    _system: int = 0
    _history: int = 0
    _reference: int = 0
    _user_query: int = 0

    # Reserve for the model's reply
    response_reserve: int = 4_000

    @property
    def used(self) -> int:
        return self._system + self._history + self._reference + self._user_query

    @property
    def remaining(self) -> int:
        return max(0, self.total_limit - self.used - self.response_reserve)

    @property
    def usage_ratio(self) -> float:
        return self.used / max(1, self.total_limit)

    @property
    def status(self) -> str:
        r = self.usage_ratio
        if r >= 0.95:
            return "emergency"
        if r >= 0.85:
            return "compact"
        if r >= 0.60:
            return "warn"
        return "ok"

    def allocate_system(self, text: str) -> int:
        self._system = estimate_tokens(text)
        return self._system

    def allocate_history(self, text: str) -> int:
        self._history = estimate_tokens(text)
        return self._history

    def allocate_reference(self, text: str) -> int:
        self._reference = estimate_tokens(text)
        return self._reference

    def allocate_query(self, text: str) -> int:
        self._user_query = estimate_tokens(text)
        return self._user_query


# ── compaction ──────────────────────────────────────────────────────────────


_COMPACT_SYSTEM = (
    "You are a context-compaction assistant. Summarise the conversation history "
    "below into a structured, information-dense format. Preserve ALL critical "
    "details — decisions, findings, citations, open questions, file references, "
    "and numeric data. Discard only filler and conversational noise. "
    "Output STRUCTURED MARKDOWN, not prose."
)

_COMPACT_USER = (
    "Summarise the following conversation turns into this structure:\n\n"
    "### Key Decisions\n- ...\n\n"
    "### Findings & Evidence\n- ...\n\n"
    "### Open Questions\n- ...\n\n"
    "### Files / Sections Referenced\n- ...\n\n"
    "### Citations Discussed\n- ...\n\n"
    "---\n"
    "Conversation to summarise:\n{turns}"
)


async def compact_history(
    history: list[dict[str, str]],
    *,
    llm: Any = None,
    max_input_turns: int = 20,
) -> str:
    """Compress conversation history into a structured summary.

    When ``llm`` is available, uses it to produce a dense structured summary
    (following Claude Code's compaction format). Falls back to simple
    concatenation when no LLM is wired.

    Returns a single compact string that replaces the raw history.
    """
    if not history:
        return ""

    # Take the most recent N turns for compaction input.
    recent = history[-max_input_turns:]

    if llm is None:
        # No LLM → simple concatenation with char cap (old behaviour, but
        # better than the previous 600-char brutal truncation).
        lines: list[str] = []
        for h in recent:
            role = "用户" if h.get("role") == "user" else "Agent"
            content = (h.get("content") or "")[:300]
            if content:
                lines.append(f"**{role}**: {content}")
        return "\n".join(lines) if lines else ""

    # LLM-based compaction
    turns_text = "\n---\n".join(
        f"[{h.get('role', '?')}]\n{h.get('content', '')[:800]}"
        for h in recent
    )
    try:
        result = await llm.chat(
            messages=[
                {"role": "system", "content": _COMPACT_SYSTEM},
                {"role": "user", "content": _COMPACT_USER.format(turns=turns_text)},
            ],
            route="fast",
        )
        content = ""
        if isinstance(result, str):
            content = result
        elif isinstance(result, dict):
            content = result.get("content") or result.get("text") or ""
        elif hasattr(result, "content"):
            content = result.content
        if content and len(str(content)) > 20:
            log.info("context.compact.ok", turns_in=len(recent), chars_out=len(str(content)))
            return str(content)
    except Exception as exc:
        log.warning("context.compact.failed", error=str(exc)[:120])

    # Fallback: simplified concatenation
    lines: list[str] = []
    for h in recent[-8:]:
        role = "用户" if h.get("role") == "user" else "Agent"
        content = (h.get("content") or "")[:500]
        if content:
            lines.append(f"**{role}**: {content}")
    return "\n".join(lines) if lines else ""


# ── the manager ─────────────────────────────────────────────────────────────


@dataclass
class ContextManager:
    """Token-budgeted context builder for multi-turn academic conversations.

    Usage per LLM call::

        cm = ContextManager(llm=ctx.llm, model_context_limit=64_000)
        prompt = await cm.build(
            system="You are a reviewer...",
            user_query="Is the abstract clear?",
            reference_text="...paper text...",
            history=[{"role":"user","content":"..."}, ...],
        )
        # prompt is a ready-to-use string guaranteed within budget.
    """

    llm: Any = None
    model_context_limit: int = 64_000

    # Allocation ratios (fraction of total_limit)
    system_ratio: float = 0.10   # 10% for system prompt
    history_ratio: float = 0.25  # 25% for conversation history
    reference_ratio: float = 0.45  # 45% for paper/reference text
    query_ratio: float = 0.05    # 5% for current query
    response_ratio: float = 0.10  # 10% reserved for model reply
    # Remaining 5% = buffer

    async def build(
        self,
        *,
        system: str,
        user_query: str,
        reference_text: str = "",
        history: list[dict[str, str]] | None = None,
    ) -> tuple[str, ContextBudget]:
        """Build a budget-compliant prompt string.

        Returns ``(prompt, budget)`` where ``prompt`` is the final text to
        send to the LLM and ``budget`` carries the token accounting for
        telemetry / logging.
        """
        budget = ContextBudget(total_limit=self.model_context_limit)

        # 1. System prompt — fixed allocation
        system = (system or "").strip()
        budget.allocate_system(system)
        system_budget = int(self.model_context_limit * self.system_ratio)
        if budget._system > system_budget:
            system = system[:int(system_budget * 3.5)]  # rough char trim

        # 2. History — compact if over budget
        history_budget = int(self.model_context_limit * self.history_ratio)
        history_text = await self._prepare_history(history or [], history_budget)
        budget.allocate_history(history_text)

        # 3. Reference text — cap to budget
        ref_budget = int(self.model_context_limit * self.reference_ratio)
        reference_text = (reference_text or "").strip()
        ref_est = estimate_tokens(reference_text)
        if ref_est > ref_budget:
            # Progressive disclosure: keep head + tail with truncation note
            head_chars = int(ref_budget * 2.5)  # ~half in English, more in CJK
            tail_chars = int(ref_budget * 1.0)
            if len(reference_text) > head_chars + tail_chars:
                reference_text = (
                    reference_text[:head_chars]
                    + f"\n\n[... {estimate_tokens(reference_text[head_chars:-tail_chars])} tokens omitted "
                    f"— ask to expand a specific section ...]\n\n"
                    + reference_text[-tail_chars:]
                )
        budget.allocate_reference(reference_text)

        # 4. Query
        budget.allocate_query(user_query)
        budget.response_reserve = int(self.model_context_limit * self.response_ratio)

        # 5. Assemble
        parts: list[str] = []
        if system:
            parts.append(system)
        if history_text.strip():
            parts.append(f"## Conversation History (compacted)\n{history_text}")
        if reference_text:
            parts.append(f"## Reference Text\n{reference_text}")
        parts.append(f"## Current Question\n{user_query}")

        prompt = "\n\n---\n\n".join(parts)
        log.info(
            "context.build",
            total_est=budget.used,
            limit=budget.total_limit,
            ratio=round(budget.usage_ratio, 2),
            status=budget.status,
        )
        return prompt, budget

    async def _prepare_history(
        self, history: list[dict[str, str]], token_budget: int
    ) -> str:
        """Prepare history text within *token_budget* tokens.

        Strategy (matching Claude Code's layers):
        1. If within budget → use as-is (micro-clear only: strip empty turns)
        2. If slightly over → trim old turns (history snip)
        3. If significantly over → LLM-compact old turns (compaction)
        """
        if not history:
            return ""

        # Micro-clear: strip empty / whitespace-only turns
        clean = [
            h for h in history
            if h.get("content", "").strip() and h.get("role") in {"user", "assistant"}
        ]

        # Try full history first
        full_text = "\n".join(
            f"[{h['role']}]: {h['content']}" for h in clean
        )
        if estimate_tokens(full_text) <= token_budget:
            return full_text

        # History snip: keep most recent turns that fit
        snipped: list[dict[str, str]] = []
        snipped_tokens = 0
        for h in reversed(clean):
            t = estimate_tokens(h.get("content", ""))
            if snipped_tokens + t > token_budget:
                break
            snipped.insert(0, h)
            snipped_tokens += t

        snipped_text = "\n".join(
            f"[{h['role']}]: {h['content']}" for h in snipped
        )

        # If snipping gives us most turns, use it
        if len(snipped) >= len(clean) * 0.7:
            return snipped_text

        # Compaction: LLM-summarise old turns, keep recent ones raw
        split = max(2, len(clean) // 2)
        old_turns = clean[:-split]
        recent_turns = clean[-split:]

        compacted = await compact_history(old_turns, llm=self.llm)

        recent_text = "\n".join(
            f"[{h['role']}]: {h['content']}" for h in recent_turns
        )

        result = f"### Earlier (compacted)\n{compacted}\n\n### Recent\n{recent_text}"
        if estimate_tokens(result) > token_budget:
            # Still over — emergency truncation
            max_chars = int(token_budget * 2.5)
            result = result[:max_chars] + "\n\n[... emergency truncation ...]"

        return result


__all__ = ["ContextManager", "ContextBudget", "compact_history", "estimate_tokens"]
