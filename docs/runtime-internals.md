# Runtime Internals — Architecture & Design Reference

> **Scope.** This document is the canonical reference for *how the moving
> parts cooperate at runtime*: context management, conversation
> isolation, prompt assembly, the provider stack, memory access patterns,
> self-evolution, observability. It complements
> [`docs/architecture.md`](architecture.md) (which is the static
> subsystem map) — when you change one, update the other in the same PR.
>
> **Source-of-truth contract.** Every claim below is grounded in code.
> File paths use `path/to/file.py:Symbol` notation so the rationale stays
> traceable. When the code drifts from this document, **the code wins** —
> open a PR to bring the doc back in sync, then merge as one change.

---

## 0. One-page mental model

```
                           ┌──────────────── Browser ─────────────────┐
                           │  React 19 SPA · TanStack Query · SSE     │
                           └────────────────────┬─────────────────────┘
                                                │ HTTPS
                       ┌────────────────────────┴─────────────────────────┐
                       │                  FastAPI app                     │
                       │ POST /api/tasks  →  TaskStore.create + enqueue    │
                       │ GET  /api/tasks/{id}/stream  →  SSE replay+tail   │
                       └─────────┬─────────────────────────────┬──────────┘
                                 │ enqueue                     │ poll events
                                 ▼                             │
                    ┌──────────────────────┐                   │
                    │ TaskQueue            │                   │
                    │ InMemory  /  ARQ     │                   │
                    └──────────┬───────────┘                   │
                               │ pop                            │
                               ▼                                │
                    ┌──────────────────────┐                   │
                    │ execute_task(deps)   │                   │
                    │   build WorkflowCtx  │                   │
                    │   workflow.run(ctx)  │                   │
                    │   commit manuscript  │                   │
                    │   maybe Evolver      │                   │
                    └────┬───────┬────┬────┘                   │
                         │       │    │                         │
        ctx.llm ◀────────┘       │    └────▶ ctx.tools          │
        ctx.memory ◀─────────────┘                              │
                                                                │
   LLM provider chain (decorator stack, outer→inner):           │
   Compactor ─▶ Routing ─▶ _RouteTaggedProvider ─▶ Adapter      │
                                                                │
   Every adapter call pushes a Record into TelemetryRecorder ───┘
   Every workflow stage pushes an Event into TaskStore.events
```

Three things to remember:

1. **One task = one `WorkflowContext` = one isolated run.** Nothing in
   the framework holds cross-task mutable state outside the explicit
   stores (`TaskStore`, `MemoryBundle`, `TelemetryRecorder`).
2. **The provider is a decorator chain.** Compactor wraps Router wraps
   tagged route wraps adapter. Each layer is independently optional and
   independently testable. `for_route()` is propagated by every layer
   that doesn't own it.
3. **Disk is state, RAM is throwaway.** `task_id` and `source_run_id`
   are the only correlation keys that survive a process restart.

---

## 1. Request lifecycle — research workflow walkthrough

The cleanest way to internalise the runtime is to follow one HTTP
request from the browser to the SSE event stream. The same pattern
applies to every other workflow.

### 1.1 Step-by-step

| # | Layer | What happens | File |
|---|-------|--------------|------|
| 1 | Frontend | User clicks **Run** in `/research`; sends `POST /api/tasks` with `{workflow:"research", query, budget_usd}`. | `frontend/src/pages/ResearchConsolePage.tsx` |
| 2 | FastAPI | `create_task` validates the workflow exists; builds a `TaskRecord` (id, status=`queued`, query, input, budget, user_id, session_id); calls `TaskStore.create` then `TaskQueue.enqueue(task_id)`. Returns 202 with `task_id`. | `backend/api/routers/tasks.py:create_task` |
| 3 | Frontend | Reads back the `task_id` and opens `GET /api/tasks/{id}/stream` (SSE). | `frontend/src/hooks/useTaskStream.ts` |
| 4 | Queue | `InMemoryTaskQueue` pops the id and calls `execute_task(task_id, deps)` inside an `asyncio.create_task` (laptop mode). ARQ does the same in worker mode. | `backend/tasks/queue.py` · `backend/tasks/runner.py:execute_task` |
| 5 | Runner | Loads the `TaskRecord`, refuses if terminal, instantiates the workflow, builds a fresh `WorkflowContext` with: `task_id`, `query`, `input`, `user_id`, `session_id`, `llm`, `memory`, `tools`, `skill_host`, `Budget(max_cost_usd=...)`. Wires an event sink that does `store.append_event(task_id, event)`. Calls `store.mark_started(task_id)`. | `backend/tasks/runner.py:execute_task` |
| 6 | Workflow | `ResearchWorkflow.run(ctx)` runs six stages via `self.stage(ctx, name, fn)` — `recall → search → parse → ingest → evolve → reflect`. Each stage emits `task.stage_start` / `task.stage_end`. | `backend/workflows/research.py` · `backend/workflows/base.py:BaseWorkflow.stage` |
| 7 | Memory | `_recall` calls `ctx.memory.snapshot(query, domain="research", session_id=ctx.session_id)`. The snapshot pulls from `knowledge`, `vector`, `documents`, `heuristic`, and `episodic` in one fan-out. Returns a `MemorySnapshot`. | `backend/memory/base.py:MemoryBundle.snapshot` |
| 8 | Tools | `_search` calls `ctx.tools.call("arxiv__search", {...}, sink=...)`. The `ToolRegistry` enforces `allow_network` / `allow_paid_api`, emits `skill.call` / `skill.result`, translates exceptions into `ToolResult(ok=False)`. | `backend/tools/registry.py:ToolRegistry.call` |
| 9 | Tools | `_parse` runs `pdf__parse` for top N hits in parallel via `asyncio.gather`. | `backend/workflows/research.py:_parse` |
| 10 | Memory | `_ingest` builds a `PaperCard` per hit and writes via `ctx.memory.knowledge.write_card(card)` then mirrors the search text into `ctx.memory.vector.add(...)`. Each write carries `source_run_id = ctx.task_id`. Emits `memory.write`. | `backend/workflows/research.py:_ingest` |
| 11 | Memory | `_evolve` runs `PaperMemoryEvolver` to add typed links + tags. Idempotent — re-runs on the same input are a no-op. | `backend/memory/paper_memory.py` |
| 12 | LLM | `_reflect` calls `ctx.llm.complete([...])` (decorated chain — see §3) and writes one `Reflection` to `episodic`. Token usage from the `done` chunk is `ctx.budget.accrue_llm(...)`. | `backend/workflows/research.py:_reflect` |
| 13 | Runner | `workflow.run` returns `WorkflowOutput(verdict="ok", results, budget)`. Runner calls `_maybe_commit_manuscript` (no-op for research) then `_maybe_run_evolver` (writes a draft `Proposal` if `AAF_EVOLVER_ENABLED=true`). Finally `store.mark_completed(task_id, status="ok", result, budget)`. | `backend/tasks/runner.py:execute_task` |
| 14 | SSE | Each `store.append_event` increments a per-task `seq`. The `/stream` generator polls `store.events(task_id, after_seq=cursor)` every 50 ms while `running`, 200 ms while `queued`, exits cleanly when status is terminal and the buffer is drained. | `backend/api/routers/tasks.py:stream_events` |
| 15 | Frontend | `useTaskStream` projects the events onto `EventTimeline`; the right-hand panel auto-refreshes the `TaskRecord` once it sees a terminal event. | `frontend/src/components/research/EventTimeline.tsx` |

### 1.2 Synchronous variant (no queue)

For tests and the Research Console "preview" mode, `POST /api/workflows/{name}/run`
runs the workflow inline and returns the full `WorkflowOutput` as JSON.
SSE counterpart: `POST /api/workflows/{name}/stream` (no queue, no
durable event log — events live for the request).

