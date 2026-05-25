"""Runtime singletons exposed to routers via FastAPI dependencies.

`AppState` is constructed exactly once per process by the lifespan handler
in :mod:`backend.app` and disposed on shutdown. Routers that want any of
the dependencies ask for them via :func:`get_app_state` — everything is
attached to ``request.app.state.aaf``.

Keeping this a plain dataclass (no globals, no Pydantic) makes it trivial
to construct in tests::

    state = AppState(memory=MemoryBundle.in_memory(), llm=MockLLMProvider())
    app.state.aaf = state
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from backend.core.auth.users import UserStore
    from backend.core.llm.base import LLMProvider
    from backend.core.runtime_config import RuntimeConfigStore
    from backend.core.skill_host import SkillHost
    from backend.core.skill_host.admin import SkillAdmin
    from backend.manuscripts.bundle_storage import BundleStorage
    from backend.manuscripts.store import ManuscriptStore
    from backend.memory.base import MemoryBundle
    from backend.memory.factory import MemoryFactory
    from backend.proposals.store import ProposalStore
    from backend.settings import Settings
    from backend.tasks.queue import TaskQueue
    from backend.tasks.runner import RunnerDeps
    from backend.tasks.store import TaskStore
    from backend.tools.registry import ToolRegistry
    from backend.workflows.registry import WorkflowRegistry


@dataclass
class AppState:
    """Everything a request might touch. Assembled by lifespan."""

    settings: Settings | None = None
    memory: MemoryBundle | None = None
    memory_factory: MemoryFactory | None = None
    llm: LLMProvider | None = None
    tools: ToolRegistry | None = None
    workflows: WorkflowRegistry | None = None
    task_store: TaskStore | None = None
    task_queue: TaskQueue | None = None
    manuscripts: ManuscriptStore | None = None
    # Filesystem-backed bundle storage for project-shaped manuscripts (P7).
    # Created in lifespan even when no bundle exists yet — it's cheap and the
    # router needs it the moment the first user converts a manuscript.
    bundle_storage: BundleStorage | None = None
    users: UserStore | None = None
    skill_host: SkillHost | None = None
    skill_admin: SkillAdmin | None = None
    proposals: ProposalStore | None = None
    # Held so the /api/settings/llm hot-reload path can swap deps.llm
    # without restarting the whole queue. ARQ workers run in a separate
    # process and do not honour this swap — they re-read env at boot.
    runner_deps: RunnerDeps | None = None
    # Persistent override layer for the default LLM provider; written by
    # the frontend Settings panel. Absent ⇒ env-only defaults.
    runtime_config_store: RuntimeConfigStore | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def get_app_state(request: Request) -> AppState:
    """FastAPI dependency. Raises AttributeError if lifespan didn't run."""
    return request.app.state.aaf


__all__ = ["AppState", "get_app_state"]
