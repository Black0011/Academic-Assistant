# ruff: noqa: RUF001
# (Chinese full-width punctuation in the system/user prompt is *deliberate*
# — these are the strings the LLM sees, and we want native Chinese punctuation
# in Chinese-language prompts rather than ASCII look-alikes.)
"""ConsultWorkflow — talk to a paper without rewriting it.

This is the *read-only* sibling of :class:`RevisionWorkflow`. The user
asks a question ("does this abstract sound too AI?"), the Agent returns
a structured prose answer — observations, suggestions, citations — and
**never** mutates the manuscript. A separate revision turn (typically
launched as a follow-up via the chat UI) handles the actual rewrite
once the user confirms.

Why a new workflow instead of a flag on revision?

* Mental model: "answer a question" and "rewrite a file" are different
  contracts. Cramming both into one workflow's output schema makes the
  UI ambiguous (is ``revised`` empty because the agent declined to
  rewrite, or because it failed?). A dedicated workflow lets each output
  shape carry meaning.
* Bundle safety: ``consult`` cannot accidentally trigger the runner's
  bundle-write path because that path is keyed on workflow name. No
  "I just wanted to ask a question and the file got changed" surprises.
* Routing freedom: ``consult`` can route to the cheaper/faster model
  by default (analyzing is lighter than rewriting).

Input contract (via ``ctx.input``):

* ``query``         — the user's question. Pulled from ``ctx.query``
  primarily; falls back to ``input.query`` if a caller still uses the
  pre-1.0 shape.
* ``text``          — passage to discuss. **Required** unless a bundle
  pre-read populates it (handled by the runner — same shape as
  ``revision``).
* ``manuscript_id`` — optional, paired with ``bundle_target`` so the
  runner can pre-read the file from disk for free.
* ``bundle_target`` — relative path inside the manuscript bundle.
* ``section``       — display hint (passed through to the result).
* ``history``       — optional list of ``{"role": "user|assistant",
  "content": "..."}`` carrying prior chat turns. Used to keep
  multi-turn consults coherent. Capped at the most recent N entries
  to stay inside the context window.

Output::

    {
      "section":        "...",
      "original":       text being analysed,
      "analysis":       prose markdown answer from the LLM,
      "suggestions":    bullet points parsed out of `analysis` (best-
                        effort, used by the UI to highlight key asks),
      "citations":      [paper_ids referenced inside `analysis`],
      "papers":         [{paper_id, title}, ...] recall-time context,
    }

This workflow deliberately omits ``revised`` / ``change_log`` /
``comments_addressed`` — that's revision's job.
"""

from __future__ import annotations

import re
from typing import Any

from backend.core.context_manager import ContextBudget, ContextManager, estimate_tokens
from backend.core.events import Event, EventType
from backend.memory.models import PaperCard

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .citation_guard import audit_citations, auto_fix_suspects
from .primitives import sequential
from .write import _CITE_RE, _ask, _format_papers

_CONSULT_SYSTEM = (
    "你是一位严谨、健谈的资深学术 reviewer。用户会带着一段文本和具体问题来找你。\n"
    "你的输出必须是**分析性回答**：观察、判断、改进建议，必要时给出例句。\n"
    "**绝对不要**把整段文字重新写一遍当作回答 —— 那是另一个工作流（revision）的事。\n"
    "Markdown 输出，可使用列表与引用。若引用相关论文，仅使用提供的 paper_id 形如 [aaa111]。\n"
    "回答语言：始终使用中文回答，论文内容、专有名词、引用格式保留英文原文。"
)

_CONSULT_USER = (
    "## 用户问题 / User question\n{query}\n\n"
    "## 章节 / Section\n{section}\n\n"
    "## 待分析文本 / Passage\n---\n{text}\n---\n\n"
    "## 检索到的相关论文 / Relevant papers\n{papers}\n\n"
    "{history_block}"
)

_HISTORY_BLOCK_TEMPLATE = "## 此前对话 / Earlier turns\n{turns}\n\n"

# History window: keep the most recent N turns inside the prompt so we
# don't blow the context window on long chats. Older turns still live
# in the task thread and are visible to the user.
_HISTORY_MAX_TURNS = 8
_HISTORY_TURN_CHAR_CAP = 600

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*(.+?)\s*$")


