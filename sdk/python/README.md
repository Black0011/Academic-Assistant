# `aaf-sdk` — Python client for the Academic Agent Framework

`aaf-sdk` is a thin, async-first HTTP client for the [Academic Agent
Framework][aaf-repo] backend. It mirrors the public REST surface
(`/api/auth`, `/api/workflows`, `/api/tasks`, `/api/manuscripts`,
`/api/knowledge`, `/api/heuristics`, `/api/memory`, `/api/tools`) and
ships canonical Pydantic models so caller code stays typed.

The SDK has only two runtime dependencies — `httpx` and `pydantic` — and
works against any AAF deployment (local Uvicorn, the Docker Compose
stack in `deploy/`, or a remote install behind TLS).

[aaf-repo]: https://github.com/aaf/academic-agent-framework

## Install

```bash
# from the monorepo root
pip install -e sdk/python
# or, when published to PyPI
pip install aaf-sdk
```

Python ≥ 3.10 is required.

## Async usage

```python
import asyncio
from aaf import AsyncAAFClient

async def main() -> None:
    async with AsyncAAFClient("http://localhost:8000") as cli:
        # Login is optional when the backend has AUTH_DISABLED=true.
        await cli.login("admin@example.com", "secret")

        task = await cli.tasks.create(
            workflow="research",
            query="Mixture-of-experts inference systems",
            budget_usd=0.5,
        )
        print("task:", task.task_id)

        async for event in cli.tasks.stream(task.task_id):
            print(event.type, event.data)

        record = await cli.tasks.get(task.task_id)
        print("verdict:", record.status, record.result)

asyncio.run(main())
```

## Sync usage

For scripts that don't want to manage an event loop:

```python
from aaf import AAFClient

with AAFClient("http://localhost:8000", token="…") as cli:
    for ms in cli.manuscripts.list_all():
        print(ms.id, ms.title, "v" + str(ms.current_version))
```

Streaming endpoints return regular generators so SSE works without `await`:

```python
for event in cli.tasks.stream(task_id):
    if event.type == "task.end":
        break
```

## Sub-clients

| Property               | Server prefix          | Purpose                                          |
|------------------------|------------------------|--------------------------------------------------|
| `client.auth`          | `/api/auth`            | login / register / `/me` / config flags         |
| `client.workflows`     | `/api/workflows`       | list / synchronous run / SSE stream             |
| `client.tasks`         | `/api/tasks`           | enqueue, poll, cancel, replay, SSE stream       |
| `client.manuscripts`   | `/api/manuscripts`     | CRUD, versioning, upload (md/pdf), export       |
| `client.knowledge`     | `/api/knowledge`       | paper cards + typed links                        |
| `client.heuristics`    | `/api/heuristics`      | L3 strategy memory: list/match/freeze/bump      |
| `client.memory`        | `/api/memory`          | stats, reflections, run rollback                 |
| `client.tools`         | `/api/tools`           | introspect + invoke registered tools             |

The `Async*API` classes mirror these one-for-one and live on
`AsyncAAFClient`. Listing methods are named `list_all()` to avoid
shadowing the `list` builtin in type annotations; pagination params
(`limit` / `offset`) are accepted where supported.

## Authentication

The backend ships with a stdlib-only JWT subsystem. Three patterns:

1. **Pre-issued token.**

   ```python
   AsyncAAFClient(token=os.environ["AAF_TOKEN"])
   ```

2. **Programmatic login.** Stashes the token on the client for you.

   ```python
   await cli.login(email, password)
   ```

3. **No auth.** When the server is started with
   `AUTH_DISABLED=true`, every endpoint accepts requests without a
   token. The SDK transparently skips the `Authorization` header.

## Errors

Non-2xx responses raise typed exceptions you can catch directly:

```python
from aaf import APIError, AuthenticationError, NotFoundError

try:
    await cli.tasks.get("missing")
except NotFoundError:
    ...
except AuthenticationError:
    await cli.login(...)
except APIError as exc:
    log.warning("AAF returned %s: %s", exc.status_code, exc.detail)
```

## Testing

The SDK is fully testable with `respx` (an `httpx` recorder) — pass an
`httpx.MockTransport` to the client constructor:

```python
import httpx, respx
from aaf import AsyncAAFClient

async def test_health():
    transport = httpx.MockTransport(lambda req: httpx.Response(
        200, json={"status": "ok"}))
    async with AsyncAAFClient("http://t.local", transport=transport) as cli:
        assert await cli.health() == {"status": "ok"}
```

## Examples

Runnable scripts under `examples/` (require a live backend):

| File                       | What it does                                     |
|----------------------------|--------------------------------------------------|
| `examples/run_research.py` | Enqueue + wait for a research workflow run      |
| `examples/stream_task.py`  | Live SSE stream of a workflow with timing prints |

Run them with:

```bash
pip install -e .
export AAF_BASE_URL=http://localhost:8000
export AAF_TOKEN=…   # optional when AUTH_DISABLED=true
python examples/run_research.py
```

## Compatibility

The SDK pins to the public REST surface — schema drift is detected at
runtime via Pydantic validation. To regenerate the model file against a
running server:

```python
import json, httpx
spec = httpx.get("http://localhost:8000/openapi.json").json()
print(json.dumps(spec["components"]["schemas"], indent=2))
```

Open an issue if a backend release changes a contract before this SDK
catches up.

## License

MIT — see the repo root.
