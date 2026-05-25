# Writing your own LLM provider

AAF treats every LLM the same way: an adapter implementing the
`LLMProvider` Protocol and a factory registered with
`LLMRegistry`. This document is the canonical recipe.

The contract is fixed by rule **`aaf-llm-provider`** and lives in
`backend/core/llm/base.py`. Don't pass vendor-native dicts across the
boundary — every adapter speaks the canonical Pydantic models from
`base.py`.

## 1. Existing built-ins

| Adapter             | File                                  | Notes                                                                 |
|---------------------|---------------------------------------|-----------------------------------------------------------------------|
| `openai`            | `backend/core/llm/openai_compat.py`   | OpenAI-shape `/chat/completions` + `/embeddings`. Also covers Azure, vLLM, DeepSeek, Moonshot, SiliconFlow, Together, Groq, llama.cpp, etc. |
| `ollama`            | same `OpenAICompatProvider` class      | Reuses the OpenAI adapter; just a different base URL + dummy key.     |
| `anthropic`         | `backend/core/llm/anthropic.py`       | Anthropic Messages API; system messages live outside `messages`, tool calls use `content[].type=="tool_use"`. |
| `mock`              | `backend/core/llm/mock.py`            | Scriptable, in-memory; used by every unit test.                       |

Each adapter uses raw `httpx` so tests can inject `httpx.MockTransport`
— **don't depend on the vendor SDK**.

## 2. The Protocol

```python
@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = True,
    ) -> AsyncIterator[CompletionChunk]: ...

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]: ...

    def supports_tools(self) -> bool: ...
    def supports_streaming(self) -> bool: ...
    def context_window(self, model: str) -> int: ...

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate: ...
```

### 2.1 Canonical models (`backend/core/llm/base.py`)

| Model              | What it carries                                                              |
|--------------------|------------------------------------------------------------------------------|
| `ChatMessage`      | `role` ∈ `system|user|assistant|tool`, `content` (str or `list[ContentPart]`), optional `tool_calls`, `tool_call_id`. |
| `ContentPart`      | `TextPart` / `ImagePart` (multi-modal capable; not all providers will).      |
| `ToolSpec`         | `name`, `description`, `parameters` (JSON-Schema dict).                      |
| `ToolCall`         | `id`, `name`, `arguments` (decoded JSON dict).                               |
| `CompletionChunk`  | `type` ∈ `delta|tool_call|done|error`, optional `delta`, `tool_call`, `usage`, `finish_reason`, `error`. |
| `Usage`            | `prompt_tokens`, `completion_tokens`, `total_tokens`.                        |
| `CostEstimate`     | `usd`, `input_tokens`, `output_tokens?`, `model`, `provider`.                |

### 2.2 Streaming guarantees

`complete()` **always** returns an `AsyncIterator[CompletionChunk]`,
even when `stream=False`. Callers iterate uniformly:

```python
async for chunk in provider.complete(messages):
    if chunk.type == "delta":
        ...
    elif chunk.type == "tool_call":
        ...
    elif chunk.type == "done":
        usage = chunk.usage
    elif chunk.type == "error":
        raise LLMStreamError(chunk.error)
```

There is a helper `collect_text(stream) -> (text, tool_calls, usage)`
for callers that don't care about deltas.

### 2.3 Errors

Raise typed errors from `backend/core/errors.py`:

| Error class             | When                                                          |
|-------------------------|---------------------------------------------------------------|
| `LLMAuthError`          | 401/403 from the upstream API.                                |
| `LLMRateLimit`          | 429 / quota exhaustion.                                       |
| `LLMTimeout`            | `httpx.TimeoutException` or upstream stall.                   |
| `LLMContextWindowError` | Prompt too large for the model's window.                      |
| `LLMAPIError`           | Any other non-2xx response.                                   |
| `LLMStreamError`        | Mid-stream parse error or `error`-typed chunk.                |

The OpenAI adapter shows the canonical mapping; reuse the patterns
verbatim for new HTTP-backed providers.

## 3. Registering the provider

Once your class satisfies the Protocol, register a factory with the
process-wide registry:

```python
# backend/core/llm/registry.py
def register_defaults(reg: LLMRegistry) -> None:
    ...

    def _my_provider(cfg: dict[str, Any]) -> LLMProvider:
        from .my_provider import MyProvider
        return MyProvider(
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url") or "https://api.example.com/v1",
            default_model=cfg.get("default_model") or "model-1",
        )

    reg.register("my-provider", _my_provider)
```

`Settings` then auto-wires the credentials from env vars on convention
`<NAME>_API_KEY`, `<NAME>_BASE_URL`, `<NAME>_DEFAULT_MODEL`. Add the
attributes on `Settings`:

```python
# backend/settings.py
my_provider_api_key: str = ""
my_provider_base_url: str = "https://api.example.com/v1"
my_provider_default_model: str = "model-1"
```

