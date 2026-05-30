"""ARQ worker process — picks up tasks enqueued by the API and runs them.

Run with::

    uv run arq backend.workers.arq_worker.WorkerSettings

The worker builds a fresh :class:`RunnerDeps` on startup (its own
workflow registry, memory bundle, LLM provider, tool registry) and
hands it to :func:`execute_task`. Nothing is shared with the API
process except the SQL task store (via ``database_url``) and Redis.
"""

from __future__ import annotations

from typing import Any, ClassVar

import structlog

from backend.app import _build_bundle_storage, _build_llm  # re-use API-side wiring
from backend.manuscripts.sql_store import SqlManuscriptStore
from backend.memory.factory import MemoryFactory
from backend.settings import Settings, get_settings
from backend.tasks.queue import ARQ_JOB_NAME
from backend.tasks.runner import RunnerDeps, execute_task
from backend.tasks.sql_store import SqlTaskStore
from backend.tools.registry import build_default_registry as build_tools
from backend.workflows.registry import build_default_registry as build_workflows

log = structlog.get_logger(__name__)


async def on_startup(ctx: dict[str, Any]) -> None:
    settings: Settings = get_settings()
    ctx["settings"] = settings

    store = SqlTaskStore.from_url(settings.database_url)
    await store.init()
    ctx["store"] = store

    manuscripts = SqlManuscriptStore.from_url(settings.database_url)
    await manuscripts.init()
    ctx["manuscripts"] = manuscripts

    llm = _build_llm(settings)
    factory = MemoryFactory(settings.memory_config(), embedder=llm)
    bundle = await factory.build()
    ctx["memory_factory"] = factory
    ctx["memory"] = bundle

    bundle_storage = _build_bundle_storage(settings)
    ctx["bundle_storage"] = bundle_storage

    ctx["deps"] = RunnerDeps(
        store=store,
        workflows=build_workflows(),
        memory=bundle,
        llm=llm,
        tools=build_tools(),
        manuscripts=manuscripts,
        bundle_storage=bundle_storage,
        default_budget_usd=settings.default_budget_usd,
    )
    log.info("arq_worker.ready", workflows=ctx["deps"].workflows.names())


async def on_shutdown(ctx: dict[str, Any]) -> None:
    store = ctx.get("store")
    if store is not None:
        await store.close()
    manuscripts = ctx.get("manuscripts")
    if manuscripts is not None:
        await manuscripts.close()
    factory = ctx.get("memory_factory")
    if factory is not None:
        await factory.aclose()


async def run_task(ctx: dict[str, Any], task_id: str) -> str:
    """ARQ job function — one task id per invocation."""
    deps: RunnerDeps = ctx["deps"]
    try:
        await execute_task(task_id, deps)
    except Exception:
        log.exception("arq_worker.execute_failed", task_id=task_id)
        raise
    return task_id


# Bind the ARQ job name expected by the API-side enqueuer.
run_task.__name__ = ARQ_JOB_NAME


class WorkerSettings:
    """Entry point for ``arq backend.workers.arq_worker.WorkerSettings``."""

    functions: ClassVar[list[Any]] = [run_task]
    on_startup = on_startup
    on_shutdown = on_shutdown

    # Redis settings are resolved lazily at worker start so test imports don't connect.
    @classmethod
    def redis_settings(cls) -> Any:
        from arq.connections import RedisSettings

        return RedisSettings.from_dsn(get_settings().redis_url)


__all__ = ["WorkerSettings", "on_shutdown", "on_startup", "run_task"]