See `backend/api/routers/workflows.py:run` and `:stream`. The SSE
variant uses an in-memory `asyncio.Queue` between the workflow driver
and the SSE generator instead of polling the durable store.

---

## 2. Conversation isolation

Five identifiers carry isolation through the system. Each has a
specific scope and lifetime; **never alias them**.

| Identifier | Scope | Lifetime | Set where | Read where |
|---|---|---|---|---|
| `user_id` | Per-account | Forever (until user deleted) | `auth.login` JWT subject; or anonymous synthetic id when `AUTH_DISABLED=true` | every router via `Depends(current_user)` |
| `session_id` | Per multi-turn chat | TTL'd in Redis (or in-memory) | `MemoryBundle.session.create(SessionContext(user_id=..., ...))` | passed to `WorkflowContext`; influences `memory.snapshot(session_id=...)` |
| `task_id` | One workflow run | Forever (durable in `TaskStore`) | `tasks.create_task` with `uuid.uuid4().hex` | `WorkflowContext.task_id`; primary key of every `TaskEventRecord` |
| `source_run_id` | All side-effects from one run | Forever (column on every memory row) | `task_id` is the canonical value (`run_id == task_id`); `paper ingest` uses `"ingest:<paper_id>"` | `MemoryBundle.rollback_run(run_id)` reverses every write tagged with it |
| `proposal_id` | One framework-change proposal | Forever | `ProposalStore.create` | `Proposal.proposal_id`; audit log `actor` |

### 2.1 What guarantees that two runs don't bleed into each other?

- **`WorkflowContext` is per-run.** It's a `dataclass`, freshly
  constructed by `execute_task` (or `_make_context` in the synchronous
  router) — see `backend/workflows/base.py:WorkflowContext` and
  `backend/tasks/runner.py:execute_task`. Nothing from a previous run
  reaches the new context.
- **Workflows are stateless classes.** `BaseWorkflow.run` only reads
  `ctx`. The workflow registry instantiates a *fresh* class per run via
  `WorkflowRegistry.instantiate(name)` — no module-level mutable state.
- **The 4 agents (Planner/Executor/Evaluator/Evolver) are stateless.**
  They take collaborators by argument; nothing is held on `self` between
  runs. See `backend/agents/evolver.py:EvolverAgent` and
  `.cursor/skills/aaf-agent-workflow/SKILL.md` §3.
- **Memory writes carry `source_run_id`.** Every `PaperCard`,
  `DocChunk`, `Reflection`, `SynthesisNote`, vector entry has the
  field. `POST /api/memory/rollback/{run_id}` reverses *only* what that
  run wrote. Other runs' data is untouched.
- **Telemetry records carry `task_id`.** Per-call cost / token attribution
  goes into `TelemetryRecorder` with `r.task_id`, so per-run reporting
  is just a filter — see `backend/core/llm/telemetry.py:Record`.
- **Soft delete keeps history honest.** Deletes go to `_trash/` for 30
  days (KnowledgeStore / DocumentStore / SkillAdmin all follow this).
  A run that thinks it deleted something can be inspected later without
  having to recover from backups.

### 2.2 Per-user data partitioning

`MemoryBundle.snapshot(query, domain, session_id, user_id)` filters at
the query layer. Stores keep `user_id` on every row that originated
from a workflow with a known user. A multi-tenant deployment must
therefore:

1. enable auth (`AUTH_DISABLED=false`),
2. ensure routers always pass `user_id` from `Depends(current_user)`
   into the `TaskRecord` and downstream into `ctx.user_id`,
3. ensure custom workflows propagate `c.user_id` into every
   `*.write_*` call site (the built-in workflows do this).

The default *single-user laptop preset* (`AUTH_DISABLED=true`) skips
all of this — there's only one user, so the partitioning columns are
present but constant.

### 2.3 Conversation history (SessionStore)

`MemoryBundle.session` is the multi-turn chat store. Workflows that
consume / produce conversational state read it via
`session.get(session_id)`, mutate it via
`session.append_message(session_id, SessionMessage(...))`. Default
backend is in-memory; production wires `RedisSessionStore` (Redis hash
+ TTL).

A session is **isolated** from the LLM call sequence — workflows decide
what slice of the session they want to feed into the prompt. There is
*no* global "current conversation" — every workflow constructs its
prompt explicitly from its own ingredients (see §4).

---

## 3. LLM provider stack (the decorator chain)

The single biggest insight about AAF's LLM layer: **it's a decorator
chain that wraps a single base adapter**, with `for_route()` propagated
through every layer that doesn't own it.

### 3.1 Build order (`backend/app.py:_build_llm`)

```
_build_llm(settings) returns:

   ┌────────── settings.autocompact_enabled? ────────────┐
   │                                                     │
   │  CompactingLLMProvider(                             │  outer-most
   │     inner=                                          │
   │     ┌────────── routing yaml exists? ───────────┐   │
   │     │                                            │   │
   │     │  RoutingLLMProvider(                       │   │
   │     │     default = adapter_for(default_route)   │   │
   │     │     routes  = { name: adapter_for(spec) }  │   │
   │     │  )                                         │   │
   │     │                                            │   │
   │     └─ else ─▶ adapter (openai / anthropic /     │   │
   │                ollama / mock)                    │   │
   │                                                     │
   │     threshold = settings.autocompact_threshold      │
   │     keep_recent_n = settings.autocompact_keep_recent_n
   │     summariser_route = settings.autocompact_summariser_route
   │  )                                                  │
   │                                                     │
   └─ else ─▶ (Routing or adapter)                       │
                                                         │
   embedder = _build_embedder(settings, llm)             │
     - "provider" → reuses chat llm                      │
     - "local"    → LocalSentenceTransformerEmbedder     │
                                                         ▼
   AppState.llm = compactor (or whichever is outermost)
   AppState.memory.embedder = embedder
   AppState.skill_host._matcher._embedder = embedder
```

### 3.2 Each layer's job

| Layer | File | Owns | Pass-through |
|---|---|---|---|
| `CompactingLLMProvider` | `backend/core/llm/compactor.py` | Token estimate, threshold check, recursion guard, summariser invocation | `embed`, `supports_*`, `context_window`, `estimate_cost`, `for_route` (delegates to inner) |
| `RoutingLLMProvider` | `backend/core/llm/router.py` | Multi-provider dictionary, `for_route(name) → _RouteTaggedProvider` | `complete` / `embed` delegate to **default** provider when called without `for_route` |
| `_RouteTaggedProvider` | `backend/core/llm/router.py` | Sets `_ACTIVE_ROUTE` contextvar around inner call so adapter telemetry tags the record | All other Protocol methods delegate to inner |
| Adapter (`openai_compat` / `anthropic` / `ollama` / `mock`) | `backend/core/llm/openai_compat.py` etc. | Real HTTP via `httpx.AsyncClient`, stream parsing, error mapping, telemetry `record(...)` | n/a |

### 3.3 The `for_route()` propagation invariant

Workflows call `ctx.llm.for_route("reasoning")` to ask for a different
model on a specific call. Every wrapper that doesn't own routing must
forward to the inner provider — see
`CompactingLLMProvider.for_route` (`backend/core/llm/compactor.py:399`).
Result: a workflow can call `ctx.llm.for_route("reasoning").complete(...)`
without knowing or caring whether routing or compaction is active.

### 3.4 Telemetry tagging (active_route contextvar)

