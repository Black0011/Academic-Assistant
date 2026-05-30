"""Shared conversation history normalisation for workflows.

Normalises the full message chain (user/assistant+tool_calls/tool) into
readable text blocks suitable for inclusion in text-based LLM prompts.
"""

from __future__ import annotations

from typing import Any


def normalise_history(raw: Any) -> list[dict[str, str]]:
    """Convert a full message chain into a readable role/content list.

    Handles tool messages and assistant tool_calls by formatting them
    as readable annotations ([Agent called tools: ...], [Tool result: ...]).
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()

        if role == "tool":
            tool_name = str(item.get("name", "unknown"))
            summary = content[:200] + ("..." if len(content) > 200 else "")
            out.append({"role": "assistant", "content": f"[Tool result: {tool_name}] {summary}"})
            continue

        if role == "assistant":
            tc = item.get("tool_calls")
            if isinstance(tc, list) and tc:
                names = [c.get("name", "?") for c in tc if isinstance(c, dict)]
                if names:
                    content = f"[Agent called tools: {', '.join(names)}]\n{content}" if content else f"[Agent called tools: {', '.join(names)}]"
            if content:
                out.append({"role": "assistant", "content": content})
            continue

        if role == "user" and content:
            out.append({"role": "user", "content": content})
            continue
    return out


async def load_history_block(ctx: Any, max_tokens: int = 12_000) -> str:
    """Load, normalise, and compact conversation history for a text prompt.

    Returns a formatted string block (or empty string if no history).
    """
    from backend.core.context_manager import ContextManager

    raw = ctx.input.get("history")
    history = normalise_history(raw)
    if not history:
        return ""
    cm = ContextManager(llm=None)
    text = await cm._prepare_history(history, max_tokens)
    return f"\n## Prior Conversation\n{text}\n\n" if text.strip() else ""


__all__ = ["normalise_history", "load_history_block"]