`Settings.has_llm_credentials("my-provider")` returns True iff the
`my_provider_api_key` is non-empty (or the base URL alone is enough,
in the Ollama-style case — special-case it like the registry does).

## 4. Worked example: minimal HTTP provider

```python
# backend/core/llm/my_provider.py
"""MyProvider — ExampleCo Chat API.

Spec: https://api.example.com/docs/chat
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.core.errors import (
    LLMAPIError,
    LLMAuthError,
    LLMContextWindowError,
    LLMRateLimit,
    LLMStreamError,
    LLMTimeout,
)

from .base import (
    ChatMessage,
    CompletionChunk,
    CostEstimate,
    ToolSpec,
    Usage,
)


class MyProvider:
    name = "my-provider"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.example.com/v1",
        default_model: str = "model-1",
        timeout_s: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_s = timeout_s
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = True,
    ) -> AsyncIterator[CompletionChunk]:
        body: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = [t.model_dump() for t in tools]

        return self._stream(body) if stream else self._oneshot(body)

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        response = await self._client.post(
            "/embeddings",
            json={"model": model or "embed-1", "input": texts},
        )
        self._raise_for_status(response)
        return [item["embedding"] for item in response.json()["data"]]

    def supports_tools(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def context_window(self, model: str) -> int:
        return {"model-1": 32_000, "model-large": 128_000}.get(model, 8192)

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate:
        tokens = sum(len(m.text()) // 4 for m in messages)  # crude estimate
        return CostEstimate(
            usd=tokens * 1e-6,
            input_tokens=tokens,
            model=model or self._default_model,
            provider=self.name,
        )

    # ---- internals ----------------------------------------------------

    async def _stream(self, body: dict[str, Any]) -> AsyncIterator[CompletionChunk]:
        async with self._client.stream("POST", "/chat/completions", json=body) as resp:
            self._raise_for_status(resp)
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    yield CompletionChunk(type="done", finish_reason="stop")
                    return
                try:
                    chunk = json.loads(payload)
                except ValueError as exc:
                    raise LLMStreamError(f"bad SSE payload: {payload!r}") from exc
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if "content" in delta and delta["content"]:
                    yield CompletionChunk(type="delta", delta=delta["content"])
                # …handle tool_calls / usage as needed…

    async def _oneshot(self, body: dict[str, Any]) -> AsyncIterator[CompletionChunk]:
        body = {**body, "stream": False}
        response = await self._client.post("/chat/completions", json=body)
        self._raise_for_status(response)
        data = response.json()
        choice = data["choices"][0]
        message = choice.get("message", {})
        if message.get("content"):
            yield CompletionChunk(type="delta", delta=message["content"])
        usage = data.get("usage") or {}
        yield CompletionChunk(
            type="done",
            finish_reason=choice.get("finish_reason", "stop"),
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code == 401:
            raise LLMAuthError("invalid api key")
        if response.status_code == 429:
            raise LLMRateLimit("rate limit exceeded")
        if response.status_code == 408:
            raise LLMTimeout("upstream timeout")
        if response.status_code == 413:
            raise LLMContextWindowError("prompt too long")
        raise LLMAPIError(f"HTTP {response.status_code}: {response.text[:200]}")
```

## 5. Tests

Three required layers:

1. **Unit test** the encoding/decoding logic without network — feed
   pre-canned bytes through an `httpx.MockTransport`:

   ```python
   import httpx
   import pytest

   from backend.core.llm.my_provider import MyProvider

   @pytest.mark.asyncio
   async def test_my_provider_streams_deltas():
       def handler(request: httpx.Request) -> httpx.Response:
           assert request.url.path == "/chat/completions"
           sse = b"data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n\ndata: [DONE]\n\n"
           return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})
       transport = httpx.MockTransport(handler)
       client = httpx.AsyncClient(transport=transport, base_url="http://t")
       provider = MyProvider(api_key="x", base_url="http://t", client=client)
       chunks = []
       async for chunk in await provider.complete([ChatMessage(role="user", content="hi")]):
           chunks.append(chunk)
       assert chunks[0].delta == "hi"
       assert chunks[-1].type == "done"
   ```

2. **Registry test** asserting your factory is wired:

   ```python
   from backend.core.llm.registry import default_registry

   def test_my_provider_registered():
       assert default_registry().has("my-provider")
   ```

3. **Integration smoke** (only when credentials are set in CI; gate
   with `pytest.skip` on missing key) — make one call, assert non-empty
   response. Don't spend more than a few cents per CI run.

## 6. Optional polish

- **Cost telemetry.** `backend/core/llm/telemetry.py` records every
  call (`record(...)`) and provides `estimate_cost_usd(...)`. Call
  `record` from your provider so `Budget` and the workflow event log
  show real costs.
- **Tool-calling.** If your provider supports it, encode `tools` and
  decode `tool_call` chunks into `ToolCall` instances; otherwise leave
  `supports_tools()` returning `False` and let the workflow fall back
  to text-only prompting.
