"""AutoWorkflow — Agent-driven entry point. No hardcoded routing.

The Agent (LLM) decides what to do via tool calls:
- use_skill__<name> → load a skill's instructions
- mcp__* → call MCP tools
- <skill>__<script> → execute skill scripts
- read_file / write_file → interact with the bundle

No keyword-based intent classification. No forced workflow routing.
The Agent is fully autonomous within the tool and skill ecosystem.
"""

from __future__ import annotations

from typing import Any

from backend.core.events import Event, EventType

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput


class AutoWorkflow(BaseWorkflow):
    name = "auto"
    version = "0.2.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await self._chat(ctx)
        except Exception as exc:
            await ctx.emit(Event(EventType.TASK_END, data={"verdict": "error"}))
            return WorkflowOutput(
                task_id=ctx.task_id,
                verdict="error",
                trace=list(ctx.trace),
                budget=ctx.budget.snapshot(),
                error=f"{type(exc).__name__}: {exc}",
            )

        if ctx.state.get("_paused"):
            return WorkflowOutput(
                task_id=ctx.task_id,
                verdict="waiting",
                results={
                    "stage": ctx.state.get("_pause_stage", ""),
                    "prompt": ctx.state.get("_pause_prompt", ""),
                    "checkpoint": ctx.state.get("_pause_checkpoint", ""),
                    "prompt_data": ctx.state.get("_pause_prompt_data", {}),
                },
                trace=list(ctx.trace),
                budget=ctx.budget.snapshot(),
            )

        sub_results = ctx.state.get("_sub_results", {})
        await ctx.emit(Event(EventType.TASK_END, data={"verdict": "ok"}))
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results=sub_results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    async def _chat(self, ctx: WorkflowContext) -> None:
        """Multi-round tool-calling with progressive skill disclosure
        and 4-layer context management (Claude Code model)."""
        from backend.core.context.conversation import ConversationContext
        from backend.core.llm.base import ChatMessage, ToolSpec

        if ctx.llm is None:
            ctx.state["_sub_results"] = {"answer": "LLM not configured.", "intent": "chat"}
            return

        # Agent decides everything. Skills are registered as individual
        # `use_skill__<name>` tools — just like Claude Code. The LLM sees
        # each skill as a separate callable function with its description.
        # No pre-matching, no ranking, no injection.
        intent = "general"
        skill_summary = _render_discovery_summary(ctx)
        system = _load_preset(ctx) or (
            "You are an autonomous academic assistant. "
            "Read the Available Skills list. When a skill matches the user's "
            "request, call `use_skill__<name>` to load its full instructions "
            "before executing. Synthesize results in the user's language."
        )
        if skill_summary:
            system += f"\n\n{skill_summary}"

        # Initialize 4-layer context
        conv = ConversationContext(
            system_messages=[ChatMessage(role="system", content=system)],
        )

        # Load history as full message chain (assistant + tool + reasoning)
        # — same model as Claude Code / ChatGPT: the LLM sees the complete
        # conversation including tool calls and their results.
        history = ctx.input.get("history", [])
        if isinstance(history, list):
            pending_tool_calls: set[str] = set()
            for h in history[-30:]:
                if not isinstance(h, dict):
                    continue
                role = str(h.get("role", ""))
                if role == "user":
                    conv.add_message(ChatMessage(role="user", content=str(h.get("content", ""))))
                elif role == "assistant":
                    tc_list = h.get("tool_calls")
                    tool_calls = None
                    if isinstance(tc_list, list) and tc_list:
                        tool_calls = [{"id": tc.get("id", f"call_{i}"), "name": tc["name"], "arguments": tc.get("arguments", {})} for i, tc in enumerate(tc_list) if isinstance(tc, dict) and tc.get("name")]
                        tool_calls = tool_calls or None
                    msg = ChatMessage(role="assistant", content=str(h.get("content", "")))
                    if tool_calls:
                        msg.tool_calls = tool_calls
                        pending_tool_calls.update(tc["id"] for tc in tool_calls if tc.get("id"))
                    rc = h.get("reasoning_content")
                    if rc and isinstance(rc, str):
                        msg.reasoning_content = rc
                    conv.add_message(msg)
                elif role == "tool":
                    tool_call_id = str(h.get("tool_call_id", ""))
                    name = str(h.get("name", ""))
                    content = str(h.get("content", ""))
                    if tool_call_id and tool_call_id in pending_tool_calls:
                        conv.add_message(ChatMessage(
                            role="tool",
                            content=content,
                            tool_call_id=tool_call_id,
                            name=name,
                        ))
                        pending_tool_calls.discard(tool_call_id)
                    else:
                        summary = content[:200] + ("..." if len(content) > 200 else "")
                        if summary:
                            conv.add_message(ChatMessage(
                                role="assistant",
                                content=f"[Tool result: {name or 'unknown'}] {summary}",
                            ))
        parent_task_id = ctx.input.get("parent_task_id")
        if parent_task_id and not history:
            parent_answer = await _fetch_parent_answer(ctx, parent_task_id)
            if parent_answer:
                conv.add_message(ChatMessage(role="assistant", content=parent_answer))

        # Inject pre-read file content from runner (single/batch/project mode)
        pre_text = ctx.input.get("text", "")
        if pre_text and isinstance(pre_text, str) and pre_text.strip():
            max_pre = 10000
            truncated = pre_text[:max_pre]
            hint = f"\n(content truncated to {max_pre} chars)" if len(pre_text) > max_pre else ""
            conv.add_message(ChatMessage(role="system", content=f"The user has selected the following file(s) for you to analyze. Read and reference this content:\n\n{truncated}{hint}"))

        # Inject manuscript context for file editing
        ms_id = ctx.input.get("manuscript_id", "")
        edit_mode = ctx.input.get("edit_mode") is True
        if ms_id and isinstance(ms_id, str) and ms_id.strip():
            mode_note = (
                "EDIT MODE ACTIVE: You MUST call write_manuscript_file to apply changes. "
                "Reading files and describing changes is NOT sufficient — you must write the modified content back. "
                if edit_mode else
                "You have both read_file and write_manuscript_file available. "
            )
            conv.add_message(ChatMessage(
                role="system",
                content=(
                    f"{mode_note}"
                    f"Manuscript ID: '{ms_id}'. "
                    f"Use write_manuscript_file(manuscript_id='{ms_id}', path='...', content='...') to save changes."
                ),
            ))
        # Inject bundle_tree for project mode progressive reading
        bundle_tree = ctx.state.get("bundle_tree")
        if bundle_tree and isinstance(bundle_tree, list):
            tree_summary = "Available files in this manuscript:\n" + "\n".join(f"- {f.get('path','?')} ({f.get('size',0)}B)" for f in bundle_tree[:30])
            conv.add_message(ChatMessage(role="system", content=tree_summary))

        conv.add_message(ChatMessage(role="user", content=ctx.query))

        # Tool setup: each skill is an individual `use_skill__<name>` tool.
        # The LLM sees 24 skill tools, each with a name and description —
        # just like Claude Code. Base tools (arxiv, MCP, memory) always available.
        all_tools: list = _get_base_tools(ctx)
        # Register skills as individual tools (Claude Code pull mode)
        skill_tools = _get_discovery_tools(ctx)
        if skill_tools:
            all_tools.extend(skill_tools)
        # expand_tool_result — retrieves large offloaded tool results (Layer 4)
        all_tools.append(ToolSpec(
            name="expand_tool_result",
            description="Retrieve the full content of a large tool result that was offloaded. Use the reference ID shown in the tool result message (e.g. tool://call_XX).",
            parameters={"type": "object", "properties": {
                "tool_result_id": {"type": "string", "description": "The tool:// reference ID to expand"}
            }, "required": ["tool_result_id"]}
        ))
        # Store conv for tool handlers that need Layer 4 access
        ctx.state["_conv"] = conv

        max_rounds = 15
        final_answer = ""
        last_tool_result = ""
        last_intermediate_text = ""
        tool_call_log: list[dict] = []  # persisted for frontend post-completion display
        compaction_count = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for _round in range(max_rounds):
            # Auto-compact if over threshold (Layer 3)
            if conv.should_compact:
                await conv.compact(ctx.llm)
                compaction_count += 1

            messages = conv.build_messages()
            stream = await ctx.llm.complete(messages, tools=all_tools)
            text, tool_calls, usage, reasoning = await _collect_stream(stream)
            if usage:
                pt = getattr(usage, "prompt_tokens", 0) or 0
                ct = getattr(usage, "completion_tokens", 0) or 0
                total_prompt_tokens += pt
                total_completion_tokens += ct
                ctx.budget.accrue_llm(prompt_tokens=pt, completion_tokens=ct)
            # Emit LLM call trace for frontend transparency
            await ctx.emit(Event(EventType.LLM_CALL, data={
                "round": _round + 1,
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "tool_calls": [tc.name for tc in tool_calls] if tool_calls else [],
                "has_reasoning": bool(reasoning),
            }))

            # Only use text from the FINAL round (no more tool calls) as answer.
            # Intermediate text like "让我看看..." is not a useful answer.
            if not tool_calls:
                final_answer = text or final_answer
                break
            # Track last text for fallback (but prefer final round)
            if text:
                last_intermediate_text = text

            conv.add_message(ChatMessage(
                role="assistant", content=text,
                tool_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in tool_calls],
                reasoning_content=reasoning or None,
            ))

            for tc in tool_calls:
                # Deterministic kind classification for frontend icons
                _kind = "skill" if (tc.name.startswith("use_skill__") or tc.name == "use_skill") else \
                        "mcp" if tc.name.startswith("mcp__") else \
                        "file_read" if tc.name == "read_file" else \
                        "file_write" if tc.name in ("write_manuscript_file", "create_manuscript") else \
                        "memory" if tc.name in ("list_papers", "search_papers", "get_paper", "save_paper") else \
                        "tool"
                # Emit progress for transparency (frontend renders tool call cards)
                await ctx.emit(Event(EventType.TASK_PROGRESS, data={
                    "stage": "tool_call", "tool": tc.name, "args": tc.arguments,
                    "kind": _kind,
                }))
                result = await _handle_tool_call(ctx, tc)
                content = result.get("content", "")
                await ctx.emit(Event(EventType.TASK_PROGRESS, data={
                    "stage": "tool_result", "tool": tc.name,
                    "result_summary": content[:200] + ("..." if len(content) > 200 else ""),
                }))
                # Record for frontend post-completion display
                tool_call_log.append({
                    "id": tc.id,
                    "name": tc.name,
                    "kind": _kind,
                    "args": tc.arguments or {},
                    "result_summary": content[:200] + ("..." if len(content) > 200 else ""),
                })
                last_tool_result = result.get("content", "")[:500]
                # Layer 4: large tool results auto-offloaded by conv.add_message
                conv.add_message(ChatMessage(
                    role="tool", content=result.get("content", ""),
                    tool_call_id=tc.id, name=tc.name,
                ))
                # Layer 2: add sub-tools on skill activation
                new_tools = result.get("tools", [])
                for nt in new_tools:
                    if not any(t.name == nt["name"] for t in all_tools):
                        all_tools.append(ToolSpec(**nt))

        # Extract manuscript_id from create_manuscript tool calls
        manuscript_id = ""
        for msg in conv.messages:
            if msg.role == "tool" and msg.tool_call_id:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if "Manuscript created: id=" in content:
                    try:
                        manuscript_id = content.split("id=")[1].split(",")[0].strip()
                    except Exception:
                        pass

        # Collect reasoning from all rounds for frontend display
        all_reasoning: list[str] = []
        for msg in conv.messages:
            if msg.role == "assistant" and msg.reasoning_content:
                all_reasoning.append(msg.reasoning_content)

        # edit_mode enforcement: must call write_manuscript_file
        if edit_mode:
            wrote = any(tc.get("name") == "write_manuscript_file" for tc in tool_call_log)
            if not wrote:
                await ctx.emit(Event(EventType.TASK_WARNING, data={
                    "message": "Edit mode required write_manuscript_file but none was called.",
                }))
                ctx.state["_sub_results"] = {
                    "answer": final_answer or "Edit mode requires file changes, but no write_manuscript_file call was made. The agent read files but did not apply any edits.",
                    "intent": "chat",
                    "manuscript_id": manuscript_id or None,
                    "reasoning": "\n\n".join(all_reasoning) if all_reasoning else None,
                    "tool_rounds": min(_round + 1, max_rounds),
                    "tool_calls": tool_call_log,
                    "files_written": [],
                    "edit_mode_failed": True,
                    "context_stats": {
                        "compactions": compaction_count,
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                    },
                }
                return

        # Active Clarification: if no tools were used and the answer
        # looks like a clarifying question, pause for user input.
        if not tool_call_log and final_answer and len(final_answer) < 300:
            clarification_markers = ("?","？","你想","你要","请问","哪个","哪种","怎么","如何",
                                    "还是","或者","确认","是否","提供","告诉我","指定","明确")
            if any(m in final_answer for m in clarification_markers):
                await ctx.emit(Event(EventType.TASK_AWAITING_INPUT, data={
                    "prompt": final_answer,
                    "stage": "clarification",
                }))
                ctx.state["_paused"] = True
                ctx.state["_pause_stage"] = "clarification"
                ctx.state["_pause_prompt"] = final_answer
                return

        # Batch mode stats: which files were written
        written_files: list[str] = []
        for tc in tool_call_log:
            if tc.get("name") == "write_manuscript_file":
                path = (tc.get("args") or {}).get("path", "")
                if path:
                    written_files.append(str(path).lstrip("./"))

        ctx.state["_sub_results"] = {
            "answer": final_answer or last_intermediate_text or last_tool_result or "Tools returned no results. The external services may be unavailable.",
            "intent": "chat",
            "manuscript_id": manuscript_id or None,
            "reasoning": "\n\n".join(all_reasoning) if all_reasoning else None,
            "tool_rounds": min(_round + 1, max_rounds),
            "tool_calls": tool_call_log,
            "files_written": written_files,
            "context_stats": {
                "compactions": compaction_count,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
            },
        }


