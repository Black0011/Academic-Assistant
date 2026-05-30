"""FastAPI application factory + lifespan wiring.

Boots all subsystems declared in :class:`Settings` and attaches them to
``app.state.aaf`` for request handlers to consume via
:func:`backend.core.app_state.get_app_state`.

Startup order (matters for shutdown — reversed):

1. Resolve Settings
2. Pick an LLM provider (falls back to ``mock`` if credentials absent)
3. Build a :class:`MemoryBundle` through :class:`MemoryFactory`
4. Attach both to :class:`AppState`

Shutdown runs ``memory_factory.aclose()`` to close Redis / SQL engines.

Trust store: we inject the host OS trust store via the ``truststore``
package as the very first action in this module. This makes outbound
HTTPS calls (httpx, urllib, requests) honour macOS Keychain / Windows
cert store / Linux system CA roots automatically — important for users
behind a corporate or split-tunnel TLS-MITM proxy whose root CA only
lives in the OS trust store, not in ``certifi``'s bundle. Failing
silently (try/except) keeps the framework bootable on machines where
``truststore`` isn't installed (e.g. constrained CI images).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

try:
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:  # pragma: no cover - defensive: never fail to boot here
    _truststore = None  # type: ignore[assignment]

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import auth as auth_router
from backend.api.routers import documents as documents_router
from backend.api.routers import health as health_router
from backend.api.routers import heuristics as heuristics_router
from backend.api.routers import knowledge as knowledge_router
from backend.api.routers import manuscripts as manuscripts_router
from backend.api.routers import mcp as mcp_router
from backend.api.routers import memory as memory_router
from backend.api.routers import models as models_router
from backend.api.routers import planner as planner_router
from backend.api.routers import proposals as proposals_router
from backend.api.routers import settings as settings_router
from backend.api.routers import skills as skills_router
from backend.api.routers import tasks as tasks_router
from backend.api.routers import tools as tools_router
from backend.api.routers import workflows as workflows_router
from backend.core.app_state import AppState
from backend.core.auth.users import InMemoryUserStore, UserStore, YamlUserStore
from backend.core.errors import ConfigError, NotFoundError
from backend.core.llm.base import LLMProvider
from backend.core.llm.compactor import CompactingLLMProvider
from backend.core.llm.local_embedder import LocalSentenceTransformerEmbedder
from backend.core.llm.registry import default_registry
from backend.core.llm.router import build_routing_provider, load_routing_policy
from backend.core.runtime_config import RuntimeConfigStore, RuntimeProviderConfig
from backend.core.skill_host import SkillHost
from backend.core.skill_host.admin import SkillAdmin
from backend.manuscripts.bundle_storage import BundleStorage
from backend.manuscripts.sql_store import SqlManuscriptStore
from backend.manuscripts.store import InMemoryManuscriptStore, ManuscriptStore
from backend.memory.factory import MemoryFactory
from backend.proposals.store import (
    InMemoryProposalStore,
    ProposalStore,
    YamlProposalStore,
)
from backend.settings import Settings, get_settings
from backend.tasks.queue import TaskQueue, build_task_queue
from backend.tasks.runner import RunnerDeps
from backend.tasks.sql_store import SqlTaskStore
from backend.tasks.store import InMemoryTaskStore, TaskStore
from backend.tools.mcp_config import load_mcp_config
from backend.tools.mcp_loader import register_mcp_servers
from backend.tools.registry import ToolRegistry
from backend.tools.registry import build_default_registry as build_tools
from backend.workflows.registry import WorkflowRegistry
from backend.workflows.registry import build_default_registry as build_workflows

log = structlog.get_logger(__name__)

APP_VERSION = "0.1.0"


def _detect_system_proxy() -> str | None:
    """Detect system proxy. Returns proxy URL or None.

    Does NOT set global env vars (that would break httpx/DeepSeek).
    Callers use the returned URL to configure specific HTTP clients.
    """
    import os as _os

    # 1. Explicit config
    explicit = _os.environ.get("AAF_HTTPS_PROXY") or _os.environ.get("HTTPS_PROXY")
    if explicit:
        log.info("app.proxy.explicit", proxy=explicit[:50])
        return explicit

    # 2. Windows: read Internet Settings
    try:
        import winreg as _winreg
        try:
            key = _winreg.OpenKey(
                _winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            )
            enabled, _ = _winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = _winreg.QueryValueEx(key, "ProxyServer")
            _winreg.CloseKey(key)
        except OSError:
            enabled, server = 0, ""

        if enabled and server:
            proxy = f"http://{server}"
            # Only set for urllib/requests (not httpx — DeepSeek must go direct)
            _os.environ["AIP_HTTPS_PROXY"] = proxy
            log.info("app.proxy.windows", server=server)
            return proxy
    except Exception:
        pass
    return None


def _build_llm(
    settings: Settings,
    *,
    runtime_override: RuntimeProviderConfig | None = None,
) -> LLMProvider:
    """Pick an LLM provider. Falls back to ``mock`` when credentials missing.

    The fallback is deliberate: the framework must boot in zero-credential
    environments (CI, demos, first run) so users can poke the API without
    configuring keys first.

    When ``runtime_override`` is supplied (typically loaded from
    ``data/runtime/provider.yaml`` by :class:`RuntimeConfigStore`), it
    takes precedence over the env-driven ``settings.default_llm_provider``
    and per-provider credential fields. This lets the frontend Settings
    panel hot-reload the active provider without editing dotfiles.

    When ``settings.model_routing_config`` points to an existing YAML file,
    we wrap the result in a :class:`RoutingLLMProvider` so workflows can
    call ``ctx.llm.for_route("reasoning")`` for per-task model selection.
    A malformed routing file is logged and silently ignored — the
    framework still boots on the single-provider path.
    """
    registry = default_registry()
    desired: str  # `Literal[...]` from runtime_override would make the else branch fail mypy
    if runtime_override is not None:
        desired = runtime_override.provider
        provider_cfg: dict[str, Any] = {
            "api_key": runtime_override.api_key,
            "base_url": runtime_override.base_url,
            "default_model": runtime_override.default_model,
            "timeout_s": runtime_override.timeout_s,
            "verify_ssl": getattr(runtime_override, "verify_ssl", True),
        }
    else:
        desired = settings.default_llm_provider
        if not settings.has_llm_credentials(desired):
            log.warning("app.llm.fallback_to_mock", desired=desired)
            desired = "mock"
        provider_cfg = settings.provider(desired).model_dump()

    if desired == "mock":
        base: LLMProvider = registry.get("mock", {})
    elif desired == "ollama":
        # Ollama doesn't need an API key; tolerate empty key gracefully.
        base = registry.get(desired, provider_cfg)
    elif not provider_cfg.get("api_key"):
        log.warning("app.llm.fallback_to_mock", desired=desired, reason="missing_api_key")
        base = registry.get("mock", {})
    else:
        base = registry.get(desired, provider_cfg)

    # Optional per-task routing: only activated when the YAML exists.
    # Boot must not abort just because an *optional* config file is broken,
    # so we narrowly catch the documented failure modes — config / lookup /
    # filesystem errors — and fall back to the single-provider path. The
    # full traceback is preserved via ``log.exception`` so operators can
    # debug instead of guessing.
    try:
        policy = load_routing_policy(settings.model_routing_config)
    except (ConfigError, OSError):
        log.exception(
            "app.llm.routing_disabled",
            path=str(settings.model_routing_config),
        )
        policy = None

    if policy is None:
        provider: LLMProvider = base
    else:
        try:
            router = build_routing_provider(policy, registry=registry)
        except (ConfigError, NotFoundError):
            log.exception(
                "app.llm.routing_build_failed",
                path=str(settings.model_routing_config),
            )
            provider = base
        else:
            log.info(
                "app.llm.routing_enabled",
                routes=router.route_names(),
                path=str(settings.model_routing_config),
            )
            provider = router

    # Optional auto-compaction wrapper sits OUTSIDE the routing wrapper —
    # so a workflow's `for_route(...)` call still works (CompactingLLMProvider
    # delegates `for_route` to its inner) and the compactor sees the full
    # message list before it gets dispatched to a route.
    if settings.autocompact_enabled:
        try:
            provider = CompactingLLMProvider(
                inner=provider,
                threshold=settings.autocompact_threshold,
                keep_recent_n=settings.autocompact_keep_recent_n,
                summariser_route=settings.autocompact_summariser_route,
            )
        except ValueError:
            log.exception("app.llm.autocompact_disabled_invalid_settings")
        else:
            log.info(
                "app.llm.autocompact_enabled",
                threshold=settings.autocompact_threshold,
                keep_recent_n=settings.autocompact_keep_recent_n,
                summariser_route=settings.autocompact_summariser_route,
            )
    return provider


def _build_embedder(settings: Settings, llm: LLMProvider) -> LLMProvider:
    """Pick the embedder used by the vector store + skill matcher.

    ``provider`` (default) reuses the chat ``llm`` so the embed/chat pair
    stays consistent (same vendor, same context). ``local`` swaps in
    :class:`LocalSentenceTransformerEmbedder` for fully-offline boot —
    useful when chat goes through Ollama / no API keys are available.

    A misconfigured local backend (sentence-transformers not installed)
    is **not** allowed to silently downgrade: the user explicitly asked
    for the offline embedder, so we surface a clear ConfigError instead
    of pretending everything is fine and falling back to whatever the
    chat LLM happens to do.
    """
    if settings.embedding_backend != "local":
        return llm
    cache = (
        str(settings.local_embedding_cache_folder)
        if settings.local_embedding_cache_folder
        else None
    )
    embedder = LocalSentenceTransformerEmbedder(
        model_name=settings.local_embedding_model,
        device=settings.local_embedding_device,
        cache_folder=cache,
    )
    log.info(
        "app.embedder.local",
        model=settings.local_embedding_model,
        device=settings.local_embedding_device,
    )
    return embedder


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)

    # P12.2 — log the *running* build's identity as the very first thing.
    # When a user reports "the bug I just fixed is still happening", the
    # answer almost always sits here: their backend is on an older sha.
    # Surfacing this on every startup makes that diagnosis trivial.
    from backend.core.build_info import BUILD_INFO

    log.info(
        "app.build.info",
        git_sha=BUILD_INFO.git_sha_short,
        git_sha_full=BUILD_INFO.git_sha,
        dirty=BUILD_INFO.git_dirty,
        commit_ts=BUILD_INFO.commit_ts,
        commit_subject=BUILD_INFO.commit_subject,
    )

    log.info(
        "app.tls.trust_store",
        injected=_truststore is not None,
    )

    _proxy = _detect_system_proxy()
    # arxiv opener reads these (doesn't affect httpx/DeepSeek)
    if _proxy:
        import os as _os2
        _os2.environ["AAF_HTTPS_PROXY"] = _proxy
        _os2.environ["AIP_HTTPS_PROXY"] = _proxy

    runtime_config_store = RuntimeConfigStore(settings.workdir)
    runtime_override = runtime_config_store.load()
    if runtime_override is not None:
        log.info(
            "app.llm.runtime_override",
            provider=runtime_override.provider,
            has_key=bool(runtime_override.api_key),
            path=str(runtime_config_store.path),
        )
    llm = _build_llm(settings, runtime_override=runtime_override)
    log.info("app.llm.ready", provider=getattr(llm, "name", "?"))

    embedder = _build_embedder(settings, llm)
    log.info("app.embedder.ready", provider=getattr(embedder, "name", "?"))

    factory = MemoryFactory(settings.memory_config(), embedder=embedder)
    bundle = await factory.build()
    log.info(
        "app.memory.ready",
        vector=type(bundle.vector).__name__,
        knowledge=type(bundle.knowledge).__name__,
        heuristic=type(bundle.heuristic).__name__,
        episodic=type(bundle.episodic).__name__,
        session=type(bundle.session).__name__,
    )

    tools: ToolRegistry = build_tools()
    log.info("app.tools.ready", count=len(tools.names()), tools=tools.names())

    # MCP servers — opt-in. Each server's tools land in `tools` under
    # the namespaced name `mcp__<server>__<remote>`. The exit stack owns
    # every connected client; closing it closes them in LIFO order.
    mcp_stack = AsyncExitStack()
    mcp_outcomes = await _maybe_register_mcp(settings, tools, mcp_stack)

    workflows: WorkflowRegistry = build_workflows()
    log.info(
        "app.workflows.ready",
        count=len(workflows.names()),
        workflows=workflows.names(),
    )

    task_store = await _build_task_store(settings)
    log.info("app.task_store.ready", kind=type(task_store).__name__)

    manuscripts = await _build_manuscript_store(settings)
    log.info("app.manuscripts.ready", kind=type(manuscripts).__name__)

    bundle_storage = _build_bundle_storage(settings)
    log.info(
        "app.bundle_storage.ready",
        root=str(bundle_storage.root),
        max_file_mb=settings.manuscript_max_file_mb,
        max_bundle_mb=settings.manuscript_max_bundle_mb,
    )

    users = await _build_user_store(settings)
    log.info(
        "app.users.ready",
        kind=type(users).__name__,
        count=await users.count(),
        auth_disabled=settings.auth_disabled,
    )

    skill_host = SkillHost.build(
        skills_root=settings.skills_root,
        workdir_root=settings.skill_workdir_root,
        embedder=embedder,
        embedding_model=settings.embedding_model,
        default_timeout_s=settings.skill_exec_timeout_s,
    )
    await skill_host.load()
    skill_admin = SkillAdmin(skill_host)
    log.info(
        "app.skill_host.ready",
        skills_root=str(settings.skills_root),
        skills_count=len(skill_host.list_skills()),
        disabled_count=len(skill_admin.list_disabled()),
    )

    proposals = await _build_proposal_store(settings)
    log.info("app.proposals.ready", kind=type(proposals).__name__)

    runner_deps = RunnerDeps(
        store=task_store,
        workflows=workflows,
        memory=bundle,
        llm=llm,
        tools=tools,
        manuscripts=manuscripts,
        bundle_storage=bundle_storage,
        skill_host=skill_host,
        settings=settings,
        default_budget_usd=settings.default_budget_usd,
        proposals=proposals,
        evolver_enabled=settings.evolver_enabled,
    )
    task_queue = await _build_task_queue(settings, runner_deps)
    log.info("app.task_queue.ready", kind=type(task_queue).__name__)

    state = AppState(
        settings=settings,
        memory=bundle,
        memory_factory=factory,
        llm=llm,
        tools=tools,
        workflows=workflows,
        task_store=task_store,
        task_queue=task_queue,
        manuscripts=manuscripts,
        bundle_storage=bundle_storage,
        users=users,
        skill_host=skill_host,
        skill_admin=skill_admin,
        proposals=proposals,
        runner_deps=runner_deps,
        runtime_config_store=runtime_config_store,
    )
    if mcp_outcomes:
        # Store outcomes + a reload closure for hot-reload
        async def _reload_mcp():
            nonlocal mcp_stack
            await mcp_stack.aclose()
            mcp_stack = AsyncExitStack()
            results = await _maybe_register_mcp(settings, tools, mcp_stack)
            new_outcomes = {"servers": len(results), "tools": sum(len(r.tools) for r in results if r.connected)}
            state.extras["mcp"] = {**new_outcomes, "_reload_fn": _reload_mcp, "servers_list": results}
            return new_outcomes

        state.extras["mcp"] = {
            "servers": len(mcp_outcomes),
            "tools": sum(len(r.tools) for r in mcp_outcomes if r.connected),
            "servers_list": mcp_outcomes,
            "_reload_fn": _reload_mcp,
        }
    app.state.aaf = state

    try:
        yield
    finally:
        log.info("app.shutdown.begin")
        try:
            await task_queue.close()
        except Exception:  # pragma: no cover - defensive
            log.exception("app.shutdown.task_queue")
        try:
            await task_store.close()
        except Exception:  # pragma: no cover
            log.exception("app.shutdown.task_store")
        try:
            await manuscripts.close()
        except Exception:  # pragma: no cover
            log.exception("app.shutdown.manuscripts")
        try:
            await users.close()
        except Exception:  # pragma: no cover
            log.exception("app.shutdown.users")
        try:
            await proposals.close()
        except Exception:  # pragma: no cover
            log.exception("app.shutdown.proposals")
        try:
            # Closes every MCP client connected during boot in LIFO order.
            await mcp_stack.aclose()
        except Exception:  # pragma: no cover - per-client errors are logged inside
            log.exception("app.shutdown.mcp")
        await factory.aclose()
        log.info("app.shutdown.done")


async def _maybe_register_mcp(
    settings: Settings,
    tools: ToolRegistry,
    stack: AsyncExitStack,
) -> list:
    """Connect MCP servers + register their tools when feature is on.

    Returns the list of :class:`MCPRegistration` outcomes (or an empty
    list when the feature is off / config file missing). Errors are
    logged and absorbed — a bad MCP config must never prevent the
    rest of the app from booting.
    """

    if not settings.mcp_enabled:
        return []
    try:
        configs = load_mcp_config(settings.mcp_config)
    except (ConfigError, OSError):
        log.exception("app.mcp.config_load_failed", path=str(settings.mcp_config))
        return []
    if not configs:
        log.info("app.mcp.no_servers", path=str(settings.mcp_config))
        return []
    outcomes = await register_mcp_servers(tools, configs, stack=stack)
    log.info(
        "app.mcp.ready",
        servers=len(outcomes),
        connected=sum(1 for o in outcomes if o.connected),
        total_tools=sum(len(o.tools) for o in outcomes),
    )
    return outcomes


async def _build_task_store(settings: Settings) -> TaskStore:
    kind = settings.task_store_backend
    if kind == "auto":
        kind = "sql" if settings.database_url else "inmemory"
    if kind == "sql":
        store = SqlTaskStore.from_url(settings.database_url)
        await store.init()
        return store
    return InMemoryTaskStore()


async def _build_manuscript_store(settings: Settings) -> ManuscriptStore:
    # Reuse the task store backend preference — same tradeoff (durable vs zero-dep).
    kind = settings.task_store_backend
    if kind == "auto":
        kind = "sql" if settings.database_url else "inmemory"
    if kind == "sql":
        store = SqlManuscriptStore.from_url(settings.database_url)
        await store.init()
        return store
    return InMemoryManuscriptStore()


def _build_bundle_storage(settings: Settings) -> BundleStorage:
    """Construct the manuscript :class:`BundleStorage` from settings.

    Synchronous: just resolves paths + caps. The directory is created
    lazily on first use (``BundleStorage.init_for``) so we don't pollute
    ``data/`` for installations that never touch bundles.
    """
    return BundleStorage(
        root=settings.manuscript_root.resolve(),
        max_file_bytes=settings.manuscript_max_file_mb * 1024 * 1024,
        max_bundle_bytes=settings.manuscript_max_bundle_mb * 1024 * 1024,
    )


async def _build_proposal_store(settings: Settings) -> ProposalStore:
    """Pick a ProposalStore. ``auto`` resolves to YAML (durable on disk).

    Tests construct ``InMemoryProposalStore`` directly via ``AppState``,
    bypassing this helper.
    """
    kind = settings.proposals_backend
    if kind == "auto":
        kind = "yaml"
    if kind == "yaml":
        store = YamlProposalStore(settings.proposals_dir)
        await store.init()
        return store
    return InMemoryProposalStore()


async def _build_user_store(settings: Settings) -> UserStore:
    """Pick a UserStore. YAML when a directory is configured, else in-memory.

    The YamlUserStore is intentionally simple — file-per-user — so admins
    can manage accounts with a text editor when the UI is offline.
    """
    if settings.users_dir:
        store: UserStore = YamlUserStore(settings.users_dir)
        await store.init()
        return store
    fallback = InMemoryUserStore()
    await fallback.init()
    return fallback


async def _build_task_queue(settings: Settings, deps: RunnerDeps) -> TaskQueue:
    kind = settings.task_queue_backend
    if kind == "auto":
        kind = "inmemory"
        if settings.redis_url:
            try:
                import arq  # noqa: F401
            except ImportError:
                kind = "inmemory"
            else:
                # Honour Redis URL only in production; dev usually runs
                # inmemory even with Redis available, to keep the API
                # self-contained. Explicit opt-in via env var.
                if settings.env == "production":
                    kind = "arq"
    return await build_task_queue(kind, deps=deps, redis_url=settings.redis_url)


def create_app(*, state: AppState | None = None) -> FastAPI:
    """Construct the FastAPI application.

    When ``state`` is provided (tests), the lifespan is skipped and the
    caller is responsible for wiring/tearing down the runtime singletons.
    """
    app = FastAPI(
        title="Academic Agent Framework",
        description="LLM-agnostic academic agent with a self-hosted skill runtime.",
        version=APP_VERSION,
        lifespan=lifespan if state is None else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    if state is not None:
        app.state.aaf = state

    app.include_router(health_router.router)
    app.include_router(auth_router.router)
    app.include_router(memory_router.router)
    app.include_router(manuscripts_router.router)
    app.include_router(knowledge_router.router)
    app.include_router(documents_router.router)
    app.include_router(heuristics_router.router)
    app.include_router(tasks_router.router)
    app.include_router(tools_router.router)
    app.include_router(mcp_router.router)
    app.include_router(workflows_router.router)
    app.include_router(models_router.router)
    app.include_router(skills_router.router)
    app.include_router(proposals_router.router)
    app.include_router(planner_router.router)
    app.include_router(settings_router.router)

    return app


def _configure_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        cache_logger_on_first_use=True,
    )


__all__ = ["APP_VERSION", "create_app", "lifespan"]