Adapters all emit `backend.core.llm.telemetry.record(provider=..., model=..., task_id=..., prompt_tokens=..., completion_tokens=..., cost_usd=..., error_code=...)` themselves — they don't know about routing. To
label those records with the workflow-declared route name *without*
changing every adapter, `_RouteTaggedProvider._tagged_stream` sets a
`contextvars.ContextVar` (`_ACTIVE_ROUTE`) around the inner `complete()`
call:

```
RoutingLLMProvider.for_route("reasoning") returns
  _RouteTaggedProvider(inner=routes["reasoning"], route="reasoning")

await tagged.complete(messages):
  set_active_route("reasoning") → token
  try:
    async for chunk in await inner.complete(messages):
      yield chunk
      # adapter's record(...) call inside this scope reads the
      # contextvar via active_route() and tags the record
  finally:
    reset_active_route(token)
```

`record(..., route=None)` consults `_ACTIVE_ROUTE.get()` as the default
— so an adapter that knows nothing about routing still produces
route-tagged records when called via `for_route(...)`. See
`backend/core/llm/telemetry.py:active_route` and `:record`.

---

## 4. Prompt assembly pipeline

This is where Harness Engineering's "Context Engineering" rubber meets
the road. AAF assembles each LLM prompt from up to **five** ingredients
in a fixed order. Workflows pick which ingredients to include — there
is no global system-prompt concatenator.

```
┌──────────────────────────────────────────────────────────────────────┐
│  ChatMessage[]  passed to ctx.llm.complete(...)                      │
│                                                                      │
│  [0] system  ── workflow base instructions (inline in workflow .py)  │
│  [1] system  ── injection_bundle.system_additions  (skills + heur)   │
│  [2] system  ── rule_engine.system_prompt(agent)   (L2 rules)        │
│  [3] system  ── (optional) compactor summary of older turns          │
│  [N] user    ── current task query + retrieved memory snippets       │
│  [N+1] tool  ── tool results (round-trip, tool-calling workflows)    │
└──────────────────────────────────────────────────────────────────────┘
                       │
                       ▼  tools list passed alongside:
        injection_bundle.tool_specs  ⊕  tool_registry.list_for_injection()
```

### 4.1 Where each piece comes from

| Position | Producer | When included |
|---|---|---|
| Workflow base prompt | hardcoded in the workflow file (see e.g. `_OUTLINE_SYSTEM`, `_DRAFT_SYSTEM` in `backend/workflows/write.py`) | always for that workflow |
| Skill injection | `SkillHost.select_and_inject(query, top_k, min_score, domain, heuristics)` returns `InjectionBundle` (`system_additions` + `tool_specs` + `script_index`) | when the workflow opts in by calling `select_and_inject` |
| Behaviour rules (L2) | `RuleEngine.system_prompt(agent)` stitches all `enforcement: "prompt"` rules whose scope matches `agent` (or `"all"`) | when the workflow opts in by calling `system_prompt` |
| Compactor summary | `CompactingLLMProvider` injects a `system` message in front of the recent tail when `estimate_message_tokens(messages) > window * threshold` | whenever the threshold trips |
| Memory snippets | workflow embeds `MemorySnapshot.related_papers / doc_chunks / heuristics` into the user message body | always, when memory is wired |

### 4.2 Skill injection — Loader → Matcher → Injector

This is the runtime guarantee for "progressive skill reading".

```
boot                                request                          per-LLM-call
─────                                ────────                         ─────────────
SkillLoader._scan_sync()             SkillHost.select_and_inject(query, top_k=3, ...)
  scans skills/*/SKILL.md              │
  parses frontmatter + body            ▼
  builds 24× SkillMeta             SkillMatcher.match(query, ...)
  → SkillRegistry                      │
                                       │  score = 0.4 * keyword_score +
                                       │          0.6 * cosine(query_vec, desc_vec)
                                       │  (description_vec lazily cached
                                       │   per skill, embedder = LLM.embed
                                       │   or LocalSentenceTransformerEmbedder)
                                       │
                                       ▼
                                   filter score ≥ min_score (0.3)
                                   keep top_k (3)
                                   exclusive: keep highest only
                                   fallback: builtin general-assistant
                                       │
                                       ▼
                                   SkillInjector.inject(matches, heuristics)
                                       │
                                       │  drop by ascending score until
                                       │  approx_tokens ≤ token_budget (8000)
                                       │
                                       ▼
                                   InjectionBundle(
                                     system_additions = "# Skills\n## 🧩 Skill: …",
                                     tool_specs = [ToolSpec(...) per script],
                                     script_index = {tool_name: Path},
                                     matched_skills = [str],
                                     truncated = bool
                                   )
                                       │
                                       ▼
                                   workflow concatenates into messages[0..n]
                                   passes tool_specs to ctx.llm.complete(tools=...)
```

**Invariant (tested in `backend/tests/integration/test_skill_progressive_load.py`):**
even though the Loader holds the body of every skill in process memory,
**only the matched skills' bodies enter `system_additions`**. With 24
real skills loaded, `top_k=3` gives a `system_additions` strictly
smaller than 40% of the all-bodies concatenation.

If you change `_render_system` / `_render_skill` in `injector.py`,
re-run those integration tests — the assertions will catch any leak of
unmatched bodies into the prompt. See
`.cursor/skills/aaf-skill-host/SKILL.md` §5.1 for the formal contract.

### 4.3 Tool exposure

Two sources of `ToolSpec` reach the LLM in tool-calling mode:

1. **Skill-derived tools** — every script in a matched skill becomes
   one `ToolSpec` named `{skill_name}__{script_stem}`. Description
   comes from the script's `# aaf:description` magic comment;
   parameters from `# aaf:args {...}`. The injector renders them into
   `injection_bundle.tool_specs` and the executor knows how to dispatch
   via `injection_bundle.script_index`. See
   `backend/core/skill_host/injector.py:_render_tools`.
2. **Registered tools** — `ToolRegistry.list_for_injection(allow_network=..., allow_paid_api=...)`
   returns the framework-level callables (arxiv search, pdf parse, MCP
   adapters) that survived the capability gate. The workflow merges
   both lists when building `tools=...`.

The LLM sees one flat tool list. Dispatch is uniform: a tool name with
`__` → skill-derived (route through `SkillHost.call_tool`); without
`__` (or a registered prefix like `mcp__server__`) → `ToolRegistry.call`.

---

## 5. Context management & auto-compaction

### 5.1 Token estimation

`backend/core/llm/compactor.py:estimate_message_tokens` is intentionally
crude (no `tiktoken` dep, no per-model tokenisation). The math:

```
total = Σ_messages (
  max(1, len(text) / 4)   # 4 chars ≈ 1 token, always at least 1
  + 4                     # role marker + delimiters
  + (len(tool_calls) * 16 if tool_calls else 0)
  + Σ_tool_calls max(1, len(repr(args)) / 4)
)
```

It's off by ±10% in practice — fine because the threshold default
(0.7) leaves plenty of headroom and the laptop profile uses 0.6.

### 5.2 Compaction trigger

```
CompactingLLMProvider.complete(messages):
  if _INSIDE_COMPACTION.get():           # recursion guard (the summariser
    return inner.complete(messages)      # itself calls complete() — skip)

  original = estimate_message_tokens(messages)
  window   = inner.context_window(model) or fallback_window  (8192)
  budget   = window * threshold          (default 0.7)

  if original ≤ budget:
    return inner.complete(messages)      # zero overhead, common case

  token = _INSIDE_COMPACTION.set(True)
  try:
    result = compact_messages(messages,
                              summariser = inner.for_route("fast")
                                           if available else inner,
                              keep_recent_n = 6)
  finally:
    _INSIDE_COMPACTION.reset(token)

  log.info("llm.compacted", model, window, threshold,
           original_tokens, compacted_tokens, dropped_messages)

  return inner.complete(result.compacted)
```

