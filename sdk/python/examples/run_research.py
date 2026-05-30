"""Enqueue a research workflow run and wait for the result.

Usage:

    pip install -e ../..[dev]
    export AAF_BASE_URL=http://localhost:8000
    export AAF_TOKEN=…              # optional when AUTH_DISABLED=true
    python run_research.py "MoE inference systems"
"""

from __future__ import annotations

import asyncio
import os
import sys

from aaf import AsyncAAFClient


async def main(query: str) -> int:
    base_url = os.environ.get("AAF_BASE_URL", "http://localhost:8000")
    token = os.environ.get("AAF_TOKEN")

    async with AsyncAAFClient(base_url, token=token) as cli:
        health = await cli.health()
        print(f"# server: {base_url} status={health.get('status', '?')}")

        task = await cli.tasks.create(
            workflow="research",
            query=query,
            budget_usd=float(os.environ.get("AAF_BUDGET_USD", "0.5")),
        )
        print(f"# enqueued task {task.task_id} workflow={task.workflow}")

        record = await cli.tasks.wait(task.task_id, timeout_s=900)
        print(f"# verdict={record.status} budget={record.budget}")
        if record.error:
            print(f"# error: {record.error}")
            return 2
        if record.result:
            print("# result keys:", sorted(record.result))
        return 0


if __name__ == "__main__":  # pragma: no cover
    query_arg = " ".join(sys.argv[1:]) or "Mixture-of-Experts inference systems"
    raise SystemExit(asyncio.run(main(query_arg)))