class ConsultWorkflow(BaseWorkflow):
    """Answer questions about a passage without rewriting it.

    Stages: ``validate → recall → consult → reflect``. Each LLM step
    has a template fallback so the workflow stays runnable when no key
    is wired (matches the rest of the framework).
    """

    name = "consult"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(
                ctx,
                [self._validate, self._audit_original, self._recall, self._consult, self._reflect],
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

        results: dict[str, Any] = {
            "section": ctx.input.get("section", ""),
            "original": ctx.state.get("original", ""),
            "analysis": ctx.state.get("analysis", ""),
            "suggestions": ctx.state.get("suggestions", []),
            "citations": sorted(ctx.state.get("citations", set())),
            "papers": [
                {"paper_id": p.paper_id, "title": p.title} for p in ctx.state.get("papers", [])
            ],
            # P14.1: suspect citations surfaced for user review
            "suspect_citations": ctx.state.get("suspect_citations", []),
        }
        await ctx.emit(
            Event(
                EventType.TASK_END,
                data={"verdict": "ok", "suggestions": len(results["suggestions"])},
            )
        )
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results=results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    # ---- stages ------------------------------------------------------

    async def _validate(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            text = (c.input.get("text") or "").strip()
            if not text:
                manuscript_id = c.input.get("manuscript_id") or ""
                bundle_target = c.input.get("bundle_target") or ""
                if manuscript_id and bundle_target:
                    raise ValueError(
                        "consult: target file is empty after pre-read "
                        f"(manuscript={manuscript_id}, bundle_target={bundle_target}). "
                        "Make sure the file exists and has content."
                    )
                if bundle_target and not manuscript_id:
                    raise ValueError(
                        "consult: bundle_target was set but manuscript_id is empty — "
                        "pick a manuscript first, or send raw input.text."
                    )
                if manuscript_id and not bundle_target:
                    raise ValueError(
                        "consult: manuscript_id was set but bundle_target is empty — "
                        "select a target file inside the bundle, or send input.text."
                    )
                raise ValueError(
                    "consult needs input.text, or input.manuscript_id + bundle_target."
                )
            if not (c.query or "").strip():
                raise ValueError(
                    "consult needs a non-empty query — what do you want to ask about this passage?"
                )
            c.state["original"] = text

        await self.stage(ctx, "validate", inner)

    async def _recall(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            # Safe default set *before* the risky call: if the snapshot
            # blows up (broken pipe, vector store offline, …) ``stage_soft``
            # swallows the exception and the workflow keeps running with
            # an empty papers list rather than aborting the whole task.
            c.state["papers"] = []
            if c.memory is None:
                return
            cue = f"{c.query or ''}\n{c.state.get('original', '')[:400]}".strip()
            snap = await c.memory.snapshot(
                cue,
                domain=c.input.get("domain", "consult"),
                k=int(c.input.get("recall_k") or 6),
                session_id=c.session_id,
            )
            c.state["papers"] = list(snap.related_papers)
            await c.emit(
                Event(
                    EventType.MEMORY_READ,
                    data={
                        "papers": len(snap.related_papers),
                        "doc_chunks": len(snap.doc_chunks),
                    },
                )
            )

        await self.stage_soft(ctx, "recall", inner)

    async def _audit_original(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            audit = await audit_citations(c, text=c.state.get("original", ""), stage="consult:original")
            c.state["_audit_original_suspect"] = list(audit.suspect_citations)

        await self.stage(ctx, "audit_original", inner)

    async def _consult(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            papers: list[PaperCard] = c.state.get("papers", [])
            raw_history = _normalise_history(c.input.get("history"))
            full_text = c.state.get("original", "")

            # P17: ContextManager for smart history + reference management.
            cm = ContextManager(llm=c.llm)
            history_text = await cm._prepare_history(raw_history, 16_000)
            ref_text = full_text
            ref_est = estimate_tokens(full_text)
            if ref_est > 28_000:
                ref_text = full_text[:28_000] + (
                    f"\n\n[... {ref_est - 28000} tokens omitted ...]"
                )
            budget = ContextBudget()
            budget.allocate_system(_CONSULT_SYSTEM)
            budget.allocate_history(history_text)
            budget.allocate_reference(ref_text)
            budget.allocate_query(c.query or "")

            analysis = ""
            llm_error: str | None = None
            if c.llm is not None:
                try:
                    analysis = await _ask(
                        c,
                        system=_CONSULT_SYSTEM,
                        user=_CONSULT_USER.format(
                            query=c.query or "(no question)",
                            section=c.input.get("section", "(unspecified)"),
                            text=ref_text,
                            papers=_format_papers(papers),
                            history_block=_format_history_text(history_text),
                        ),
                        route="fast",
                    )
                except Exception as exc:
                    llm_error = f"{type(exc).__name__}: {exc}"
                    await c.emit(
                        Event(
                            EventType.TASK_RETRY,
                            data={
                                "stage": "consult",
                                "fallback": "template",
                                "message": str(exc),
                                "budget_status": budget.status,
                            },
                        )
                    )
            if not analysis.strip():
                analysis = _template_analysis(
                    text=full_text, query=c.query or "", llm_error=llm_error,
                    truncated=budget.status in ("compact", "emergency"),
                )

            c.state["analysis"] = analysis.strip()
            audit = await audit_citations(c, text=c.state["analysis"], stage="consult:analysis")
            c.state["citations"] = audit.paper_ids
            # P14.1: merge suspect citations from both audit stages
            orig_suspect: list[dict[str, str]] = c.state.get("_audit_original_suspect", [])
            all_suspect = orig_suspect + list(audit.suspect_citations)
            # Deduplicate by key
            seen: set[str] = set()
            deduped: list[dict[str, str]] = []
            for s in all_suspect:
                if s["key"] not in seen:
                    seen.add(s["key"])
                    deduped.append(s)
            if deduped:
                deduped = await auto_fix_suspects(c, deduped)
            c.state["suspect_citations"] = deduped
            c.state["suggestions"] = _parse_suggestions(
                c.state["analysis"], suspect_citations=deduped,
            )

        await self.stage(ctx, "consult", inner)

    async def _reflect(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                return
            from backend.memory.paper_memory import PaperMemoryEvolver

            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            await evolver.write_session_reflection(
                task_id=c.task_id,
                query=c.query or "Consult",
                outcomes={
                    "verdict": "ok",
                    "kind": "consult",
                    "section": c.input.get("section", ""),
                    "suggestions_count": len(c.state.get("suggestions", [])),
                    "citations_count": len(c.state.get("citations", set())),
                },
                session_id=c.session_id,
                user_id=c.user_id,
            )
            await c.emit(Event(EventType.MEMORY_WRITE, data={"kind": "reflection"}))

        # Reflection is a "nice-to-have" memory write — if the episodic
        # store is offline we still want to hand the user their answer.
        # P12.1: soft-fail keeps that promise.
        await self.stage_soft(ctx, "reflect", inner)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_history(raw: Any) -> list[dict[str, str]]:
    """Coerce ``input.history`` into a safe list of role/content dicts.

    P17: the 600-char cap and 8-turn limit are REMOVED — ContextManager
    handles compaction intelligently instead of brute-force truncation.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        out.append({"role": role, "content": content})
    return out


def _format_history(history: list[dict[str, str]]) -> str:
    """Legacy formatter — now replaced by ContextManager._prepare_history.
    Kept for backward compatibility when no ContextManager is used."""
    if not history:
        return ""
    lines: list[str] = []
    for turn in history:
        prefix = "用户" if turn["role"] == "user" else "Agent"
        lines.append(f"- **{prefix}**: {turn['content']}")
    return _HISTORY_BLOCK_TEMPLATE.format(turns="\n".join(lines))


def _format_history_text(history_text: str) -> str:
    """Format ContextManager-compacted history into the prompt block."""
    if not history_text.strip():
        return ""
    return _HISTORY_BLOCK_TEMPLATE.format(turns=history_text)


def _parse_suggestions(
    text: str, *, suspect_citations: list[dict[str, str]] | None = None,
) -> list[str]:
    """Pull bullet-line suggestions from analysis prose, plus suspect citation fixes.

    Suspect citations are appended as actionable fix suggestions so the
    user can click to rewrite in revision mode.
    """
    items: list[str] = []
    for line in (text or "").splitlines():
        m = _BULLET_RE.match(line)
        if m:
            body = m.group(1).strip().strip("`*_")
            if body:
                items.append(body)

    # Append suspect citation fix actions
    if suspect_citations:
        for s in suspect_citations:
            key = s["key"]
            reason = s.get("reason", "missing citation")
            items.append(f"Fix citation [{key}]: {reason}")

    return items[:12]  # allow a few more for citation fixes


def _citations_in(text: str, papers: list[PaperCard]) -> set[str]:
    """Collect paper_ids the analysis actually cites, scoped to the
    supplied papers so hallucinated ids don't survive."""

    known = {p.paper_id for p in papers}
    cites: set[str] = set()
    for match in _CITE_RE.finditer(text or ""):
        # match.group(1) is the comma-separated id list inside [].
        for raw in match.group(1).split(","):
            cid = raw.strip()
            if cid in known:
                cites.add(cid)
    return cites


def _template_analysis(
    *,
    text: str,
    query: str,
    llm_error: str | None = None,
    truncated: bool = False,
) -> str:
    """Fallback when the LLM call fails or no LLM is wired.

    Returns a deterministic diagnostic message so callers can tell at a
    glance that the real model didn't respond. The shape still mirrors
    the live response so frontend rendering keeps working.
    """

    preview = (text or "").strip()
    if len(preview) > 300:
        preview = preview[:300].rstrip() + "…"

    reason = ""
    if llm_error:
        reason = f"\n**Reason**: `{llm_error}`\n"
    else:
        reason = "\n**Reason**: No LLM provider configured.\n"

    hints: list[str] = []
    if truncated:
        hints.append(f"The input text was truncated from {len(text or '')} to "
                     f"{len(preview)} chars to fit the context window. "
                     f"Try a more specific question, or select a single section "
                     f"instead of the whole project.")
    if llm_error and "context" in llm_error.lower():
        hints.append("Context window may be too small for the full paper. "
                     "Switch to single-file mode or ask a narrower question.")
    if llm_error and ("timeout" in llm_error.lower() or "TimedOut" in llm_error):
        hints.append("The LLM request timed out. The provider may be slow "
                     "or the input was too large to process in time.")
    hints.append("Switch to single-file mode for more reliable responses on "
                 "large papers, or use Peer Review for structured audit.")

    return (
        f"**[Template Fallback — LLM unavailable]**\n"
        f"{reason}\n"
        f"Question: {query or '(empty)'}\n\n"
        f"Input text: {len(text or '')} chars"
        f"{' (truncated for LLM call)' if truncated else ''}\n\n"
        f"> {preview}\n\n"
        + "\n".join(f"- {h}" for h in hints) + "\n"
    )


__all__ = ["ConsultWorkflow"]
