---
name: aaf-llm-provider
description: >-
  How to write or modify an LLM provider adapter in AAF so the framework stays
  LLM-agnostic. Covers the Protocol, streaming, tool-call translation, error
  handling, retries, cost tracking, and testing via MockLLMProvider. Load this
  skill when touching backend/core/llm/*.
domain: engineering
triggers:
  - llm provider
  - add llm
  - openai provider
  - anthropic provider
  - ollama
  - backend/core/llm
version: "1.0.0"
---

# AAF LLM Provider — Adapter Contract

AAF assumes *any* LLM with a chat API can run *any* workflow. This skill freezes the adapter contract so new providers snap in without touching agents.

## 1. The Protocol

```python
# backend/core/llm/base.py
class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None = None,
        model: str | None = None,        # None → provider default
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = True,
    ) -> AsyncIterator[CompletionChunk]: ...

    async def embed(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]: ...

    def supports_tools(self) -> bool: ...
    def supports_streaming(self) -> bool: ...
    def context_window(self, model: str) -> int: ...
    async def estimate_cost(self, messages, model) -> CostEstimate: ...
```

All adapters must satisfy this Protocol. Use `typing.Protocol` not ABC — adapters should not be forced to inherit.

## 2. Data structures (canonical shapes)

```python
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentPart]         # ContentPart covers text|image|...
    tool_calls: list[ToolCall] | None = None # role=="assistant" case
    tool_call_id: str | None = None          # role=="tool" case
    name: str | None = None                  # optional tool/user label

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict                          # parsed, not raw JSON string

class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict                         # JSON Schema

class CompletionChunk(BaseModel):
    type: Literal["delta", "tool_call", "done", "error"]
    delta: str | None = None
    tool_call: ToolCall | None = None
    finish_reason: str | None = None
    usage: Usage | None = None               # non-None only on done

class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
```

Adapters must **emit `CompletionChunk`** — never raw provider chunks. Translation is the adapter's job.

## 3. Writing a new adapter

File: `backend/core/llm/<name>.py`. Class: `class {Name}Provider: ...`. Register in `registry.py` under a short key (`"openai"`, `"anthropic"`, `"ollama"`, etc.).

Steps:

1. Accept a `config: dict` in `__init__` (base_url, api_key, default_model, timeouts).
2. Use `httpx.AsyncClient` (not `requests`). Reuse a shared client per provider instance.
3. Translate `messages` + `tools` to provider's native schema.
4. Iterate provider's SSE or stream and yield `CompletionChunk`s in order.
5. On the final chunk, attach `usage`.

### Tool-call translation matrix

| Framework shape | OpenAI-compat | Anthropic | Ollama |
|---|---|---|---|
| `ToolSpec`        | `tools[].function` | `tools[]` (input_schema) | OpenAI mode: same |
| `assistant tool_calls` | `message.tool_calls` | `content[].type == "tool_use"` | OpenAI mode: same |
| `role=tool` | `role:"tool", tool_call_id` | `role:"user", content[].type=="tool_result", tool_use_id` | OpenAI mode: same |

Anthropic quirk: tool results are **user** messages, not tool messages. The adapter must re-map on both outbound and inbound.

## 4. Error handling

Catch provider SDK exceptions and re-raise as one of:

- `LLMTimeout`             → HTTP 504, retryable=True
- `LLMRateLimit`           → HTTP 429, retryable=True, honour `Retry-After`
- `LLMAuthError`           → HTTP 401, retryable=False
- `LLMContextWindowError`  → HTTP 422, retryable=False
- `LLMAPIError`            → HTTP 502, retryable=True (default)

All defined in `backend/core/errors.py`. Never raise the raw SDK exception above the adapter boundary.

## 5. Retry policy

Use `tenacity`:

```python
@retry(
    retry=retry_if_exception_type(LLMTimeout | LLMAPIError | LLMRateLimit),
    wait=wait_exponential_jitter(initial=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _call(...): ...
```

Do not retry tool-level errors — those belong to the Executor.

## 6. Telemetry

Every completed stream must call `backend.core.llm.telemetry.record(...)` with:

```
provider, model, task_id, prompt_tokens, completion_tokens,
duration_ms, cost_usd, error_code
```

Cost: look up `backend/core/llm/prices.yaml` for `(provider, model)`. If missing, record `cost_usd=None` (do not raise).

## 7. Registry

```python
llm_registry = LLMRegistry()
llm_registry.register("openai", lambda cfg: OpenAICompatProvider(cfg))
llm_registry.register("anthropic", lambda cfg: AnthropicProvider(cfg))
# ...
provider = llm_registry.get("openai", settings.providers["openai"])
```

Registration happens at FastAPI lifespan startup in `backend/main.py`.

## 8. Mock provider (for tests)

`backend/core/llm/mock.py` must support:
- Scripted responses (YAML fixture).
- Forced tool-calls on demand.
- Fake streaming (yield deltas token-by-token).
- Counted invocations for assertions.

Every integration test MUST use `MockLLMProvider`. Never hit real endpoints in CI.

## 9. Checklist for a new adapter PR

- [ ] File `backend/core/llm/<name>.py` + class `{Name}Provider`
- [ ] Registered in `registry.py`
- [ ] Tool-call round-trip test (assistant → tool → assistant)
- [ ] Streaming test with at least 2 deltas and final usage
- [ ] Error-mapping test for timeout + rate-limit
- [ ] Entry in `prices.yaml` for each known model
- [ ] Docs: add row in `docs/writing-your-own-llm-provider.md`

## 10. Embed-only adapters

Some providers are useful for ONLY one half of the Protocol — typically
embeddings (`backend/core/llm/local_embedder.py` is the canonical
example: a sentence-transformers wrapper that has no chat surface).

Rules for embed-only adapters:

1. Still satisfy the full `LLMProvider` Protocol structurally; missing
   methods (`complete`, `estimate_cost`) raise `NotImplementedError`
   with a message that names the right alternative
   (e.g. *"set DEFAULT_LLM_PROVIDER=ollama for chat"*).
2. **Do not** register them in the global `default_registry()` under
   the same key as a full provider — they would silently break
   workflows that expect `complete()`.
3. Wire them via dedicated factory paths only (e.g. `_build_embedder`
   in `backend/app.py`), never via `default_llm_provider`.
4. Lazy-import heavy deps (torch, sentence-transformers, etc.) inside
   the constructor so users without the extra installed don't pay
   import cost; on `ImportError` raise `ConfigError` pointing at the
   `uv sync --extra <name>` invocation that fixes it.
5. Use `asyncio.to_thread` for any sync CPU/GPU work so the event
   loop keeps serving other requests during encoding.
6. Translate library exceptions into the same `LLMAPIError` family
   the remote providers use, so callers (vector store, matcher) keep a
   single fallback branch.