### 5.3 Compaction algorithm (`compact_messages`)

```
input:  [system, system, user, assistant, user, assistant, ..., user]

step 1: split → systems = all role=system
                non_system = the rest

step 2: if len(non_system) ≤ keep_recent_n:
          return input unchanged    # nothing to compact

step 3: middle = non_system[:-keep_recent_n]
        tail   = non_system[-keep_recent_n:]

step 4: summary_text = await summariser.complete([
          system: _SUMMARY_SYSTEM,    (≤200 words, third person, preserves
                                       facts/decisions/IDs/open questions/
                                       tool results; drops chitchat/thinking)
          user:   "Summarise the following conversation slice:" + middle
        ])

step 5: output = [
          *systems,                   # original system messages verbatim
          system: "[Compacted context — earlier portion of this conversation,
                   summarised by AAF auto-compactor; original N messages
                   collapsed into the paragraph below.]\n\n" + summary_text,
          *tail                       # most recent N messages verbatim
        ]
```

Why this shape:

- **Systems are never summarised.** Workflow base prompts, skill
  injections, rules — all the structural context — stay intact.
- **Tail is verbatim.** The most recent N messages preserve the model's
  ability to do exact turn-taking on the latest exchange.
- **Middle becomes one paragraph.** Reflects Anthropic's
  "context resets" idea (PLAN §16.5); cheaper than perfect compression
  and easier to reason about.
- **Summariser uses the cheap route.** `summariser_route="fast"` by
  default — compaction itself doesn't blow the budget.
- **Recursion guard.** `_INSIDE_COMPACTION` contextvar prevents the
  summariser's own `complete()` call from re-triggering compaction. See
  `backend/core/llm/compactor.py:_INSIDE_COMPACTION`.

### 5.4 Settings

| Env var | Default | Laptop | Offline |
|---|---|---|---|
| `AAF_AUTOCOMPACT_ENABLED` | `false` | `true` | `true` |
| `AAF_AUTOCOMPACT_THRESHOLD` | `0.7` | `0.7` | `0.6` |
| `AAF_AUTOCOMPACT_KEEP_RECENT_N` | `6` | `6` | `4` |
| `AAF_AUTOCOMPACT_SUMMARISER_ROUTE` | `fast` | `fast` | `fast` |

Fast route lookup: when the underlying provider is a
`RoutingLLMProvider`, the compactor calls `inner.for_route("fast")`.
When it's a single adapter, the compactor uses the same adapter for
the summariser call.

### 5.5 Budget vs context window — different concerns

Don't conflate them:

- **Context window** is a *per-call* model property
  (`provider.context_window(model)`), measured in tokens. Compactor
  guards it.
- **Budget** is a *per-task* economic limit, measured in dollars / total
  tokens / wallclock seconds. `WorkflowContext.budget` (a `Budget`
  dataclass) accrues every `chunk.usage` from `done` chunks and
  raises `BudgetExceededError` from `budget.assert_ok()` at the start
  of each stage. See `backend/core/budget.py:Budget`.

---

## 6. Memory subsystem — read & write patterns

### 6.1 The single read API: `MemoryBundle.snapshot`

```python
snap = await ctx.memory.snapshot(
    query=ctx.query,
    domain="research",          # filters heuristics by domain
    session_id=ctx.session_id,  # filters episodic by session
    user_id=ctx.user_id,        # filters per-user data
    k=8,                        # top-K for vector / docs / papers
)

# snap is a MemorySnapshot:
#   vector_summary      : str         — flat textual context, ≤1000 chars
#   related_papers      : list[PaperCard]
#   doc_chunks          : list[DocChunkHit]   (M7.3)
#   heuristics          : list[Heuristic]     (filtered by domain)
#   recent_reflections  : list[Reflection]    (filtered by session_id)
```

Workflows embed pieces of the snapshot into their user message; they do
**not** stream the whole snapshot blindly. Typical usage: titles and
1-line summaries from `related_papers`, top heuristic, latest
reflection — total budget ~500 tokens.

### 6.2 The 6 stores (M7.3 inclusive)

| Store | Default backend | Ownership | Mutator surface |
|---|---|---|---|
| `vector` | Chroma (laptop: in-memory) | embedded text fragments (papers, chunks, snippets) | `add(doc_id, text, metadata)` / `query(text, k, where)` / `delete(doc_id)` / `count()` |
| `knowledge` | YAML (1 file per `PaperCard`) | structured paper cards + synthesis notes; versioned | `write_card` / `find_related` / `link` / `write_synthesis` / `rollback_run` |
| `heuristic` | YAML (1 file per heuristic) | L3 learned strategies; freezable | `add` / `update` / `freeze` / `unfreeze` / `find_by_domain` |
| `episodic` | SQL (Postgres / SQLite) | append-only `Reflection` rows tied to `task_id` | `add_reflection` / `for_session` / `recent` |
| `session` | Redis (laptop: in-memory) | multi-turn chat contexts + messages | `create` / `get` / `append_message` / `list_for_user` |
| `documents` | YAML (`<root>/<doc_id>/{document.yaml, chunks.yaml}`) | RAG layer; chunks mirrored into `vector` | `write` / `search_chunks` / `delete` (cascades to vector) |

### 6.3 Hard write rules

These come from `.cursor/skills/aaf-memory-contract/SKILL.md` and are
mechanically enforced in tests — break one and the suite fails.

1. **Only via `MemoryBundle`.** Nothing under `backend/` outside
   `memory/` may import `chromadb` / `PyYAML` directly to read or write.
   The HTTP routers go through `state.memory.<store>`; workflows go
   through `ctx.memory.<store>`.
2. **Knowledge → vector ordering.** `bundle.knowledge.write_card(card)`
   first (durable), then `bundle.vector.add(card.paper_id, card.search_text(), metadata)`.
   A vector failure is logged but doesn't roll back the YAML write — a
   nightly job rebuilds the vector index from durable storage.
3. **Soft delete only.** `delete()` moves the row to `_trash/` (kept 30
   days). Hard purge is a separate admin op.
4. **`source_run_id` on every write.** Field is mandatory in the
   models; the runner sets it from `ctx.task_id`. Enables
   `MemoryBundle.rollback_run(run_id)` to reverse a single run cleanly.
5. **Document delete cascades.** `DocumentStore.delete(doc_id)` drops
   the YAML file *and* prunes every `vector` entry whose metadata
   carries that `doc_id`. The `vector.count()` invariant is the test
   probe.
6. **Audit logs.** Every store operation calls
   `log.info("memory.<store>.<op>", id=..., run_id=...)` for the SSE
   `memory.write` / `memory.read` events and for offline audit.

### 6.4 Why `documents` and `knowledge` coexist

- **`knowledge`** is for *cite-able, structured papers* — `PaperCard`
  has explicit `paper_id` (DOI / arXiv id), `authors`, `year`, `venue`,
  `summary`, `findings`, `tags`, `typed_links`. One row = one paper.
- **`documents`** is for *free-form RAG* — markdown notes, blog posts,
  PDF excerpts that aren't a "paper" in the academic sense. Chunked
  with heading-aware sliding window (atomic code fences / table rows).

`MemoryBundle.snapshot` queries both and dedupes by score — the
workflow gets one merged top-K list.

---

## 7. Skill Host pipeline

Four components, one façade. All public access goes through
`SkillHost` (`backend/core/skill_host/registry.py`); the four internals
should never be imported directly outside the package.

### 7.1 Loader

