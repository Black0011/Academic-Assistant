"""ProjectRevisionWorkflow — rewrite multiple files across a bundle project.

Like Cursor's agent: explores files → plans changes → applies edits → returns diffs.

Input: ``manuscript_id`` + user instruction.
Output: ``{plan, changes: [{path, before, after}], files_modified}``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.core.context_manager import ContextManager
from backend.core.events import Event, EventType

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .citation_guard import audit_citations, auto_fix_suspects
from .primitives import sequential
from .project_consult import _read_file, _format_excerpts
from .write import _ask, _format_papers

_MAX_ROUNDS = 3
_MAX_FILES_PER_ROUND = 3
_MAX_CHARS_PER_FILE = 100_000

_REVISE_SYSTEM = (
    "You are a senior academic editor. You have read the paper files and "
    "received a revision instruction. Produce a concrete revision plan: "
    "for each file that needs changes, provide the COMPLETE new content. "
    "Output STRICT JSON only."
)

_REVISE_USER = (
    "Revision instruction:\n{query}\n\n"
    "Current file contents:\n{excerpts}\n\n"
    "Relevant papers from knowledge base:\n{papers}\n\n"
    "Citation verification results:\n{verify_report}\n\n"
    "### Rules\n"
    "- Only modify files that actually need changes.\n"
    "- Provide the COMPLETE new file content, not just the changed lines.\n"
    "- Preserve the original formatting/style unless the instruction asks otherwise.\n"
    "- If citation data in the text differs from verified sources, correct it.\n"
    "- If a citation is listed as suspect and you cannot verify it, add a TODO comment.\n"
    "- If no changes are needed for a file, don't include it.\n\n"
    'Return JSON:\n'
    '{{\n'
    '  "plan": "1-sentence summary of overall changes",\n'
    '  "changes": [\n'
    '    {{\n'
    '      "path": "sections/intro.tex",\n'
    '      "after": "complete new file content...",\n'
    '      "summary": "what changed and why"\n'
    '    }}\n'
    '  ]\n'
    '}}'
)


def _format_verify_report(suspects: list[dict[str, str]], verified_ids: set[str]) -> str:
    """Format citation verification results for the LLM prompt."""
    if not suspects and not verified_ids:
        return "(no citations were verified — the text may not contain citations)"
    lines: list[str] = []
    if verified_ids:
        lines.append(f"Verified citations (found in knowledge base): {len(verified_ids)} papers")
        lines.append(f"  IDs: {', '.join(sorted(verified_ids)[:20])}")
    if suspects:
        lines.append(f"SUSPECT citations (NOT found — may be incorrect or fabricated):")
        for s in suspects:
            lines.append(f"  - [{s['key']}] — {s.get('reason', 'unknown issue')}")
    return "\n".join(lines)


def _safe_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


class ProjectRevisionWorkflow(BaseWorkflow):
    """Multi-file revision across a bundle project."""

    name = "project-revision"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(
                ctx,
                [self._validate, self._recall, self._explore, self._verify, self._revise, self._audit, self._reflect],
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

        changes = ctx.state.get("changes", [])
        results: dict[str, Any] = {
            "plan": ctx.state.get("plan", ""),
            "changes": changes,
            "files_modified": [c["path"] for c in changes],
            "citations": sorted(ctx.state.get("citations", set())),
            "suspect_citations": ctx.state.get("suspect_citations", []),
            "verified_citations": sorted(ctx.state.get("_verified_citation_ids", set())),
            "verify_suspects": ctx.state.get("_verify_suspects", []),
        }
        await ctx.emit(Event(EventType.TASK_END, data={
            "verdict": "ok",
            "files_modified": len(results["files_modified"]),
        }))
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results=results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    async def _validate(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if not (c.query or "").strip():
                raise ValueError("project-revision needs a revision instruction.")
            tree = c.state.get("bundle_tree") or c.input.get("bundle_tree")
            if not tree:
                raise ValueError("project-revision needs a bundle_tree.")
        await self.stage(ctx, "validate", inner)

    async def _recall(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            c.state["papers"] = []
            if c.memory is None:
                return
            snap = await c.memory.snapshot(c.query or "", domain="revision", k=6, session_id=c.session_id)
            c.state["papers"] = list(snap.related_papers)
        await self.stage_soft(ctx, "recall", inner)

    async def _explore(self, ctx: WorkflowContext) -> None:
        """Agentic exploration: LLM reads files it needs via read_file tool."""
        async def inner(c: WorkflowContext) -> None:
            tree: list[dict[str, Any]] = c.state.get("bundle_tree", [])
            text_files = [
                f for f in tree
                if f.get("is_text") and any(f["path"].endswith(ext) for ext in (".tex", ".md", ".txt", ".bib"))
            ]
            file_list_str = "\n".join(
                f"  {f['path']} ({f.get('size', '?')} bytes)"
                for f in text_files[:80]
            ) or "(empty project)"

            if c.llm is None:
                c.state["read_content"] = {}
                c.state["files_read"] = []
                return

            from backend.core.llm.base import ChatMessage, ToolSpec, collect_text
            adapter = c.bundle
            read_content: dict[str, str] = {}

            read_tool = ToolSpec(name="read_file", description="Read a project file. Returns full content (capped at 8000 chars).", parameters={"type": "object", "properties": {"path": {"type": "string", "description": "File path, e.g. sections/intro.tex"}}, "required": ["path"]})
            expand_tool = ToolSpec(name="expand_tool_result", description="Retrieve full content of a large offloaded tool result.", parameters={"type": "object", "properties": {"tool_result_id": {"type": "string"}}, "required": ["tool_result_id"]})
            all_tools = [read_tool, expand_tool]
            system_msg = "You are an academic editor. Explore the project to understand the revision needed.\n\nProject files:\n" + file_list_str
            messages: list[ChatMessage] = [ChatMessage(role="system", content=system_msg)]
            # Load conversation history for thread continuity
            raw_history = c.input.get("history")
            if isinstance(raw_history, list):
                for h in raw_history[-20:]:
                    if not isinstance(h, dict): continue
                    role = str(h.get("role", "")).strip().lower()
                    if role == "user":
                        messages.append(ChatMessage(role="user", content=str(h.get("content", ""))))
                    elif role == "assistant":
                        tc = h.get("tool_calls")
                        tcs = None
                        if isinstance(tc, list) and tc:
                            tcs = [{"id": c.get("id", f"hist_{i}"), "name": c["name"], "arguments": c.get("arguments", {})} for i, c in enumerate(tc) if isinstance(c, dict) and c.get("name")]
                        msg = ChatMessage(role="assistant", content=str(h.get("content", "")))
                        if tcs: msg.tool_calls = tcs
                        messages.append(msg)
                    elif role == "tool":
                        messages.append(ChatMessage(role="tool", content=str(h.get("content", "")), tool_call_id=str(h.get("tool_call_id", "")), name=str(h.get("name", ""))))
            messages.append(ChatMessage(role="user", content=c.query or "Revise this project"))

            for round_num in range(1, 6):
                await c.emit(Event(EventType.TASK_PROGRESS, data={"round": round_num, "action": "thinking", "files_read": len(read_content)}))
                stream = await c.llm.complete(messages, tools=all_tools, temperature=0.2)
                text, tool_calls, usage, reasoning = await collect_text(stream)

                assistant_msg = ChatMessage(role="assistant", content=text or "")
                if tool_calls: assistant_msg.tool_calls = tool_calls
                assistant_msg.reasoning_content = reasoning
                messages.append(assistant_msg)

                if not tool_calls:
                    break

                for tc in tool_calls:
                    if tc.name == "expand_tool_result":
                        messages.append(ChatMessage(role="tool", content="(tool results are kept inline — no offloading in this workflow)", tool_call_id=tc.id))
                        continue
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
                            messages.append(ChatMessage(role="tool", content=truncated, tool_call_id=tc.id))
                            await c.emit(Event(EventType.TASK_PROGRESS, data={"action": "read", "path": path, "chars": len(truncated)}))
                        else:
                            messages.append(ChatMessage(role="tool", content="(file empty or not found)", tool_call_id=tc.id))
                    except Exception as exc:
                        messages.append(ChatMessage(role="tool", content=f"(error: {exc})", tool_call_id=tc.id))

            c.state["read_content"] = read_content
            c.state["files_read"] = list(read_content.keys())
        await self.stage(ctx, "explore", inner)

    async def _verify(self, ctx: WorkflowContext) -> None:
        """Research and verify citations before revision."""
        async def inner(c: WorkflowContext) -> None:
            read_content = c.state.get("read_content", {})
            all_text = "\n".join(read_content.values())
            if not all_text.strip():
                return

            # 1. Run citation audit on all files
            audit = await audit_citations(c, text=all_text, stage="project-revision:original")
            suspects = list(audit.suspect_citations)

            # 2. Also include suspect_citations passed from parent task
            parent_suspects = c.input.get("suspect_citations", [])
            if parent_suspects:
                seen = {s["key"] for s in suspects}
                for s in parent_suspects:
                    if s["key"] not in seen:
                        suspects.append(s)
                        seen.add(s["key"])

            # 3. Auto-research missing citations (uses MCP + arxiv)
            if suspects:
                await c.emit(Event(EventType.TASK_PROGRESS, data={
                    "stage": "verify", "action": "researching", "suspect_count": len(suspects),
                }))
                suspects = await auto_fix_suspects(c, suspects)
                await c.emit(Event(EventType.TASK_PROGRESS, data={
                    "stage": "verify", "action": "researched", "remaining_suspects": len(suspects),
                }))

            c.state["_verify_suspects"] = suspects
            c.state["_verified_citation_ids"] = audit.paper_ids
            await c.emit(Event(EventType.TASK_PROGRESS, data={
                "stage": "verify", "action": "done",
                "verified_citations": len(audit.paper_ids),
                "suspect_citations": len(suspects),
            }))
        await self.stage(ctx, "verify", inner)

    async def _revise(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            read_content = c.state.get("read_content", {})
            if c.llm is None:
                c.state["plan"] = "No LLM available."
                c.state["changes"] = []
                return

            suspects = c.state.get("_verify_suspects", [])
            verified_ids = c.state.get("_verified_citation_ids", set())
            verify_report = _format_verify_report(suspects, verified_ids)

            excerpts = _format_excerpts(read_content)
            raw = await _ask(
                c,
                system=_REVISE_SYSTEM,
                user=_REVISE_USER.format(
                    query=c.query or "",
                    excerpts=excerpts,
                    papers=_format_papers(c.state.get("papers", [])),
                    verify_report=verify_report,
                ),
                route="reasoning",
            )
            plan_data = _safe_json(raw)
            plan_text = plan_data.get("plan", "")
            changes: list[dict[str, Any]] = plan_data.get("changes", [])

            # Enrich changes with before content for diffs
            for ch in changes:
                path = ch.get("path", "")
                if path in read_content:
                    ch["before"] = read_content[path]
                else:
                    ch["before"] = ""

            c.state["plan"] = plan_text
            c.state["changes"] = changes

            await c.emit(Event(EventType.TASK_PROGRESS, data={
                "action": "revise",
                "plan": plan_text,
                "changed_files": [c.get("path") for c in changes],
            }))
        await self.stage(ctx, "revise", inner)

    async def _audit(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            all_text = "\n".join(
                ch.get("after", "") for ch in c.state.get("changes", [])
            )
            audit = await audit_citations(c, text=all_text, stage="project-revision:revised")
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
                query=c.query or "Project Revision",
                outcomes={
                    "verdict": "ok",
                    "kind": "project-revision",
                    "files_modified": len(c.state.get("changes", [])),
                },
                session_id=c.session_id,
                user_id=c.user_id,
            )
        await self.stage_soft(ctx, "reflect", inner)


__all__ = ["ProjectRevisionWorkflow"]
