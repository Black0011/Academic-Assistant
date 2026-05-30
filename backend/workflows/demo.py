"""Tiny end-to-end workflow used by tests and local smoke runs.

Exercises the full Stage-3 surface with zero external dependencies:

    SkillHost.select_and_inject → LLM.complete → tool call → summary

It isn't meant to ship as-is; the real `research` / `write` workflows
arrive in a later milestone. What matters is that every moving part —
context, events, rule injection, budget accounting, primitives — works
together in one runnable file.
"""

from __future__ import annotations

from backend.core.events import Event, EventType

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .primitives import sequential


class DemoWorkflow(BaseWorkflow):
    """Three-stage smoke workflow: prepare → chat → finalize."""

    name = "demo"
    version = "1.0.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))

        try:
            await sequential(
                ctx,
                [
                    self._recall,
                    self._prepare,
                    self._chat,
                    self._finalize,
                    self._remember,
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

        await ctx.emit(Event(EventType.TASK_END, data={"verdict": "ok"}))
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results=ctx.state.get("answer"),
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    # ---- stages -----------------------------------------------------

    async def _recall(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            c.state.setdefault("memory_snapshot", None)
            if c.memory is None:
                return
            snap = await c.memory.snapshot(
                c.query,
                domain=c.input.get("domain", ""),
                session_id=c.session_id,
            )
            c.state["memory_snapshot"] = snap
            await c.emit(
                Event(
                    EventType.MEMORY_READ,
                    data={
                        "papers": len(snap.related_papers),
                        "heuristics": len(snap.heuristics),
                        "reflections": len(snap.recent_reflections),
                        "doc_chunks": len(snap.doc_chunks),
                    },
                )
            )

        await self.stage_soft(ctx, "recall", inner)

    async def _prepare(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.skill_host is not None:
                bundle = await c.skill_host.select_and_inject(c.query)
                c.state["bundle"] = bundle
                await c.emit(Event(EventType.SKILL_MATCHED, data={"skills": bundle.matched_skills}))
            rule_prompt = ""
            if c.rule_engine is not None:
                rule_prompt = c.rule_engine.system_prompt(agent="all")
            c.state["rule_prompt"] = rule_prompt

        await self.stage(ctx, "prepare", inner)

    async def _chat(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.llm is None:
                c.state["answer"] = f"[offline] echo: {c.query}"
                return
            # Build a minimal system prompt from skills + rules.
            system_parts: list[str] = []
            bundle = c.state.get("bundle")
            bundle_additions = getattr(bundle, "system_additions", "") if bundle else ""
            if bundle_additions:
                system_parts.append(bundle_additions)
            if c.state.get("rule_prompt"):
                system_parts.append(c.state["rule_prompt"])
            system = "\n\n".join(system_parts) or "You are a helpful assistant."

            from backend.core.errors import LLMAPIError
            from backend.core.llm.base import ChatMessage

            messages = [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=c.query),
            ]
            chunks: list[str] = []
            stream = await c.llm.complete(messages)
            async for chunk in stream:
                if chunk.type == "delta" and chunk.delta:
                    chunks.append(chunk.delta)
                elif chunk.type == "error":
                    raise LLMAPIError(chunk.error or "llm error")
                elif chunk.type == "done" and chunk.usage is not None:
                    c.budget.accrue_llm(
                        prompt_tokens=chunk.usage.prompt_tokens or 0,
                        completion_tokens=chunk.usage.completion_tokens or 0,
                    )
            c.state["answer"] = "".join(chunks)

        await self.stage(ctx, "chat", inner)

    async def _finalize(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            answer = c.state.get("answer") or ""
            c.state["summary"] = answer[:200]

        await self.stage(ctx, "finalize", inner)

    async def _remember(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                return
            summary = c.state.get("summary") or ""
            if not summary:
                return
            # Lazy imports so offline callers needn't ship the memory dep.
            from backend.memory import PaperMemoryEvolver

            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            await evolver.write_session_reflection(
                task_id=c.task_id,
                query=c.query,
                outcomes={"summary": summary, "verdict": "ok"},
                session_id=c.session_id,
                user_id=c.user_id,
            )
            await c.emit(Event(EventType.MEMORY_WRITE, data={"kind": "reflection"}))

        await self.stage(ctx, "remember", inner)


__all__ = ["DemoWorkflow"]