`SkillLoader.load_all()` runs once at boot (`backend/app.py:lifespan`
calls `await skill_host.load()`). It walks `skills/<name>/`, parses
each `SKILL.md` frontmatter (description, triggers, version, domain,
exclusive, network, requires) **and** the body. Scripts under
`<skill>/scripts/` get magic-comment metadata extraction (see
`ScriptMeta` model). Result lives in `SkillRegistry`, indexed by name,
with a generation counter that bumps on every mutation.

**Forward-compat seam:** unknown frontmatter keys go into
`SkillMeta.raw_meta` so v2.x extensions don't break parsing. Loader
**never raises** — malformed SKILL.md is logged + skipped so a single
bad file can't break boot.

### 7.2 Matcher

`SkillMatcher.match(query, top_k, min_score, domain)` scores every
skill in the registry:

```
score = 0.4 * keyword_score  +  0.6 * semantic_score

keyword_score  = (# of triggers whose tokens are all in query+context)
                 / len(triggers)
                 (or fraction-of-description-overlap if no triggers)

semantic_score = cosine(query_embedding, description_embedding)
                 mapped from [-1, 1] → [0, 1]
                 (description embeddings cached per generation)
```

If the embedder is unavailable or fails, the matcher silently degrades
to pure keyword scoring (`_embed_disabled = True`). Top-K results are
filtered by `min_score=0.3`; `exclusive` skills suppress lower-scoring
exclusive collisions; if nothing passes, a `general-assistant` builtin
fallback is returned.

### 7.3 Injector

`SkillInjector.inject(matches, heuristics)` renders the kept matches
into `system_additions` markdown plus a `tool_specs` list. **The
injector is the only place where skill bodies enter the LLM prompt** —
this is the runtime contract for "progressive injection" (§4.2).

Token budget: if the rendered bundle exceeds `token_budget` (default
8000), skills are dropped in *ascending* score order until it fits;
`log.info("skill.injector.truncated", dropped=..., kept=...)` fires.

### 7.4 Executor

`SkillExecutor.run(script_path, args, tool_name, task_id, timeout_s, uses_llm)`
spawns the script in a sandboxed working directory under
`AAF_SKILL_WORKDIR_ROOT/<task_id>/<tool_name>/`, captures stdout /
stderr / artifacts, enforces the timeout, returns an `ExecResult`. Calls
to the executor are recorded in `SkillInvocationStore` so the
`/api/v1/skills/{name}/invocations` endpoint can show recent history.

### 7.5 SkillAdmin (mutating surface)

`backend/api/routers/skills.py` mounts the install / update / disable /
enable / reload / dry-run endpoints. They go through `SkillAdmin` which
implements **staging dir → atomic mv → reload** semantics: writes land
in `_staging/<name>/`, get fsync-ed, then `os.replace()` swaps them in.
Failure leaves the active skill untouched. Disabled skills move to
`_disabled/` (soft delete).

---

## 8. Self-evolution chain

```
workflow run                      runner                         proposals
  succeeds                          │                                │
  verdict="ok"                      │                                │
  ─────────────▶                  if AAF_EVOLVER_ENABLED              │
  WorkflowOutput                  and proposals != None               │
  results / budget                  │                                │
                                    ▼                                │
                            EvolverAgent.evolve_from_run(            │
                              record=TaskRecord,                     │
                              output=WorkflowOutput,                 │
                              store=ProposalStore                    │
                            )                                        │
                                    │                                │
                                    │  - drafts heuristic via        │
                                    │    LLM (route="reasoning")     │
                                    │    OR a deterministic template │
                                    │  - never raises (returns None) │
                                    │                                │
                                    ▼                                ▼
                              CreateProposalInput           ProposalStore.create
                              (kind="heuristic",            → status=draft
                               diff=YAML body,              → audit log {action:create}
                               risk="low",                  → returns Proposal
                               proposer_id=
                                 "evolver:<task_id>")
                                    │
                                    ▼
                              log.info("task.runner.evolver_proposal",
                                       task_id, workflow, proposal_id)


human review (frontend `/proposals`):
  POST /api/proposals/{id}:submit    draft     → pending
  POST /api/proposals/{id}:approve   pending   → approved   (admin)
  POST /api/proposals/{id}:apply     approved  → applied    (admin)
  POST /api/proposals/{id}:reject    pending   → rejected
  POST /api/proposals/{id}:withdraw  any       → withdrawn
  illegal transition                 → 409 IllegalTransitionError
```

**Critical invariant:** `:apply` *only stamps status* and writes an
audit event. It **does not touch any file on disk**. The diff field
carries the change; humans / CI consume it. A future `apply_strategy:
"skill_admin"` will dispatch to `SkillAdmin` for skill-scoped
proposals, reusing the staging / atomic / rollback path.

Why this gating exists: an LLM-written proposal can't suddenly mutate
`backend/`. Reviewability + safety + composability with the existing
`SkillAdmin` (M7.2) skill-edit pipeline.

See `backend/proposals/AGENTS.md` for the state machine table.

---

## 9. Telemetry & observability

Two parallel signal streams; both are first-class.

### 9.1 LLM telemetry — `TelemetryRecorder`

In-process ring buffer (default 1000 records). Every adapter calls
`record(provider, model, task_id, prompt_tokens, completion_tokens,
duration_ms, cost_usd, error_code, route)` after each completion. The
route is auto-filled from the `_ACTIVE_ROUTE` contextvar when omitted.

Surfaces:

- `GET /api/v1/models/usage` — totals + per-`(provider, model, route)`
  breakdown, optional `?route=reasoning` filter
- `GET /api/v1/models/routes` — currently configured routes (read from
  `RoutingLLMProvider.route_names()` when present)

> **Known prefix inconsistency.** Most routers use `/api/<resource>`
> (`/api/proposals`, `/api/skills`, `/api/planner`, `/api/manuscripts`,
> …), but `mcp` and `models` use `/api/v1/<resource>`. New routers should
> follow the **`/api/<resource>`** convention; the two `v1` prefixes
> stay for backward compatibility until a deliberate rename PR.
> Verified by the demo run on 2026-05-10 — see Change Log.

The frontend `Settings` page renders both as a table + chart so cost
attribution is one click away.

### 9.2 Workflow event log — `TaskStore.events`

Per-task, append-only, ordered by `seq` (1-based). Every meaningful
side-effect is one event:

| Event type | Producer | When |
|---|---|---|
| `task.start` | `WorkflowContext.emit` from workflow `run()` | first emit per run |
| `task.stage_start` / `task.stage_end` | `BaseWorkflow.stage` context manager | every named stage |
| `task.error` | `BaseWorkflow.stage` on exception, runner on crash | failure paths |
| `task.retry` | `DAGExecutor` between retry attempts | DAG node retry |
| `task.checkpoint` | `WorkflowContext.checkpoint` when enabled | per-stage if checkpointing on |
| `task.end` | workflow `run()` final emit | always (verdict in `data`) |
| `llm.call` / `llm.token` | adapters (planned — currently aggregated via budget) | per LLM call |
| `skill.matched` | `SkillMatcher` | per `select_and_inject` call |
| `skill.call` / `skill.result` | `ToolRegistry.call` | per tool invocation |
| `memory.read` / `memory.write` / `memory.rollback` | workflow stages on `ctx.memory` ops | per memory op |
| `rule.block` | `RuleEngine.pre_action` Block result | per blocked action |

Two transports for the same log:

- `GET /api/tasks/{id}/events?after_seq=N` — polling, returns up to
  200 records and the `next_after_seq` cursor
- `GET /api/tasks/{id}/stream` — SSE; replays from `after_seq=0` then
  tails (50 ms while running, 200 ms while queued, exits cleanly when
  terminal + buffer drained, safety timeout after 10 min idle)

The frontend `useTaskStream` hook chooses SSE; it groups events by
stage in `EventTimeline` and refreshes the cached `TaskRecord` on
terminal events.

