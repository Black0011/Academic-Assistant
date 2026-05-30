"""Stream a workflow run and print one event per second class.

Demonstrates the SSE endpoint via :meth:`AsyncTasksAPI.stream`. Useful as
a smoke test: ``python stream_task.py demo "what is RAG?"``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from aaf import AsyncAAFClient


async def main(workflow: str, query: str) -> int:
    base_url = os.environ.get("AAF_BASE_URL", "http://localhost:8000")
    token = os.environ.get("AAF_TOKEN")

    async with AsyncAAFClient(base_url, token=token) as cli:
        task = await cli.tasks.create(workflow=workflow, query=query)
        print(f"# task {task.task_id} workflow={task.workflow}")

        started = time.monotonic()
        seen: dict[str, int] = {}
        async for event in cli.tasks.stream(task.task_id):
            seen[event.type] = seen.get(event.type, 0) + 1
            elapsed = time.monotonic() - started
            print(f"[{elapsed:6.2f}s] {event.type:<24} {event.data}")
            if event.type in {"task.end", "task.error"}:
                break

        print("# event totals:")
        for kind, count in sorted(seen.items()):
            print(f"  {kind}: {count}")
        return 0


if __name__ == "__main__":  # pragma: no cover
    workflow_name = sys.argv[1] if len(sys.argv) > 1 else "demo"
    query_arg = " ".join(sys.argv[2:]) or "demo query"
    raise SystemExit(asyncio.run(main(workflow_name, query_arg)))
