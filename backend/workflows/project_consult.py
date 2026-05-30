"""ProjectConsultWorkflow — agent-driven file exploration like Cursor/Claude Code.

Instead of pre-loading every bundle file into a single LLM call (which blows
the context window), the agent:

1. Starts with a file *listing* (names + sizes, cheap)
2. Picks which files look relevant to the user's question
3. Reads those files
4. Evaluates whether it has enough context; if not, picks more files
5. Produces a final answer

Each round emits events so the frontend can show the agent's exploration
progress in real time.

Input contract (via ``ctx.input``):
* ``manuscript_id`` — bundle manuscript to explore.
* The runner pre-fills ``ctx.state["bundle_tree"]`` with the file listing.

Output::

    {
      "analysis":        prose markdown answer,
      "files_read":      [paths the agent chose to read],
      "exploration_log": [{round, action, paths, reasoning}],
      "citations":       [...],
      "suspect_citations": [...],
    }
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from backend.core.context.history import normalise_history
from backend.core.context_manager import ContextManager
from backend.core.events import Event, EventType
from backend.memory.models import PaperCard

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .citation_guard import audit_citations
from .primitives import sequential
from .write import _ask, _format_papers

_MAX_ROUNDS = 5
_MAX_FILES_PER_ROUND = 3
_MAX_CHARS_PER_FILE = 100_000

_HISTORY_BLOCK = "\n\n## Prior Conversation\n{history}\n"


# ── prompts ─────────────────────────────────────────────────────────────────

_EXPLORE_SYSTEM = (
    "You are an academic research assistant exploring a paper project. "
    "You have access to the project's file tree. Use the `read_file` tool "
    "to read files that are relevant to the user's question. "
    "Be strategic: only read files likely to contain the needed information. "
    "When you have enough context, produce a final answer."
)

_EXPLORE_USER = (
    "User question:\n{query}\n\n"
    "Available files (path + size):\n{file_list}\n\n"
    "Files already read so far:\n{already_read}\n\n"
    "Pick up to {max_files} files to read next. If you already have enough "
    "context from previously read files, respond with `files: []` to generate "
    "the final answer.\n\n"
    'Return JSON:\n'
    '{{\n'
    '  "files": ["path/to/file1.tex", ...],\n'
    '  "reasoning": "one-line explanation of why these files were chosen"\n'
    '}}'
)

_ANSWER_SYSTEM = (
    "You are a senior academic assistant. Answer the user's question based on "
    "the provided paper excerpts. Be thorough and cite specific sections. "
    "Use markdown formatting. Always respond in Chinese; keep paper content, "
    "technical terms, and citations in their original English."
)

_ANSWER_USER = (
    "User question:\n{query}\n\n"
    "Relevant excerpts from the paper:\n---\n{excerpts}\n---\n\n"
    "Relevant papers from memory:\n{papers}\n\n"
    "Provide a detailed answer."
)

# ── helpers ─────────────────────────────────────────────────────────────────


def _safe_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


class ProjectConsultWorkflow(BaseWorkflow):
    """Agent-driven file exploration for large bundle projects.

    Stages: validate → recall → explore → audit → reflect.
    """

    name = "project-consult"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(
                ctx,
                [
                    self._validate,
                    self._recall,
                    self._explore,
                    self._research_citations,
                    self._audit,
                    self._reflect,
                ],
            )
        except Exception as exc:
            await ctx.emit(Event(EventType.TASK_END, data={"verdict": "error"}))
            return WorkflowOutput(
                task_id=ctx.task_id,
                verdict="error",
                trace=list(ctx.trace),
                budget=ctx.budget.snapshot(),
                error=f"{type(exc).__name__}: {exc}",
            )

        explored = ctx.state.get("exploration_log", [])
        tool_call_log: list[dict[str, Any]] = []
        for entry in explored:
            for path in entry.get("paths", []):
                tool_call_log.append({"name": "read_file", "kind": "file_read", "args": {"path": path}, "result_summary": f"Read file: {path}"})

        results: dict[str, Any] = {
            "analysis": ctx.state.get("analysis", ""),
            "files_read": ctx.state.get("files_read", []),
            "exploration_log": ctx.state.get("exploration_log", []),
            "citations": sorted(ctx.state.get("citations", set())),
            "suspect_citations": ctx.state.get("suspect_citations", []),
            "researched": ctx.state.get("researched", []),
            "research_failures": ctx.state.get("research_failures", []),
            "tool_calls": tool_call_log,
        }
        await ctx.emit(
            Event(EventType.TASK_END, data={
                "verdict": "ok",
                "files_read": len(results["files_read"]),
            })
        )
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results=results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    # ── stages ──────────────────────────────────────────────────────────

    async def _validate(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            tree = c.state.get("bundle_tree") or c.input.get("bundle_tree")
            if not tree or not isinstance(tree, list) or len(tree) == 0:
                raise ValueError(
                    "project-consult requires a non-empty bundle_tree — "
                    "make sure the manuscript is a bundle with at least one file."
                )
            if not (c.query or "").strip():
                raise ValueError("project-consult needs a non-empty query.")
        await self.stage(ctx, "validate", inner)

    async def _recall(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            c.state["papers"] = []
            if c.memory is None:
                return
            snap = await c.memory.snapshot(
                c.query or "",
                domain="consult",
                k=6,
                session_id=c.session_id,
            )
            c.state["papers"] = list(snap.related_papers)
        await self.stage_soft(ctx, "recall", inner)

    async def _explore(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            tree: list[dict[str, Any]] = c.state.get("bundle_tree", [])
            text_files = [
                f for f in tree
                if f.get("is_text") and any(
                    f["path"].endswith(ext) for ext in (".tex", ".md", ".txt", ".bib")
                )
            ]
            file_list_str = "\n".join(
                f"  {f['path']} ({f.get('size', '?')} bytes)"
                for f in text_files[:80]
            )

            raw_history = normalise_history(c.input.get("history"))
            cm = ContextManager(llm=c.llm)
            history_text = await cm._prepare_history(raw_history, 12_000)

            if c.llm is None:
                c.state["analysis"] = _template_answer(query=c.query or "", read_files=[])
                c.state["files_read"] = []
                c.state["exploration_log"] = []
                return

            from backend.core.llm.base import ChatMessage, ToolSpec, collect_text
            adapter = c.bundle
            read_content: dict[str, str] = {}
            exploration_log: list[dict[str, Any]] = []

            read_tool = ToolSpec(name="read_file", description="Read a project file. Returns full content (capped at 8000 chars).", parameters={"type": "object", "properties": {"path": {"type": "string", "description": "File path, e.g. sections/intro.tex"}}, "required": ["path"]})
            system_msg = _EXPLORE_SYSTEM + f"\n\nProject files:\n{file_list_str}"
            messages: list[ChatMessage] = [ChatMessage(role="system", content=system_msg), ChatMessage(role="user", content=c.query or "Explore this project")]

            for round_num in range(1, _MAX_ROUNDS + 1):
                await c.emit(Event(EventType.TASK_PROGRESS, data={"round": round_num, "action": "thinking", "files_read": len(read_content)}))
                stream = await c.llm.complete(messages, tools=[read_tool], temperature=0.2)
                text, tool_calls, usage, reasoning = await collect_text(stream)

                assistant_msg = ChatMessage(role="assistant", content=text or "")
                if tool_calls: assistant_msg.tool_calls = tool_calls
                assistant_msg.reasoning_content = reasoning
                messages.append(assistant_msg)

                if not tool_calls:
                    c.state["analysis"] = text.strip()
                    exploration_log.append({"round": round_num, "action": "answer"})
                    break

                # Execute file reads requested by the LLM
                paths_read: list[str] = []
                for tc in tool_calls:
                    if tc.name != "read_file":
                        messages.append(ChatMessage(role="tool", content=f"(unknown tool: {tc.name})", tool_call_id=tc.id))
                        continue
                    path = str(tc.arguments.get("path", "")).strip()
                    if not path:
                        messages.append(ChatMessage(role="tool", content="(no path specified)", tool_call_id=tc.id))
                        continue
                    if path in read_content:
                        messages.append(ChatMessage(role="tool", content=f"(already read, {len(read_content[path])} chars)", tool_call_id=tc.id))
                        continue
                    try:
                        content = await _read_file(adapter, path)
                        if content:
                            truncated = content[:_MAX_CHARS_PER_FILE]
                            read_content[path] = truncated
                            paths_read.append(path)
                            messages.append(ChatMessage(role="tool", content=truncated, tool_call_id=tc.id))
                            await c.emit(Event(EventType.TASK_PROGRESS, data={"round": round_num, "action": "read", "path": path, "chars": len(truncated)}))
                        else:
                            messages.append(ChatMessage(role="tool", content="(file empty or not found)", tool_call_id=tc.id))
                    except Exception as exc:
                        messages.append(ChatMessage(role="tool", content=f"(error: {exc})", tool_call_id=tc.id))
                exploration_log.append({"round": round_num, "action": "read", "paths": paths_read})

            if not c.state.get("analysis", "").strip():
                c.state["analysis"] = _template_answer(query=c.query or "", read_files=list(read_content.keys()))
            c.state["files_read"] = list(read_content.keys())
            c.state["exploration_log"] = exploration_log

        await self.stage(ctx, "explore", inner)

    async def _research_citations(self, ctx: WorkflowContext) -> None:
        """P19: Auto-research missing citations found in explored files."""
        async def inner(c: WorkflowContext) -> None:
            researched: list[str] = []
            failures: list[str] = []
            if c.memory is None:
                c.state["researched"] = researched
                c.state["research_failures"] = failures
                return

            # Collect all citations from read files
            all_text = "\n".join(c.state.get("files_read", []))
            import re
            cite_re = re.compile(r"\\cite\{([^}]+)\}|\[([A-Za-z0-9_-]{3,64})\]")
            keys: set[str] = set()
            for m in cite_re.finditer(all_text):
                keys.add((m.group(1) or m.group(2)).strip())

            if not keys:
                c.state["researched"] = researched
                c.state["research_failures"] = failures
                return

            # Check which are missing from knowledge store
            knowledge = c.memory.knowledge
            missing: list[str] = []
            for key in keys:
                card = await knowledge.get(key)
                if card is None:
                    missing.append(key)

            if not missing:
                await c.emit(Event(EventType.TASK_PROGRESS, data={
                    "stage": "research", "found_all": len(keys),
                }))
                c.state["researched"] = researched
                c.state["research_failures"] = failures
                return

            await c.emit(Event(EventType.TASK_PROGRESS, data={
                "stage": "research", "checking": len(missing),
            }))

            # Try to research each missing key
            from backend.workflows.citation_guard import _research_missing, _strip_year_prefix

            for key in sorted(missing):
                # Try exact match first, then year-stripped
                variants = [key, _strip_year_prefix(key)]
                found = False
                for variant in variants[:2]:
                    if c.tools:
                        try:
                            result = await c.tools.call("arxiv__search", {"query": variant, "max_results": 2})
                            if result.ok:
                                hits = list((result.data or {}).get("results") or [])
                                for hit in hits:
                                    from backend.workflows.research import _hit_to_card
                                    card = _hit_to_card(hit, None, run_id=f"{c.task_id}:cite", user_id=c.user_id)
                                    await c.memory.knowledge.write_card(card)
                                    researched.append(card.paper_id)
                                    found = True
                        except Exception:
                            pass
                if found:
                    await c.emit(Event(EventType.TASK_PROGRESS, data={
                        "stage": "research", "found": key,
                    }))
                else:
                    failures.append(key)
                    await c.emit(Event(EventType.TASK_PROGRESS, data={
                        "stage": "research", "missing": key,
                    }))

            c.state["researched"] = researched
            c.state["research_failures"] = failures

        await self.stage(ctx, "research_citations", inner)

    async def _audit(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            audit = await audit_citations(
                c, text=c.state.get("analysis", ""), stage="project-consult:analysis"
            )
            c.state["citations"] = audit.paper_ids
            c.state["suspect_citations"] = list(audit.suspect_citations)
        await self.stage(ctx, "audit", inner)

    async def _reflect(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                return
            from backend.memory.paper_memory import PaperMemoryEvolver
            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            await evolver.write_session_reflection(
                task_id=c.task_id,
                query=c.query or "Project Consult",
                outcomes={
                    "verdict": "ok",
                    "kind": "project-consult",
                    "files_read": len(c.state.get("files_read", [])),
                },
                session_id=c.session_id,
                user_id=c.user_id,
            )
        await self.stage_soft(ctx, "reflect", inner)


# ── helpers ─────────────────────────────────────────────────────────────────


async def _read_file(adapter: Any, path: str) -> str | None:
    """Read a single file from the bundle via the adapter."""
    if adapter is None:
        return None
    try:
        return await adapter.read_text(path)
    except Exception:
        return None


def _format_excerpts(read_content: dict[str, str]) -> str:
    """Format read files into a single text block for the LLM."""
    parts: list[str] = []
    for path, content in sorted(read_content.items()):
        parts.append(f"%%% FILE: {path} %%%\n\n{content}\n")
    return "\n".join(parts)


def _template_answer(*, query: str, read_files: list[str]) -> str:
    return (
        f"**[Template Fallback — LLM unavailable]**\n\n"
        f"Question: {query}\n\n"
        f"Files explored: {len(read_files)}\n"
        f"{chr(10).join(f'- {f}' for f in read_files)}\n\n"
        f"The file exploration machinery is working correctly, but "
        f"no LLM is wired to produce a real analysis. "
        f"Configure a provider in Settings → LLM."
    )


__all__ = ["ProjectConsultWorkflow"]