### 9.3 Structured logging

`structlog` everywhere. Convention: dotted event names like
`memory.knowledge.write_card`, `skill.matcher.embed_failed`,
`task.runner.evolver_proposal`. Routers configure logging via
`_configure_logging(settings.log_level)` at lifespan start. JSON logs
in production (via env), pretty-printed in dev.

---

## 10. Settings & deployment profiles

`backend/settings.py:Settings` is a `pydantic.BaseSettings` with an
`alias` per field that maps to the `AAF_*` env var. Three things make
this layer non-leaky:

1. **Single source of config truth.** Routers / workflows read from
   `state.settings`, never `os.environ` directly.
2. **`memory_config()` returns a fully-resolved `MemoryConfig`** that
   `MemoryFactory.build()` consumes. Backends pick themselves based on
   `MEMORY_VECTOR_BACKEND` etc. — no special-case branches in the apps.
3. **Three official profiles**, all `.example` templates committed:

| Profile | Env file | Storage | Auth | Compaction | Use case |
|---|---|---|---|---|---|
| Production | `.env.example` | Postgres + Redis + Chroma | enabled | off | server deploy via `docker-compose.yml` |
| Laptop | `.env.laptop.example` | SQLite + in-memory queue + in-memory vector | disabled | on (0.7) | personal laptop via `make dev-laptop` or `docker-compose.lite.yml` |
| Offline | `.env.offline.example` | same as laptop | disabled | on (0.6) | Ollama chat + local sentence-transformers embedder; zero outbound API calls |

See `docs/laptop-mode.md` for the full setup walkthrough of the latter
two.

### 10.1 Runtime LLM provider override (frontend Settings panel)

Env-driven config covers servers and CI. For the laptop preset we also
support **runtime overrides** written by the frontend Settings panel —
no dotfile edits, no restart. The override is a single YAML file:

```
data/runtime/provider.yaml
```

Owned by `backend/core/runtime_config.py:RuntimeConfigStore`:

* **File format.** Plaintext YAML with the four user-editable fields
  (`provider`, `api_key`, `base_url`, `default_model`, `timeout_s`).
* **Permissions.** Directory `0700`, file `0600`, set on every save.
  `data/runtime/` is gitignored (`.keep` marker preserves the dir).
* **Atomic write.** Write to `provider.yaml.tmp` then `os.replace` —
  partial writes can never produce an unreadable file.
* **Tolerant load.** Missing / corrupt / wrong-shape file ⇒ logged
  warning + `None`. The boot path falls back to env-only config rather
  than crashing.

#### HTTP surface

`backend/api/routers/settings.py` exposes the override as REST:

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/settings/llm` | Read active provider — `api_key` returned **masked** (`sk-…XXXX`), never raw |
| `PUT`  | `/api/settings/llm` | Persist + hot-reload `state.llm` and `runner_deps.llm` |
| `DELETE` | `/api/settings/llm` | Clear override; fall back to env / mock |
| `POST` | `/api/settings/llm:test` | Probe a candidate config (one tiny `complete` call) without saving |
| `GET`  | `/api/settings/llm/providers` | Whitelist for the UI dropdown |

Auth: admin role required when `auth_disabled=false`; pass-through under
the laptop preset (`auth_disabled=true`).

#### "Empty `api_key` ⇒ keep current" semantics

The frontend only ever sees the masked key, so it must be possible to
PUT without re-entering the secret on every save. The contract:

* `api_key == ""` and *the same provider* is already configured ⇒
  preserve the stored / env key.
* `api_key == ""` and the provider is **switching** ⇒ require an
  explicit key (rejected with HTTP 400 — and `mock`/`ollama` are exempt
  since they don't need one).
* `api_key != ""` ⇒ replace.

#### Hot-reload boundaries

`PUT` swaps `state.llm` and `state.runner_deps.llm` so newly-enqueued
tasks pick up the change immediately. **In-flight tasks keep using the
provider they captured on `WorkflowContext`** — that matches the
isolation invariant in §2.

ARQ workers run in a separate process. They read env at boot and do
**not** observe runtime overrides. The response surfaces this with
`warns_arq_worker: true` so the UI can warn the operator.

---

## 11. Manuscripts subsystem — single docs vs project bundles

> Entry points: `backend/manuscripts/`, `backend/api/routers/manuscripts.py`,
> `frontend/src/pages/PaperWriterPage.tsx`,
> `frontend/src/components/manuscripts/BundleExplorer.tsx`.

A manuscript can carry **two layouts** in the same table:

| `layout` | Physical shape | Best for |
|---|---|---|
| `single` | A blob of Markdown plus a version chain (`ManuscriptVersion`) | Short pieces, drafts auto-produced by the write workflow, anywhere a clean `v1 → vN` history matters |
| `bundle` | An on-disk directory tree (`overleaf/` + `plan/` + `experiments/` + …) accessed through `BundleStorage` | Overleaf projects, multi-file manuscripts, projects already managed in git or an IDE (the `data/papers/paper-dataagent-eval` shape) |

`layout`, `bundle_link_path`, and `bundle_versioning` are round-tripped
through the existing `meta` JSON column inside `SqlManuscriptStore` — **no
schema migration**, and every pre-P7 row defaults to `layout="single"` so
nothing changes for them.

### 11.1 Two physical placements for bundles

```
┌──────────────────── Manuscript (layout="bundle") ───────────────────┐
│                                                                       │
│  ① copy mode (default)                                                │
│     bundle_link_path = None                                            │
│     physical root    = ./data/manuscripts/<id>/work/                  │
│     semantics        = AAF owns the directory (self-contained,         │
│                        portable, easy to back up + zip)               │
│                                                                       │
│  ② link mode                                                          │
│     bundle_link_path = "/Users/.../paper-dataagent-eval"               │
│     physical root    = that path itself                               │
│     semantics        = AAF references the user's directory; reads +    │
│                        writes happen in place — coexists with git,    │
│                        VSCode, Overleaf-sync                          │
└───────────────────────────────────────────────────────────────────────┘
```

**Key invariants:**
- All pre-existing `single`-layout APIs (`/upload`, `/versions`, `/export`)
  are untouched and behave exactly as they did before P7.
- Deleting a `bundle` manuscript only removes
  `./data/manuscripts/<id>/work/` for **copy** mode; `BundleStorage.remove_owned()`
  refuses to touch the user's directory in **link** mode.

### 11.2 Path safety — `BundleStorage._safe_resolve`

Every operation on a bundle file goes through
`_safe_resolve(manuscript, rel_path)`, which rejects four attack classes
in one place:

1. Absolute paths (`/etc/passwd`, `C:\…`)
2. `..` segments (`../../etc/passwd`)
3. URL-encoded / case-flipped / slash-flipped variants
4. Symlink escapes (caught after `Path.resolve()` by the
   `relative_to(root)` check)

The same checks gate `import_zip`, defending against zip-slip *before*
extraction; entries with a Unix symlink mode (`0o120000`) are skipped
unconditionally so a malicious zip cannot smuggle a symlink into the
bundle.

### 11.3 Size limits & write accounting

Two thresholds (from `backend/settings.py`):

| Setting | Default | Meaning |
|---|---|---|
| `AAF_MANUSCRIPT_MAX_FILE_MB` | 50 MB | Per-file cap (writes, uploads, zip entries) |
| `AAF_MANUSCRIPT_MAX_BUNDLE_MB` | 500 MB | Whole-bundle cap (correctly debits old size on overwrite) |

Writes, zip extraction, and folder import are all streaming + accounted
mid-flight: walk the existing tree once for `current_total`, then for each
new entry compute `projected = current - existing + entry_size` and abort
with `ManuscriptBundleTooLarge` immediately on overflow — a hostile zip
cannot fill the disk before validation.

### 11.4 Async + the event loop

Every blocking FS call (`os.walk`, `shutil.copy2`, `zipfile.extract`)
gets offloaded via `asyncio.to_thread(...)` so a large zip cannot wedge
FastAPI's event loop. The rule is mechanically enforced by ruff
`ASYNC240` — calling `Path.exists()` directly in an `async def` will
not pass the merge bar.

### 11.5 Endpoint matrix

```
POST   /api/manuscripts/{id}/bundle             promote single → bundle (copy or link)
GET    /api/manuscripts/{id}/tree               BundleManifest (path / size / mime / is_text / sha256? / mtime)
GET    /api/manuscripts/{id}/files/{path:path}  small-file read (text → JSON; binary → JSON+base64)
PUT    /api/manuscripts/{id}/files/{path:path}  UTF-8 text write
POST   /api/manuscripts/{id}/files/{path:path}  multipart binary upload
DELETE /api/manuscripts/{id}/files/{path:path}  delete one file / empty dir