# ── chat helpers ──────────────────────────────────────────────────


async def _fetch_parent_answer(ctx: WorkflowContext, parent_task_id: str) -> str | None:
    """Fetch the parent task's answer for conversation continuity."""
    if ctx.store is None:
        return None
    try:
        record = await ctx.store.get(parent_task_id)
        if record is None:
            return None
        result = record.result or {}
        return result.get("answer", "") or ""
    except Exception:
        return None


def _allowed_paths(ctx: WorkflowContext) -> set | None:
    """Return the set of allowed file paths based on the current mode.
    - Single file (bundle_target): only that file
    - Batch (bundle_targets): only those files
    - Project mode: None (all files allowed)
    - Default (no mode, no target): only bundle_target if set, else all"""
    mode = ctx.input.get("mode", "")
    if mode == "project":
        return None  # allow all
    targets = ctx.input.get("bundle_targets")
    if isinstance(targets, list) and targets:
        return set(str(t).lstrip("./") for t in targets)
    target = ctx.input.get("bundle_target")
    if target and isinstance(target, str) and target.strip():
        return {target.strip().lstrip("./")}
    # No explicit restrictions — but if a single file was preselected by the
    # runner, respect that
    runner_target = ctx.input.get("text")
    if runner_target and isinstance(runner_target, str):
        bt = ctx.input.get("bundle_target", "")
        if bt and isinstance(bt, str) and bt.strip():
            return {bt.strip().lstrip("./")}
    return None  # no restrictions