- **Embeddings.** If your provider doesn't expose embeddings, raise
  `LLMAPIError("embeddings not supported")` from `embed()` and let the
  caller pick a different `embedding_provider` via Settings.
- **Local servers.** For Ollama-style local servers, accept an empty
  API key and don't send the `Authorization` header.

## 7. Checklist

```
☐ Class implements every method on the LLMProvider Protocol.
☐ All cross-boundary data uses the canonical Pydantic models.
☐ Errors mapped to backend.core.errors.LLM*.
☐ Factory registered in backend/core/llm/registry.py:register_defaults.
☐ Settings has <name>_api_key / <name>_base_url / <name>_default_model.
☐ Unit test exercises the encoder + decoder via httpx.MockTransport.
☐ make consistency, ruff, mypy, pytest all pass.
☐ Documented the new provider name in deploy/.env.example.
```

## 8. Per-task routing (M-Router)

Once your provider is registered, it can immediately participate in
the task-level model router (`backend/core/llm/router.py`). You do
**not** need to change anything inside the adapter.

### 8.1 What the router gives workflows

`RoutingLLMProvider` wraps a single *default* `LLMProvider` plus a
named map of alternative `LLMProvider`s. It satisfies the
`LLMProvider` Protocol itself by delegating every method to the
default, and adds one extra method:

```python
class RoutingLLMProvider:
    def for_route(self, name: str | None) -> LLMProvider: ...
```

Workflows opt into a different model by calling:

```python
provider = ctx.llm.for_route("reasoning")   # falls back to default if unknown
async for chunk in await provider.complete(messages):
    ...
```

Unknown route names degrade to the default — adding/removing routes in
the deployment YAML never breaks a workflow.

### 8.2 Activating routing

The router is **opt-in by file presence**. Drop a YAML at
`./config/model_routing.yaml` (path overridable via
`AAF_MODEL_ROUTING_CONFIG`):

```yaml
default:
  provider: my-provider          # any name registered in LLMRegistry
  api_key_env: MY_PROVIDER_API_KEY
  base_url: https://api.example.com/v1
  model: model-1
routes:
  reasoning:
    model: model-large           # inherits provider/api_key/base_url
  fast:
    model: model-1
  local:
    provider: ollama
    base_url: http://localhost:11434/v1
    model: llama3.1:8b
    api_key_env: ""
```

Each route inherits unspecified fields from `default`. `api_key_env`
points at an environment variable name — **never write live keys into
the YAML**.

### 8.3 Built-in error handling

`load_routing_policy` raises a single `backend.core.errors.ConfigError`
on any malformed input (bad YAML, non-mapping root, schema mismatch).
`backend.app._build_llm` catches `(ConfigError, NotFoundError, OSError)`,
logs the full traceback via `log.exception(...)`, and falls back to the
single-provider path — **routing failure never aborts boot**.

### 8.4 What you need to do as a provider author

Nothing extra. As long as your factory is in
`register_defaults(...)` and your provider name is referenced by a
route in `model_routing.yaml`, it will be picked up automatically.

### 8.5 Adding telemetry per route (optional)

If you want per-route token/cost statistics in `/models/usage`, call
`backend.core.llm.telemetry.record(...)` with the active route name.
The router itself is a thin proxy; the natural place to thread the
route label is the workflow stage that selected it (i.e. wherever
`for_route` was called). See `backend/workflows/research.py` for the
canonical pattern.

## 9. Auto-compaction (optional outer wrapper)

When the deployment sets `AAF_AUTOCOMPACT_ENABLED=true`, AAF wraps
your provider one more time in
`backend.core.llm.compactor.CompactingLLMProvider`. The compactor
intercepts every `complete()` call:

1. estimate the message tokens (cheap heuristic, no `tiktoken` dep);
2. if the estimate exceeds `context_window(model) * threshold`
   (default 0.7), summarise the *middle* of the conversation via a
   single LLM call and drop the original middle messages;
3. otherwise pass-through unchanged (zero overhead).

You don't have to do anything in your adapter to participate. Two
recommendations:

* **`context_window(model)` should return the real upper bound** for
  models you support. The compactor uses it to decide when to fire;
  returning `8192` for everything is fine but means compaction may
  fire too eagerly on a `128k` model.
* **Don't trigger compaction inside your adapter.** A contextvar
  (`backend.core.llm.compactor.is_inside_compaction()`) tells you when
  the current call is the summariser pass — useful when you want to
  short-circuit telemetry or log differently — but the wrapper itself
  already prevents recursion.

If you need to compact in your own workflow stage (custom reduce
strategy), call `compact_messages(...)` directly with whichever
provider you want as the summariser; it returns a
`CompactionResult` you can inspect. The Protocol-level wrapper is the
default, ergonomic path; this is the escape hatch.