POST   /api/manuscripts/import-folder           ingest an existing project dir (copy | link)
POST   /api/manuscripts/import-zip              multipart .zip upload → bundle
GET    /api/manuscripts/{id}/export-zip         download zip (default subdir = auto-detect overleaf/)
GET    /api/manuscripts/{id}/download/{path:p}  raw byte stream for one file
```

The "auto-detect overleaf subdir" rule is intentionally simple: if a
top-level `overleaf/` exists, only that gets packed (response carries
`X-Bundle-Subdir: overleaf`); otherwise the whole bundle is packed. The
frontend "Download Overleaf zip" button uses this directly. Pass
`?subdir=.` to force whole-bundle.

### 11.6 Error family

All new errors inherit `AAFError` and route through the existing handler
in `app.py` for RFC 7807 responses:

| Exception | HTTP | When |
|---|---|---|
| `ManuscriptLayoutMismatch` | 409 | Bundle-only endpoint hit on a `single` manuscript (or vice versa) |
| `ManuscriptPathInvalid` | 400 | `_safe_resolve` rejection (incl. zip-slip) |
| `ManuscriptFileTooLarge` | 413 | Single file exceeds `MAX_FILE_MB` |
| `ManuscriptBundleTooLarge` | 413 | Bundle exceeds `MAX_BUNDLE_MB` |
| `ManuscriptIOError` | 500 | Real OS error (disk full, permissions, …) |

### 11.7 Frontend wiring

- `ManuscriptsPage` rows show a `Bundle` / `Linked` badge based on
  `manuscript.layout`, and the trailing download icon points at the
  zip-export endpoint for bundles (still markdown-export for singles).
- "Import folder" modal calls `POST /import-folder`; "Import .zip"
  uploads to `POST /import-zip`.
- `PaperWriterPage` early-returns into `BundleExplorer` for
  `layout==="bundle"`: filterable file tree on the left (grouped by
  top-level directory) + Monaco editor on the right (language picked by
  extension — markdown / latex / bibtex / python / json / yaml / …).
  Binary files render a placeholder + Download link.
- All UI strings live in `i18n/locales/{en,zh}.json` under
  `manuscripts.*` and `bundle.*`, with i18next `_plural` for counts.

### 11.8 Bundle auto-write & gated proposals (P8)

P8 extends bundles from "human + frontend only" to "agent-driven +
gated proposal". The whole chain is layered, leaves the single-doc
path untouched, and refuses high-risk auto-writes on linked bundles.

**Call graph (bundle path only)**:

```
POST /api/tasks {workflow=revision|write, input.manuscript_id, input.bundle_target}
  → InMemoryTaskQueue → execute_task
        ① BundleAdapter.maybe_build  (returns None ⇒ legacy commit_version)
        ② Workflow.run               (revision reads ctx.input.text;
                                       runner pre-reads the bundle file
                                       into text so the workflow body
                                       stays unchanged)
        ③ _maybe_commit_manuscript
              · revision: write_text(bundle_target, results.revised)
              · write   : write_text(bundle_target, results.markdown)
                          + optional _maybe_register_in_main(\input{...})
              · → returns BundleChange(before/after/target)
              · also emits SSE event manuscript.bundle_write
        ④ _maybe_run_evolver(bundle_change=…)
              · EvolverAgent._enrich_with_bundle_change:
                  - target_paths = [target]
                  - diff = difflib.unified_diff(before, after)  ← human-only
                  - extras = {manuscript_id, bundle_target,
                              bundle_before, bundle_after, workflow}
              · drafted into ProposalStore(status="draft")

POST /api/proposals/{id}:apply-to-bundle  (admin)
  → check status / extras / risk / link mode / staleness
  → BundleStorage.write_text(manuscript, bundle_target, extras.bundle_after)
  → store.patch(extras += applied_to_bundle_at/by/size)   ← does NOT change status
```

**Invariants and where they are enforced**:

| Invariant | Enforced by |
|---|---|
| Workflow is layout-agnostic | `WorkflowContext.bundle` is `Any`-typed; workflow body only reads `ctx.input["text"]`; all layout branches live in the runner. |
| Single-doc legacy path is untouched | `BundleAdapter.maybe_build` returns `None` on every fall-back case; the bundle branch in `_maybe_commit_manuscript` only fires when `bundle is not None`; `apply-to-bundle` is *not* part of the state machine. |
| Auto-writes can't escape the bundle | All writes go through `BundleStorage.write_text` → `_safe_resolve` + per-file / total bundle size caps. |
| EvolverAgent never writes files | It only emits a `Proposal`. Writes happen exclusively in `apply-to-bundle`, which requires admin (or `auth_disabled`). |
| `apply` and `apply-to-bundle` are decoupled | `apply` still only stamps status; `apply-to-bundle` never touches status, only patches `extras` with `applied_to_bundle_at/by/size`. |
| Stale-write detection isn't silently swallowed | apply-to-bundle compares `extras.bundle_before` against on-disk content; mismatch ⇒ 409. Override requires explicit `force=true`. |
| Linked bundles refuse risky auto-writes | `manuscript.bundle_link_path` non-empty + `proposal.risk_level != "low"` ⇒ 403. |

**Diff field vs apply payload**: `proposal.diff` is a real unified diff
suitable for `Editor language="diff"`; the actual write content comes
from `extras.bundle_after`. This preserves the "unified diff is the
contract" semantics while sidestepping the cost of writing and
maintaining a real diff applier.

**Frontend surface**:

| Page | Change |
|---|---|
| `RevisionPage` | Bundle manuscripts are dispatched into a dedicated `BundleRevisionStudio` (target-file picker + before/after diff for that file). Single-doc keeps `SingleRevisionStudio` (version chain + diff). |
| `BundleExplorer` | Editor toolbar gains a "Revise this file" deep-link button that routes to `RevisionPage?manuscript=…&bundle_target=…`. |
| `ProposalsPage` | When `extras.bundle_target` is present, a "Bundle change" card surfaces target path / manuscript / last-applied timestamp + "Apply to bundle" and "Force" buttons (independent of the `Apply` state-machine action). |
| i18n | New keys under `revision.bundle.*`, `proposals.actions.applyToBundle*`, `proposals.bundle.*`, `bundle.reviseThisFile*`, with real en/zh translations. |

---

## 12. Mechanical gates (the merge bar)

Six checks gate every commit. They run locally (`make check`) and in
CI (`.github/workflows/consistency.yml`). A green run is the only
"done" signal.

| Tool | What it enforces | Where it runs |
|---|---|---|
| `ruff format` + `ruff check` | Style + lint (no `print`, no `Any` outside SDK boundaries, no bare `Exception`, …) | `make check` + CI |
| `mypy backend` | Strict typing (no `# type: ignore` without justification) | `make check` + CI |
| `pytest backend/tests -q` | All unit + integration tests must pass (currently 703 pass, 1 skipped) | `make check` + CI |
| `npm --prefix frontend run typecheck` + `build` | TS strict + production build succeeds | `make check` + CI |
| `scripts/check_consistency.py` | Structural invariants — see below | `make consistency` + CI |
| `.github/workflows/consistency.yml` | Same as above on every push / PR | CI only |