def _load_preset(ctx: WorkflowContext, name: str = "chat") -> str | None:
    """Load a system prompt preset from presets/<name>.md.
    Falls back to None if the file is missing — caller provides a minimal default."""
    import os
    repo_root = os.environ.get("AAF_REPO_ROOT", "")
    if not repo_root and ctx.skill_host is not None:
        repo_root = str(ctx.skill_host.skills_root.parent)
    if not repo_root:
        return None
    preset_path = os.path.join(repo_root, "presets", f"{name}.md")
    if os.path.isfile(preset_path):
        try:
            with open(preset_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return None


def _render_discovery_summary(ctx: WorkflowContext) -> str:
    """List ALL skills alphabetically with name + description.
    The LLM reads this list and decides which `use_skill` to call —
    no pre-matching, no ranking. Pure Claude Code pull mode."""
    if ctx.skill_host is None:
        return ""
    try:
        skills = ctx.skill_host.list_skills()
    except Exception:
        return ""
    if not skills:
        return ""

    ordered = sorted(skills, key=lambda s: s.name)

    lines = ["## Available Skills\n"]
    lines.append("Read the descriptions below. When a skill matches the user's request, call `use_skill` with its name to load full instructions.\n")
    for s in ordered:
        desc = (s.description or "No description")[:120]
        lines.append(f"- **{s.name}**: {desc}")
    return "\n".join(lines)

def _render_tool_summary(ctx):
    """List all available tools for the system prompt."""
    base = _get_base_tools(ctx)
    if not base:
        return "(No tools)"
    parts = []
    for t in base:
        desc = (t.description or '')[:120]
        parts.append(f'- **{t.name}**: {desc}')
    return chr(10).join(parts)



def _get_discovery_tools(ctx: WorkflowContext) -> list:
    """Layer 1: skill frontmatter as callable tools."""
    if ctx.skill_host is None:
        return []
    try:
        return ctx.skill_host.build_tools()
    except Exception:
        return []


def _get_base_tools(ctx: WorkflowContext) -> list:
    """Non-skill tools available to all chat turns."""
    from backend.core.llm.base import ToolSpec

    tools: list = []
    if ctx.tools is not None:
        try:
            tools.extend(ctx.tools.list_for_injection())
        except Exception:
            pass
    # Manuscript tools
    if ctx.manuscripts is not None:
        tools.append(ToolSpec(
            name="create_manuscript",
            description="Create a new manuscript. Always use kind='paper' for multi-file. Only call ONCE — do NOT retry with different kinds. After creation, use write_manuscript_file.",
            parameters={"type": "object", "properties": {
                "title": {"type": "string", "description": "Manuscript title"},
                "kind": {"type": "string", "description": "'bundle' (multi-file) or 'single'"}
            }, "required": ["title"]}
        ))
        if ctx.bundle_storage is not None:
            tools.append(ToolSpec(
                name="write_manuscript_file",
                description="Write/modify a file in the current manuscript. Use to apply edits directly. Do NOT call create_manuscript for existing manuscripts — use the manuscript_id from the conversation context.",
                parameters={"type": "object", "properties": {
                    "manuscript_id": {"type": "string", "description": "The manuscript ID (provided in context)"},
                    "path": {"type": "string", "description": "File path (e.g. 'main.tex', 'chapters/intro.tex')"},
                    "content": {"type": "string", "description": "File content (LaTeX, Markdown, or plain text)"}
                }, "required": ["manuscript_id", "path", "content"]}
            ))

    # Progressive memory tools (Level 1: lightweight, Level 2: full detail)
    if ctx.memory is not None:
        tools.extend([
            ToolSpec(
                name="list_papers",
                description="List all paper titles in your knowledge base. Returns paper_id and title. Use limit to control how many (default 50). For targeted retrieval, use search_papers instead.",
                parameters={"type": "object", "properties": {
                    "limit": {"type": "integer", "description": "Max results (default 50, max 100)"}
                }}
            ),
            ToolSpec(
                name="search_papers",
                description="Search your knowledge base by keyword. Returns paper_id, title, authors, year, venue, and tags. For full abstract/details, call get_paper with the paper_id.",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string", "description": "Keywords to search (e.g. 'transformer', 'RLHF', 'dark matter')"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"}
                }}
            ),
            ToolSpec(
                name="get_paper",
                description="Get full metadata for a specific paper by its paper_id. Returns title, authors, abstract, method, findings, tags, and URL. Call this after list_papers or search_papers to drill into a paper.",
                parameters={"type": "object", "properties": {
                    "paper_id": {"type": "string", "description": "The paper_id from list_papers or search_papers results"}
                }, "required": ["paper_id"]}
            ),
            ToolSpec(
                name="list_heuristics",
                description="Search learned strategies (heuristics) by keyword or domain. These are rules/patterns discovered from successful past runs. Use query for semantic matching, or domain to filter by area.",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string", "description": "Keywords to match against heuristic descriptions"},
                    "domain": {"type": "string", "description": "Filter by domain (e.g. 'research', 'writing')"}
                }}
            ),
            ToolSpec(
                name="list_reflections",
                description="Search task reflections (episodic memory) by keyword. Each reflection summarizes a past task run — what was learned, decisions made, outcomes. Use query to filter by topic.",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string", "description": "Keywords to filter reflections (e.g. 'research', 'error', 'summary')"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"}
                }}
            ),
        ])
    # Bundle file tools
    if ctx.bundle is not None:
        tools.append(ToolSpec(
            name="read_file",
            description="Read a file from the current manuscript bundle. Use to progressively explore a project.",
            parameters={"type": "object", "properties": {"path": {"type": "string", "description": "File path in bundle"}}, "required": ["path"]}
        ))
    # Memory write tool
    if ctx.memory is not None:
        tools.append(ToolSpec(
            name="save_paper",
            description="Save a research paper to your knowledge base. Use after finding papers via search.",
            parameters={"type": "object", "properties": {
                "title": {"type": "string"}, "paper_id": {"type": "string"},
                "authors": {"type": "array", "items": {"type": "string"}},
                "year": {"type": "integer"}, "venue": {"type": "string"},
                "abstract": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
                "url": {"type": "string"},
            }, "required": ["title"]}
        ))
    return tools


