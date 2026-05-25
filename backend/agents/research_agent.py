"""ResearchAgent — LLM-driven academic paper search via tool-calling loop.

Implements the Planner → Executor pattern from PLAN §10.3:

    1. Build system prompt (inject memory context + available tools)
    2. Send user query to LLM with tool_specs
    3. Loop:
       a. Collect LLM response (text + tool_calls)
       b. If no tool_calls → done
       c. Execute each tool_call via ToolRegistry
       d. Append tool results as ChatMessage(role="tool")
       e. Call LLM again
    4. Extract search results from accumulated tool responses

Design tenets (rule aaf-agent-workflow):

* **Stateless.** No per-run mutable state on the instance.
* **Fallback-safe.** Callers always have the legacy search path when
  the agent isn't available (no LLM / no tools).
* **Budget-aware.** Every LLM call accrues tokens to the workflow budget.
* **Bounded.** ``max_rounds`` caps the loop to prevent runaway token usage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from backend.core.budget import Budget
from backend.core.events import Event
from backend.core.llm.base import (
    ChatMessage,
    CompletionChunk,
    LLMProvider,
    ToolCall,
    ToolSpec,
    Usage,
    collect_text,
)
from backend.memory.models import MemorySnapshot
from backend.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "planner" / "research.md"

# Fallback system prompt when the file is missing (shouldn't happen in normal deploys).
_FALLBACK_SYSTEM = (
    "You are an academic research assistant. Use "
    "mcp__google-scholar__search_google_scholar_key_words (Google Scholar, PRIMARY) "
    "to search for papers. Fall back to arxiv__search only if needed. "
    "Always use English keywords — translate non-English queries first."
)

# Tools the agent is allowed to use. MCP tools matching google-scholar
# are added dynamically via _effective_allowlist() at runtime.
_ALLOWED_TOOLS = frozenset({"arxiv__search", "pdf__parse"})

def _effective_allowlist(tools: Any) -> list[str]:
    """Return tools the agent can use. Sticks to arxiv for now."""
    return ["arxiv__search", "pdf__parse"]


def _load_system_prompt() -> str:
    """Load the system prompt template from disk."""
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        log.warning("research_agent.prompt_missing", path=str(_PROMPT_PATH))
        return _FALLBACK_SYSTEM


def _format_memory_context(snapshot: MemorySnapshot | None) -> str:
    """Format memory snapshot into a prompt-injectable string."""
    if snapshot is None:
        return "(No prior research context available.)"
    parts: list[str] = []
    if snapshot.related_papers:
        papers_str = "\n".join(
            f"- {p.title} ({p.year or '?'})" for p in snapshot.related_papers[:5]
        )
        parts.append(f"**Previously found papers:**\n{papers_str}")
    if snapshot.heuristics:
        heur_str = "\n".join(f"- {h.name}: {h.description}" for h in snapshot.heuristics[:3])
        parts.append(f"**Research heuristics:**\n{heur_str}")
    if snapshot.recent_reflections:
        refl_str = "\n".join(
            f"- {r.content[:120]}" for r in snapshot.recent_reflections[:3]
        )
        parts.append(f"**Recent reflections:**\n{refl_str}")
    if snapshot.doc_chunks:
        parts.append(f"**Related document chunks:**\n{snapshot.doc_chunks_text(max_chars=600)}")
    return "\n\n".join(parts) if parts else "(No prior research context available.)"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ResearchAgent:
    """Stateless agent that drives paper search via LLM tool-calling loop."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        tools: ToolRegistry,
        max_rounds: int = 5,
        max_results_per_search: int = 5,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._max_rounds = max_rounds
        self._max_results_per_search = max_results_per_search

    async def run(
        self,
        query: str,
        memory_snapshot: MemorySnapshot | None = None,
        *,
        budget: Budget,
        emit: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Execute the full agent loop. Returns a list of search hit dicts.

        Each dict has the shape produced by ``arxiv__search``: paper_id,
        title, authors, year, summary, pdf_url, categories, etc.
        """
        # 1. Build system prompt with memory context
        template = _load_system_prompt()
        memory_ctx = _format_memory_context(memory_snapshot)
        system = template.replace("{memory_context}", memory_ctx)

        # 2. Prepare tool specs (builtins + google-scholar MCP if available)
        allowed = _effective_allowlist(self._tools)
        tool_specs = self._tools.list_for_injection(only=allowed)
        if not tool_specs:
            log.warning("research_agent.no_tools")
            return []

        # 3. Initialize conversation
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=query),
        ]

        all_hits: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # 4. Agent loop
        for round_num in range(1, self._max_rounds + 1):
            if emit is not None:
                await emit(Event(
                    "task.agent_round",
                    data={"stage": "agent_search", "round": round_num, "hits_so_far": len(all_hits)},
                ))

            log.info(
                "research_agent.round",
                round=round_num,
                messages=len(messages),
                hits=len(all_hits),
            )

            # Call LLM with tools
            stream = await self._llm.complete(messages, tools=tool_specs)
            text, tool_calls, usage, reasoning = await collect_text(stream)

            # Accrue budget
            if usage is not None:
                budget.accrue_llm(
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                )

            # Append assistant message (with text and/or tool_calls)
            assistant_msg = ChatMessage(role="assistant", content=text or "")
            if tool_calls:
                assistant_msg.tool_calls = tool_calls
            assistant_msg.reasoning_content = reasoning  # Always set: DeepSeek V4 requires it even when None/empty
            messages.append(assistant_msg)

            # No tool calls → agent decided to stop
            if not tool_calls:
                log.info("research_agent.done", round=round_num, reason="no_tool_calls")
                break

            # Execute each tool call and collect results
            for tc in tool_calls:
                tool_result = await self._execute_tool_call(tc, emit=emit)
                # Append tool result message
                result_content = json.dumps(tool_result, ensure_ascii=False, default=str)
                messages.append(ChatMessage(
                    role="tool",
                    content=result_content,
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

                # Extract hits from arxiv__search results
                if tc.name == "arxiv__search" and isinstance(tool_result, dict):
                    for hit in tool_result.get("results", []):
                        pid = hit.get("paper_id", "")
                        if pid and pid not in seen_ids:
                            seen_ids.add(pid)
                            all_hits.append(hit)

        else:
            log.info("research_agent.done", round=self._max_rounds, reason="max_rounds")

        log.info("research_agent.complete", total_hits=len(all_hits))
        return all_hits

    async def _execute_tool_call(
        self,
        tc: ToolCall,
        *,
        emit: Any | None = None,
    ) -> dict[str, Any]:
        """Execute a single tool call and return the result data."""
        allowed = _effective_allowlist(self._tools)
        if tc.name not in allowed:
            return {"ok": False, "error": f"tool {tc.name!r} not allowed"}

        async def sink(event_type: str, data: dict[str, Any]) -> None:
            if emit is not None:
                await emit(Event(event_type, data=data))

        result = await self._tools.call(tc.name, tc.arguments, sink=sink)
        if result.ok:
            return result.data or {}
        return {"ok": False, "error": result.error or "unknown error"}


__all__ = ["ResearchAgent"]