**`scripts/check_consistency.py` invariants** (each carries an inline
`Fix:` hint):

- every `skills/*/SKILL.md` has required frontmatter and a known `domain`
- every `rules/*.md` has required frontmatter
- every router file under `backend/api/routers/` is included in `backend/api/routers/__init__.py`
- every concrete `BaseWorkflow` subclass has a non-empty `name`
- every directory listed in the navigation map has an `AGENTS.md`
- no `print(...)` calls in `backend/**/*.py` or `scripts/**/*.py`
- no inline `fetch()` / `new EventSource()` in `frontend/src/**/*.tsx` (must use `@/lib/api` / `@/hooks/useSSE`)
- every router has a matching `backend/tests/integration/test_app_<resource>.py`

The principle is "docs decay; lints don't" — when you find yourself
about to write "remember to do X" in markdown, write a check instead.

---

## 13. "Where do I change…" — cheat sheet

| You want to… | Touch | Then update |
|---|---|---|
| Add an HTTP endpoint | `backend/api/routers/<area>.py` | `__init__.py` import; `backend/tests/integration/test_app_<area>.py` |
| Add a workflow | `backend/workflows/<name>.py` (subclass `BaseWorkflow`) | `backend/tests/unit/test_workflow_<name>.py` + integration test that posts to `/api/workflows/<name>/run` |
| Add a tool | `backend/tools/<name>.py` (implement `Tool` Protocol) | `backend/tools/registry.py:build_default_registry` |
| Add an LLM provider | `backend/core/llm/<name>.py` (satisfy `LLMProvider`) | `backend/core/llm/registry.py:register_defaults`; `prices.yaml` row; `docs/writing-your-own-llm-provider.md` |
| Add a skill (capability) | `skills/<name>/SKILL.md` (+ optional `scripts/*.py`) | `data/skills/<domain>/_index.yaml` if it's a research-domain skill |
| Add a behaviour rule | `rules/<short-kebab>.md` with frontmatter | (none — the engine auto-loads on boot) |
| Add a config knob | `backend/settings.py:Settings` field with `alias=` | `.env.example`; `docs/architecture.md` §3 if it changes a subsystem; `docs/runtime-internals.md` (this file) §10 if it changes a profile |
| Promote a behaviour to a static check | `scripts/check_consistency.py` | mention it in the commit message; no doc duplication |
| Change the prompt assembly order | the workflow file's `messages = [...]` block | this file §4 + the workflow's docstring |
| Change how compaction triggers | `backend/core/llm/compactor.py` | this file §5; `docs/architecture.md` §3.1 if the wrapper signature changes |
| Change the routing decorator chain | `backend/app.py:_build_llm` | this file §3.1 (the build-order box); `docs/architecture.md` §3.1 |
| Change conversation-isolation semantics | the relevant store + `MemoryBundle.rollback_run` | this file §2 (the identifier table); `backend/memory/AGENTS.md` |
| Change manuscript size caps | `backend/settings.py:Settings.manuscript_max_{file,bundle}_mb` | `.env.example`; this file §11.3 |
| Add a default-ignore rule for bundles | `backend/manuscripts/bundle_storage.py:DEFAULT_IGNORE_{DIRS,FILES}` | unit test; this file §11 if behavior changes user-visibly |

---

## 14. Glossary

| Term | Meaning |
|---|---|
| **Adapter** | Concrete `LLMProvider` implementation (`openai_compat`, `anthropic`, `ollama`, `mock`). Speaks raw HTTP to a vendor API or local process. |
| **Bundle (Injection)** | Output of `SkillInjector.inject`: `system_additions` + `tool_specs` + `script_index` + `matched_skills` + `truncated`. |
| **Bundle (Memory)** | `MemoryBundle` — façade over the 6 stores. The only object workflows hold. |
| **Compactor** | `CompactingLLMProvider` — outermost LLM provider wrapper that summarises old messages when the context window fills past the threshold. |
| **Decorator chain** | The LLM provider stack: Compactor → Routing → `_RouteTaggedProvider` → Adapter. Each layer satisfies the `LLMProvider` Protocol. |
| **Event** | Frozen dataclass `(type, task_id, at, data)`. Every meaningful side-effect emits one. |
| **Event sink** | Async callable `(Event) -> None` that the runner attaches to `WorkflowContext._sink`; appends to `TaskStore.events`. |
| **Heuristic** | L3 learned strategy. YAML row under `data/skills/<domain>/`. Mutable, version-controlled, freezable. |
| **Injector** | `SkillInjector` — renders matched skills into prompt markdown + tool specs. |
| **Loader** | `SkillLoader` — parses every `skills/*/SKILL.md` at boot. Never raises. |
| **Matcher** | `SkillMatcher` — keyword + cosine scoring; embedding cache invalidates per registry generation. |
| **Profile** | A `.env.*` file presetting backend choices (production / laptop / offline). |
| **Proposal** | Gated framework-change request. Goes through `draft → pending → approved → applied` state machine in `ProposalStore`. |
| **Rule (L2)** | Markdown file under `rules/` with `enforcement: "prompt"` (stitched into system prompt) or `enforcement: "hook"` (callable run by `RuleEngine.pre_action`). |
| **Skill (L1)** | Markdown file under `skills/<name>/SKILL.md` + optional scripts. Capability the agent can invoke. |
| **`source_run_id`** | Mandatory column on every memory write. Equal to `task_id` for workflow-driven writes; `"ingest:<paper_id>"` for paper-ingest writes. Drives `rollback_run`. |
| **Task** | One workflow run. Identified by `task_id` (UUID hex). Persisted in `TaskStore` with append-only event log. |
| **Telemetry** | LLM call records in `TelemetryRecorder` (1000-record ring buffer). Surfaces at `/api/v1/models/usage`. |
| **WorkflowContext** | Per-run dataclass holding `task_id`, `query`, `input`, `user_id`, `session_id`, `llm`, `memory`, `tools`, `skill_host`, `budget`, `state`, `trace`, sink, checkpointer. Passed explicitly everywhere — no globals. |
| **Bundle (P7 manuscript)** | Project-shaped manuscript with `layout="bundle"`; multi-file, can coexist with git / Overleaf. |
| **Copy mode** | AAF owns the bundle directory under `./data/manuscripts/<id>/work/` — self-contained, portable. |
| **Link mode** | Bundle physical root **is** an external user-supplied directory; AAF reads + writes in place, never deletes. |
| **`BundleStorage`** | Path-safe FS layer (`backend/manuscripts/bundle_storage.py`) that hosts the size caps, the ignore set, and the import / export streams. |
| **Overleaf-subdir convention** | A `bundle-root/overleaf/` directory; `export-zip` picks it automatically when present. |

---

## Change log

- **v1.0 — 2026-05-10.** Initial document. Captures the runtime as of the
  670-pass test suite (P0.1 → P5 complete).
- **v1.1 — 2026-05-10.** P7 manuscript bundles. Adds §11 (Manuscripts
  subsystem); renumbers Mechanical gates → §12, "Where do I change…" →
  §13, Glossary → §14. Backs the 735-pass suite.
