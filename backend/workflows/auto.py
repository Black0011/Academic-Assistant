"""AutoWorkflow — unified entry point with intent classification.

Routes user queries to research or writing workflows. When intent is
ambiguous, pauses and asks the user via the AgentQuestion mechanism.

Stages:
1. ``_classify`` — keyword-based intent detection; pauses if ambiguous.
2. ``_execute`` — delegates to ResearchWorkflow or WriteWorkflow.
"""

from __future__ import annotations

import re
import time
from typing import Any

from backend.core.events import Event, EventType
from backend.manuscripts.models import CreateManuscriptInput

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .primitives import sequential

# ── Intent classification keywords ───────────────────────────────

RESEARCH_KEYWORDS = [
    "research", "search", "find", "survey", "review",
    "调研", "搜索", "查找", "综述", "文献", "找", "查",
    "survey", "explore",
]

WRITE_KEYWORDS = [
    "write", "draft", "generate", "compose", "create",
    "写", "生成", "撰写", "创作", "起草", "写一篇", "生成一篇",
    "introduction", "abstract", "conclusion", "related work",
    "method", "experiment", "discussion", "section",
]


def _classify_intent(query: str) -> str:
    """Return 'research', 'write', or 'ambiguous' based on keyword scan."""
    q = query.lower()
    r_score = sum(1 for kw in RESEARCH_KEYWORDS if kw in q)
    w_score = sum(1 for kw in WRITE_KEYWORDS if kw in q)
    if r_score > w_score:
        return "research"
    if w_score > r_score:
        return "write"
    return "ambiguous"


def _guess_title(query: str) -> str:
    """Derive a plausible manuscript title from the user query."""
    cleaned = query.strip().rstrip(".。！!？?")
    if len(cleaned) <= 80:
        return cleaned
    return cleaned[:77] + "..."


# ── Workflow ──────────────────────────────────────────────────────


class AutoWorkflow(BaseWorkflow):
    name = "auto"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(ctx, [self._classify, self._execute])
        except Exception as exc:
            await ctx.emit(Event(EventType.TASK_END, data={"verdict": "error"}))
            return WorkflowOutput(
                task_id=ctx.task_id,
                verdict="error",
                trace=list(ctx.trace),
                budget=ctx.budget.snapshot(),
                error=f"{type(exc).__name__}: {exc}",
            )

        intent = ctx.state.get("_intent", "research")
        sub_results = ctx.state.get("_sub_results", {})
        await ctx.emit(Event(EventType.TASK_END, data={"verdict": "ok", "intent": intent}))
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results={**sub_results, "intent": intent},
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    # ---- stages ---------------------------------------------------

    async def _classify(self, ctx: WorkflowContext) -> None:
        intent = _classify_intent(ctx.query)
        if intent != "ambiguous":
            ctx.state["_intent"] = intent
            return

        # Ambiguous — ask the user via AgentQuestion
        response = await self.ask_user(
            prompt="你想让我做什么？",
            checkpoint="clarify_intent",
            prompt_data={
                "question": "请选择你想要的操作方向：",
                "options": [
                    {"id": "research", "label": "调研相关论文", "desc": "搜索 arXiv 文献，整理研究脉络"},
                    {"id": "write", "label": "撰写论文草稿", "desc": "生成学术段落或创建新稿件"},
                ],
            },
            stage="clarify",
        )

        if ctx.state.get("_paused"):
            # First run — save pause info for the runner
            await _save_pause_state(ctx)
            return

        # Resume path — extract user choice
        choice = response.get("data", {}).get("choice", "")
        if not choice and isinstance(response.get("data"), dict):
            choice = response["data"].get("selected", "")
        ctx.state["_intent"] = choice if choice in ("research", "write") else "research"

    async def _execute(self, ctx: WorkflowContext) -> None:
        # Don't execute if we just paused
        if ctx.state.get("_paused"):
            return

        intent = ctx.state.get("_intent", "research")

        if intent == "research":
            from .research import ResearchWorkflow

            sub = ResearchWorkflow()
            out = await sub.run(ctx)
            ctx.state["_sub_results"] = out.results

        elif intent == "write":
            manuscript_id = ctx.input.get("manuscript_id")
            if not manuscript_id and ctx.manuscripts is not None:
                try:
                    title = _guess_title(ctx.query)
                    body = CreateManuscriptInput(
                        title=title,
                        kind="bundle",
                        status="draft",
                        user_id=ctx.user_id,
                        session_id=ctx.session_id,
                    )
                    manuscript, _version = await ctx.manuscripts.create(body)
                    manuscript_id = manuscript.id
                    ctx.state["_sub_results"] = {
                        "action": "write",
                        "manuscript_id": manuscript_id,
                        "title": title,
                        "query": ctx.query,
                    }
                    ctx.state["_new_manuscript_id"] = manuscript_id
                except Exception:
                    ctx.state["_sub_results"] = {
                        "action": "needs_manuscript",
                        "query": ctx.query,
                        "error": "failed to auto-create manuscript",
                    }
            elif manuscript_id:
                from .write import WriteWorkflow

                sub = WriteWorkflow()
                out = await sub.run(ctx)
                ctx.state["_sub_results"] = out.results or {}
            else:
                ctx.state["_sub_results"] = {
                    "action": "needs_manuscript",
                    "query": ctx.query,
                }


# ── helpers ───────────────────────────────────────────────────────


async def _save_pause_state(ctx: WorkflowContext) -> None:
    """Persist the pause snapshot so the runner and frontend can pick it up."""
    if ctx.store is None:
        return
    try:
        snapshot = {
            "state": dict(ctx.state),
            "checkpoint": ctx.state.get("_pause_checkpoint", ""),
            "prompt": ctx.state.get("_pause_prompt", ""),
            "prompt_data": ctx.state.get("_pause_prompt_data", {}),
            "stage": ctx.state.get("_pause_stage", ""),
            "budget": ctx.state.get("_pause_budget", {}),
        }
        await ctx.store.mark_paused(ctx.task_id, snapshot=snapshot)
    except Exception:
        pass


__all__ = ["AutoWorkflow"]