async def _handle_tool_call(ctx: WorkflowContext, tc) -> dict:
    """Route a tool call: skill activation or script execution."""
    name = tc.name
    args = tc.arguments or {}

    # Layer 2: skill activation (single 'use_skill' tool or legacy 'use_skill__<name>')
    if name == "use_skill":
        skill_name = args.get("name", "")
    elif name.startswith("use_skill__"):
        skill_name = name.replace("use_skill__", "", 1)
    else:
        skill_name = ""

    if skill_name:
        await ctx.emit(Event(EventType.SKILL_CALL, data={
            "skill": skill_name, "query": args.get("query", ""),
        }))
        try:
            activated = ctx.skill_host.activate_skill(skill_name)
            body = activated.get("body", f"Skill '{skill_name}' not found.")
            sub_tools = activated.get("tools", [])
            # Render sub-tools as ToolSpec dicts
            tool_dicts = [
                {"name": t.name, "description": t.description,
                 "parameters": t.parameters if hasattr(t, 'parameters') else {}}
                for t in sub_tools
            ]
            await ctx.emit(Event(EventType.SKILL_RESULT, data={
                "skill": skill_name, "sub_tools": [t["name"] for t in tool_dicts],
                "body_len": len(body),
            }))
            return {"content": body, "tools": tool_dicts}
        except Exception as e:
            await ctx.emit(Event(EventType.SKILL_RESULT, data={
                "skill": skill_name, "error": str(e),
            }))
            return {"content": f"Error loading skill '{skill_name}': {e}", "tools": []}

    # Layer 3: script execution (skill scripts only, NOT MCP tools)
    if "__" in name and not name.startswith("mcp__"):
        try:
            result = await ctx.skill_host.call_tool(
                name, args, task_id=ctx.task_id,
            )
            return {"content": f"Result (ok={result.ok}):\n{result.stdout or result.stderr or ''}"}
        except Exception as e:
            return {"content": f"Tool error: {e}"}

    # ── Progressive Memory Tools ───────────────────────────────────
    # Level 1: lightweight list/search → paper_id + title only
    # Level 2: get_paper → full metadata (abstract, method, findings)

    if name == "list_papers" and ctx.memory is not None:
        await ctx.emit(Event(EventType.MEMORY_READ, data={"tool": "list_papers", "limit": args.get("limit", 50)}))
        try:
            limit_val = min(int(args.get("limit", 50)), 100)
            cards = await ctx.memory.knowledge.list_all()
            total = len(cards)
            import json as _json
            titles = [{"paper_id": c.paper_id, "title": c.title or "(untitled)"} for c in cards[:limit_val]]
            hint = f"\n(Showing {len(titles)} of {total}. Use limit=N to see more, or search_papers(query=...) for semantic search.)" if total > limit_val else ""
            return {"content": f"Total papers: {total}.\n{_json.dumps(titles, ensure_ascii=False, indent=2)}{hint}"}
        except Exception as e:
            return {"content": f"Error: {e}"}

    if name == "search_papers" and ctx.memory is not None:
        await ctx.emit(Event(EventType.MEMORY_READ, data={"tool": "search_papers", "query": args.get("query", "")[:100]}))
        try:
            query = args.get("query", "")
            limit_val = min(int(args.get("limit", 10)), 20)
            import json as _json
            if query:
                # Semantic/vector search
                try:
                    cards = await ctx.memory.knowledge.find_related(query, k=limit_val)
                except Exception:
                    # Fallback: keyword search
                    q = query.lower()
                    all_cards = await ctx.memory.knowledge.list_all()
                    cards = [c for c in all_cards if
                             q in (c.title or "").lower() or
                             q in (c.abstract or "").lower() or
                             any(q in t.lower() for t in (c.tags or []))]
                    cards = cards[:limit_val]
            else:
                cards = (await ctx.memory.knowledge.list_all())[:limit_val]
            results = [{"paper_id": c.paper_id, "title": c.title or "(untitled)",
                        "authors": c.authors[:3] if c.authors else [],
                        "year": c.year, "venue": c.venue or "", "tags": c.tags or []}
                       for c in cards]
            return {"content": f"Found {len(results)} papers:\n{_json.dumps(results, ensure_ascii=False, indent=2)}\nUse get_paper(id) for full details."}
        except Exception as e:
            return {"content": f"Error: {e}"}

    if name == "get_paper" and ctx.memory is not None:
        try:
            pid = args.get("paper_id", "")
            card = await ctx.memory.knowledge.get(pid)
            if card is None: return {"content": f"Paper '{pid}' not found."}
            import json as _json
            return {"content": _json.dumps({
                "paper_id": card.paper_id, "title": card.title, "authors": card.authors,
                "year": card.year, "venue": card.venue, "abstract": (card.abstract or "")[:600],
                "method": (card.method or "")[:400], "findings": (card.findings or "")[:400],
                "tags": card.tags, "url": card.url,
            }, ensure_ascii=False, indent=2)}
        except Exception as e:
            return {"content": f"Error: {e}"}

    if name == "read_file" and ctx.bundle is not None:
        try:
            path = args.get("path", "").lstrip("./")
            if not path:
                return {"content": "Error: path required"}
            # Access control — restrict to selected files in single/batch mode
            allowed = _allowed_paths(ctx)
            if allowed is not None and path not in allowed:
                return {"content": f"Access denied: '{path}' is not in the selected file scope. Allowed: {', '.join(sorted(allowed)[:10])}"}
            content = await ctx.bundle.read_text(path)
            max_chars = 30000
            truncated = content[:max_chars]
            hint = f"\n(truncated to {max_chars} chars)" if len(content) > max_chars else ""
            return {"content": f"File: {path}\n\n{truncated}{hint}"}
        except Exception as e:
            return {"content": f"Error reading {args.get('path','?')}: {e}"}

    if name == "save_paper" and ctx.memory is not None:
        try:
            from backend.memory.models import PaperCard
            from backend.memory.base import stable_id
            title = args.get("title", "Untitled")
            paper_id = args.get("paper_id") or stable_id("agent", title)
            card = PaperCard(
                paper_id=paper_id,
                title=title,
                authors=args.get("authors", []),
                year=args.get("year"),
                venue=args.get("venue", ""),
                abstract=args.get("abstract", ""),
                summary=args.get("summary", ""),
                method=args.get("method", ""),
                findings=args.get("findings", ""),
                tags=args.get("tags", []),
                url=args.get("url", ""),
                citation_url=args.get("citation_url", ""),
                source_run_id=ctx.task_id,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
            )
            await ctx.memory.knowledge.write_card(card)
            try:
                await ctx.memory.vector.add(
                    doc_id=card.paper_id,
                    text=card.search_text(),
                    metadata={"title": card.title, "year": str(card.year or ""), "source_run_id": card.source_run_id or ""},
                )
            except Exception:
                pass
            return {"content": f"Paper saved: id={card.paper_id}, title='{card.title}'"}
        except Exception as e:
            return {"content": f"Error saving paper: {e}"}

    if name == "write_manuscript_file" and ctx.manuscripts is not None:
        try:
            ms_id = args.get("manuscript_id", "")
            filepath = args.get("path", "main.tex").lstrip("./")
            content = args.get("content", "")
            if not ms_id or not content:
                return {"content": "Error: manuscript_id and content are required"}
            allowed = _allowed_paths(ctx)
            if allowed is not None and filepath not in allowed:
                return {"content": f"Access denied: '{filepath}' is not in the selected file scope. Allowed: {', '.join(sorted(allowed)[:10])}"}
            storage = ctx.bundle_storage
            if storage is None:
                return {"content": "Error: bundle storage not available"}
            manuscript = await ctx.manuscripts.get(ms_id)
            if manuscript is None:
                return {"content": f"Error: manuscript {ms_id} not found"}
            await storage.write_text(manuscript, filepath, content)
            return {"content": f"File written: {filepath} in manuscript {ms_id}"}
        except Exception as e:
            return {"content": f"Error writing file: {e}"}

    if name == "create_manuscript" and ctx.manuscripts is not None:
        try:
            title = args.get("title", ctx.query[:80])
            raw_kind = (args.get("kind") or "paper").lower()
            # Normalize to valid ManuscriptKind: paper, section, outline, note
            KINDS = {"paper": "paper", "bundle": "paper", "multi": "paper", "project": "paper",
                     "section": "section", "single": "section", "file": "section",
                     "outline": "outline", "note": "note"}
            kind = KINDS.get(raw_kind, "paper")
            from backend.manuscripts.models import CreateManuscriptInput
            body = CreateManuscriptInput(
                title=title, kind=kind, status="draft", layout="bundle",
                user_id=ctx.user_id, session_id=ctx.session_id,
            )
            manuscript, _version = await ctx.manuscripts.create(body)
            return {"content": f"Manuscript created: id={manuscript.id}, title='{title}', kind={kind}. Next: use write_manuscript_file to add content files."}
        except Exception as e:
            return {"content": f"Error creating manuscript: {e}"}

    if name == "list_reflections" and ctx.memory is not None:
        try:
            query = args.get("query", "")
            limit_val = min(int(args.get("limit", 10)), 20)
            # Get recent N, then filter by keyword if query provided
            reflections = await ctx.memory.episodic.recent(n=limit_val * 3 if query else limit_val)
            if query and reflections:
                q = query.lower()
                reflections = [r for r in reflections if
                               q in str(getattr(r, 'content', r)).lower() or
                               q in str(getattr(r, 'type', '')).lower()]
                reflections = reflections[:limit_val]
            import json as _json
            results = []
            for r in (reflections or [])[:limit_val]:
                d = {"id": getattr(r, 'id', ''), "type": getattr(r, 'type', ''),
                     "summary": str(getattr(r, 'content', r))[:300],
                     "session_id": getattr(r, 'session_id', ''),
                     "created_at": str(getattr(r, 'created_at', ''))}
                results.append(d)
            return {"content": f"Found {len(results)} reflections:\n{_json.dumps(results, ensure_ascii=False, indent=2)}"}
        except Exception as e:
            return {"content": f"Error: {e}"}

    if name == "list_heuristics" and ctx.memory is not None:
        try:
            query = args.get("query", "")
            domain = args.get("domain", "")
            if query:
                # Semantic match against query
                items = await ctx.memory.heuristic.match(query, top_k=10)
            elif domain:
                items = await ctx.memory.heuristic.list_by_domain(domain)
            else:
                items = await ctx.memory.heuristic.match(ctx.query, top_k=10)
            import json as _json
            results = [{"name": h.name, "description": (h.description or "")[:200], "domain": h.domain}
                       for h in (items or [])[:10]]
            return {"content": f"Found {len(results)} heuristics:\n{_json.dumps(results, ensure_ascii=False, indent=2)}"}
        except Exception as e:
            return {"content": f"Error: {e}"}

    # ── End memory tools ──────────────────────────────────────────

    # Fallback: try regular tool registry
    if ctx.tools is not None:
        try:
            result = await ctx.tools.call(name, args)
            import json as _json
            if not result.ok:
                err = result.error or "unknown error"
                return {"content": f"Tool '{name}' FAILED: {err}. Do NOT retry this tool — try a different one or tell the user."}
            data = result.data or {}
            if not data or data == {}:
                return {"content": f"Tool '{name}' returned no results. Try a different tool."}
            if name.startswith("mcp__") and isinstance(data.get("text"), str) and data["text"].strip():
                return {"content": f"Results from {name}:\n{data['text'][:3000]}"}
            return {"content": _json.dumps(data, ensure_ascii=False)}
        except Exception as e:
            return {"content": f"Tool '{name}' CRASHED: {e}. Try an alternative tool."}

    names = []
    if ctx.tools is not None:
        try: names = ctx.tools.names()[:20]
        except: pass
    # Layer 4: expand_tool_result — retrieve offloaded large tool results
    if name == "expand_tool_result":
        conv = ctx.state.get("_conv")
        if conv is not None:
            ref = args.get("tool_result_id", "")
            full = conv.expand_tool_result(ref)
            if full:
                return {"content": full[:10000]}
            return {"content": f"Tool result '{ref}' not found or already expired."}
        return {"content": "Error: conversation context not available."}

    return {"content": f"Unknown tool: {name}. Available tools: {', '.join(names) if names else 'none registered'}"}


async def _collect_stream(stream) -> tuple[str, list, dict | None, str]:
    """Drain the LLM stream and return (text, tool_calls, usage, reasoning)."""
    from backend.core.llm.base import ToolCall
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    usage = None
    reasoning = ""
    async for chunk in stream:
        if chunk.type == "delta" and chunk.delta:
            text_parts.append(chunk.delta)
        elif chunk.type == "tool_call" and chunk.tool_call:
            tool_calls.append(chunk.tool_call)
        elif chunk.type == "done":
            usage = chunk.usage
            reasoning = chunk.reasoning_content or ""
        elif chunk.type == "error":
            raise Exception(chunk.error or "LLM stream error")
    return "".join(text_parts), tool_calls, usage, reasoning


__all__ = ["AutoWorkflow"]
