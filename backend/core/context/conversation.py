"""Unified 4-layer context management (Claude Code model).

Layer 1: System Prompt     — always preserved, never compacted
Layer 2: Active Window     — recent N turns, full fidelity
Layer 3: Compacted History — LLM-compressed older turns
Layer 4: Tool Results      — large results offloaded, referenced by ID
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from backend.core.llm.base import ChatMessage

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────

DEFAULT_ACTIVE_TURNS = 8       # keep this many user/assistant pairs
DEFAULT_COMPACT_THRESHOLD = 0.7  # compact when 70% of context window used
DEFAULT_TOOL_RESULT_CUTOFF = 20000  # chars — offload only very large results
CHARS_PER_TOKEN = 4  # rough English heuristic


@dataclass
class ConversationContext:
    """Manages the 4 layers of a conversation's token budget."""

    system_messages: list[ChatMessage] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)
    compacted_summary: str | None = None
    tool_result_store: dict[str, str] = field(default_factory=dict)

    active_turns: int = DEFAULT_ACTIVE_TURNS
    compact_threshold: float = DEFAULT_COMPACT_THRESHOLD
    context_window: int = 128_000

    @property
    def estimated_tokens(self) -> int:
        """Rough token count of the full message list (Layer 1+2+3)."""
        total = 0
        for m in self.system_messages:
            total += _token_estimate(m.content if isinstance(m.content, str) else str(m.content))
        # Active window
        active = self._active_messages()
        for m in active:
            content = m.content if isinstance(m.content, str) else str(m.content)
            total += _token_estimate(content)
            if m.tool_calls:
                total += 50 * len(m.tool_calls)
        # Compacted summary
        if self.compacted_summary:
            total += _token_estimate(self.compacted_summary)
        return total

    @property
    def should_compact(self) -> bool:
        """True if the conversation exceeds the compaction threshold."""
        limit = int(self.context_window * self.compact_threshold)
        return self.estimated_tokens > limit

    def add_message(self, msg: ChatMessage) -> None:
        """Append a message. Large tool results are automatically offloaded."""
        if msg.role == "tool" and msg.tool_call_id:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > DEFAULT_TOOL_RESULT_CUTOFF:
                ref = f"tool://{msg.tool_call_id}"
                self.tool_result_store[ref] = content
                # Replace with reference
                msg = ChatMessage(
                    role="tool",
                    content=f"[Tool result stored at {ref} — {len(content)} chars. "
                            f"Call expand_tool_result('{ref}') to retrieve.]",
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                )
        self.messages.append(msg)

    def build_messages(self) -> list[ChatMessage]:
        """Build the final message list for LLM call.

        Returns: system (L1) + compacted summary (L3) + active window (L2)
        Tool results (L4) are referenced inline, full content in store.
        """
        result: list[ChatMessage] = list(self.system_messages)

        if self.compacted_summary:
            result.append(ChatMessage(
                role="system",
                content=f"[Compacted history — {len(self.messages)} messages summarized]:\n{self.compacted_summary}"
            ))

        result.extend(self._active_messages())
        return result

    async def compact(self, llm: Any) -> None:
        """Compress older messages into a structured summary using the LLM.

        Keeps the most recent active_turns pairs, compresses everything before.
        """
        active = self._active_messages()
        older = self._older_messages()
        if not older:
            return

        system = (
            "Summarize this conversation history for an academic agent. "
            "Preserve: key decisions, findings, open questions, files discussed, "
            "citations mentioned. Output structured markdown with sections: "
            "## Key Decisions, ## Findings & Evidence, ## Open Questions, "
            "## Files / Sections Referenced, ## Citations Discussed."
        )
        history_text = _messages_to_text(older)
        user = f"Compress this conversation history:\n\n{history_text}"

        try:
            msg_list = [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ]
            stream = await llm.complete(msg_list, max_tokens=500)
            summary = await _collect_text(stream)
            # Merge with existing compacted summary
            if self.compacted_summary:
                self.compacted_summary = f"{self.compacted_summary}\n\n---\n\n{summary}"
            else:
                self.compacted_summary = summary
            log.info("context.compacted", older_count=len(older), summary_chars=len(summary))
        except Exception as exc:
            log.warning("context.compact_failed", error=str(exc))

    def expand_tool_result(self, ref: str) -> str | None:
        """Retrieve a stored tool result by reference."""
        return self.tool_result_store.get(ref)

    def _active_messages(self) -> list[ChatMessage]:
        """Return the most recent active_turns user/assistant pairs.

        Ensures the window never starts with a tool message — the LLM API
        requires every tool message to follow an assistant with tool_calls.
        """
        pairs = self.active_turns
        user_assist_count = 0
        cutoff = 0
        for i in range(len(self.messages) - 1, -1, -1):
            m = self.messages[i]
            if m.role in ("user", "assistant"):
                user_assist_count += 1
                if user_assist_count >= pairs * 2:
                    cutoff = i
                    break
        # Extend cutoff backwards to include the assistant that owns any
        # orphaned tool messages at the start of the window.
        while cutoff > 0:
            first = self.messages[cutoff]
            if first.role == "tool":
                for j in range(cutoff - 1, -1, -1):
                    if self.messages[j].role == "assistant" and self.messages[j].tool_calls:
                        cutoff = j
                        break
                else:
                    break  # no assistant found, give up
            else:
                break
        return self.messages[cutoff:]

    def _older_messages(self) -> list[ChatMessage]:
        """Messages before the active window (to be compacted)."""
        active = self._active_messages()
        if not active:
            return list(self.messages)
        first_active = self.messages.index(active[0]) if active[0] in self.messages else 0
        return self.messages[:first_active]


# ── helpers ───────────────────────────────────────────────────────


def _token_estimate(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _messages_to_text(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        role = m.role
        content = m.content if isinstance(m.content, str) else str(m.content)
        parts.append(f"[{role}]: {content[:500]}")
    return "\n".join(parts)


async def _collect_text(stream) -> str:
    parts: list[str] = []
    async for chunk in stream:
        if hasattr(chunk, "type") and chunk.type == "delta" and chunk.delta:
            parts.append(chunk.delta)
        elif hasattr(chunk, "type") and chunk.type == "error":
            raise Exception(chunk.error or "stream error")
    return "".join(parts)
