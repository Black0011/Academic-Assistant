"""Runtime settings endpoints — currently exposes the LLM provider config.

The single resource here is ``GET / PUT / DELETE /api/settings/llm`` plus a
``POST /api/settings/llm:test`` probe endpoint. Together they let the
frontend Settings panel:

* read the active provider (api_key returned masked, never raw),
* swap to a new provider on the fly (writes to
  ``data/runtime/provider.yaml`` and rebuilds ``app.state.aaf.llm``),
* validate a candidate config before committing (one tiny ``complete``
  call against the candidate provider),
* clear the override and fall back to env / mock.

Hard rules (covered by ``backend/tests/integration/test_app_settings.py``):

* The raw ``api_key`` never leaves the process. Every response uses
  :func:`backend.core.runtime_config.mask_api_key`.
* Hot-reload swaps both ``state.llm`` and ``state.runner_deps.llm`` so
  newly-enqueued tasks pick up the change immediately. In-flight tasks
  keep using the provider they captured on ``WorkflowContext`` — that
  matches the documented isolation invariant in
  ``docs/runtime-internals.md`` §2.
* ARQ workers run in a separate process; they re-read env at boot and
  do **not** observe runtime overrides written here. This is documented
  on the response shape via ``warns_arq_worker``.
* The endpoints are admin-gated when auth is enabled; in
  ``auth_disabled`` mode every caller passes (single-user laptop preset).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.core.app_state import AppState, get_app_state
from backend.core.auth.dependencies import current_user
from backend.core.auth.models import User
from backend.core.errors import ConfigError, NotFoundError
from backend.core.llm.base import ChatMessage, LLMProvider
from backend.core.llm.registry import default_registry
from backend.core.runtime_config import (
    MaskedProviderView,
    RuntimeConfigStore,
    RuntimeProviderConfig,
    available_providers,
    mask_api_key,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def require_admin_or_open_mode(
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> User:
    """Admin-gate runtime mutation. Pass-through under ``auth_disabled``."""

    settings = state.settings
    if settings is not None and settings.auth_disabled:
        return user
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


# ---------------------------------------------------------------------------
# Response / request shapes
# ---------------------------------------------------------------------------


class LLMProviderResponse(BaseModel):
    """API-safe view of the active default provider."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., description="Provider name (openai / anthropic / ollama / mock).")
    api_key_masked: str = Field(..., description='Display-only. Format: "sk-…XXXX" or "—".')
    api_key_set: bool = Field(..., description="True when a non-empty key is stored.")
    base_url: str = ""
    default_model: str = ""
    timeout_s: int = 120
    source: Literal["runtime", "env"] = Field(
        ...,
        description=(
            '"runtime" = read from data/runtime/provider.yaml; "env" = no override, env-only.'
        ),
    )
    warns_arq_worker: bool = Field(
        False,
        description=(
            "True when an ARQ worker would not pick up runtime overrides "
            "(separate process). The frontend should warn the user."
        ),
    )

    @classmethod
    def from_view(cls, view: MaskedProviderView, *, warns_arq_worker: bool) -> LLMProviderResponse:
        return cls(
            provider=view.provider,
            api_key_masked=view.api_key_masked,
            api_key_set=view.api_key_set,
            base_url=view.base_url,
            default_model=view.default_model,
            timeout_s=view.timeout_s,
            source=view.source,
            warns_arq_worker=warns_arq_worker,
        )


class LLMProviderInput(BaseModel):
    """PUT body — partial update with explicit "keep current key" semantics.

    ``api_key == ""`` means "leave the stored key alone" (the frontend
    only sees the masked value, so it must be possible to PUT without
    re-entering the key on every save). ``api_key == None`` is forbidden
    by the type, so the contract stays unambiguous.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "anthropic", "ollama", "mock"]
    api_key: str = Field("", description="Empty string ⇒ keep current. Non-empty ⇒ replace.")
    base_url: str = ""
    default_model: str = ""
    timeout_s: int = Field(120, ge=1, le=600)


class LLMTestResponse(BaseModel):
    """Result of a candidate-config probe."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    provider: str
    model: str
    latency_ms: int
    error: str | None = None


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str] = Field(..., description="Whitelisted provider names for the UI dropdown.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_store(state: AppState) -> RuntimeConfigStore:
    store = state.runtime_config_store
    if store is None:
        raise HTTPException(status_code=503, detail="runtime config subsystem not ready")
    return store


def _current_view(state: AppState) -> MaskedProviderView:
    """Compose the masked view from runtime override (if any) or env."""

    store = _require_store(state)
    settings = state.settings
    runtime = store.load() if store.exists() else None
    if runtime is not None:
        return MaskedProviderView(
            provider=runtime.provider,
            api_key_masked=mask_api_key(runtime.api_key),
            api_key_set=bool(runtime.api_key),
            base_url=runtime.base_url,
            default_model=runtime.default_model,
            timeout_s=runtime.timeout_s,
            source="runtime",
        )
    # Env-only path: read from settings via existing provider() helper.
    if settings is None:
        return MaskedProviderView(
            provider="mock",
            api_key_masked="—",
            api_key_set=False,
            base_url="",
            default_model="",
            timeout_s=120,
            source="env",
        )
    name = settings.default_llm_provider
    cfg = settings.provider(name)
    return MaskedProviderView(
        provider=name,
        api_key_masked=mask_api_key(cfg.api_key),
        api_key_set=bool(cfg.api_key),
        base_url=cfg.base_url,
        default_model=cfg.default_model,
        timeout_s=cfg.timeout_s,
        source="env",
    )


def _arq_worker_warning(state: AppState) -> bool:
    """True when there's a separate-process worker that won't see overrides."""

    queue = state.task_queue
    return bool(queue is not None and type(queue).__name__ == "ArqTaskQueue")


def _resolve_input(state: AppState, payload: LLMProviderInput) -> RuntimeProviderConfig:
    """Apply the "empty api_key ⇒ keep current" rule and return final config."""

    api_key = payload.api_key
    if not api_key:
        view = _current_view(state)
        # Only inherit when the *same* provider is already configured;
        # switching provider always requires a fresh key entry.
        if view.provider == payload.provider:
            store = _require_store(state)
            existing = store.load()
            if existing is not None and existing.api_key:
                api_key = existing.api_key
            elif view.source == "env" and state.settings is not None:
                env_key = state.settings.provider(payload.provider).api_key
                api_key = env_key
    return RuntimeProviderConfig(
        provider=payload.provider,
        api_key=api_key,
        base_url=payload.base_url,
        default_model=payload.default_model,
        timeout_s=payload.timeout_s,
    )


def _build_candidate_provider(config: RuntimeProviderConfig) -> LLMProvider:
    """Construct a one-shot provider from a candidate config (no side effects)."""

    registry = default_registry()
    if config.provider == "mock":
        return registry.get("mock", {})
    cfg: dict[str, Any] = {
        "api_key": config.api_key,
        "base_url": config.base_url,
        "default_model": config.default_model,
        "timeout_s": config.timeout_s,
    }
    return registry.get(config.provider, cfg)


async def _probe(provider: LLMProvider, model: str | None) -> tuple[int, str | None]:
    """Send the smallest possible completion. Returns (latency_ms, error)."""

    import time

    started = time.monotonic()
    try:
        stream = await provider.complete(
            [ChatMessage(role="user", content="ping")],
            model=model,
            temperature=0.0,
            max_tokens=4,
            stream=False,
        )
        async for chunk in stream:
            if chunk.type == "error":
                return int((time.monotonic() - started) * 1000), chunk.error or "error"
            if chunk.type == "done":
                break
    except Exception as exc:
        # The probe is the explicit error boundary for "is the user's key
        # any good?" — narrowing this except would force us to enumerate
        # every adapter's error type and would defeat the point of a
        # single user-friendly diagnostic.
        return int((time.monotonic() - started) * 1000), f"{type(exc).__name__}: {exc}"
    return int((time.monotonic() - started) * 1000), None


def _hot_reload(state: AppState, runtime: RuntimeProviderConfig | None) -> LLMProvider:
    """Rebuild ``state.llm`` (and ``runner_deps.llm``) using *runtime*.

    The compactor / routing wrappers still apply because we go through
    the same ``_build_llm`` path the lifespan uses.
    """

    # Lazy import keeps test envs that swap out app.py functional.
    from backend.app import _build_llm

    if state.settings is None:
        raise HTTPException(status_code=503, detail="settings subsystem not ready")
    new_llm = _build_llm(state.settings, runtime_override=runtime)
    state.llm = new_llm
    if state.runner_deps is not None:
        state.runner_deps.llm = new_llm
    log.info(
        "settings.llm.hot_reloaded",
        provider=runtime.provider if runtime else state.settings.default_llm_provider,
        source="runtime" if runtime else "env",
    )
    return new_llm


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/llm/providers",
    response_model=ProvidersResponse,
    summary="List provider names the frontend may pick from",
)
async def list_providers() -> ProvidersResponse:
    return ProvidersResponse(items=available_providers())


@router.get(
    "/llm",
    response_model=LLMProviderResponse,
    summary="Read the active default LLM provider config (api_key masked)",
)
async def get_llm(
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> LLMProviderResponse:
    view = _current_view(state)
    return LLMProviderResponse.from_view(view, warns_arq_worker=_arq_worker_warning(state))


@router.put(
    "/llm",
    response_model=LLMProviderResponse,
    summary="Save the active default LLM provider config (persists + hot-reloads)",
)
async def put_llm(
    payload: LLMProviderInput,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
) -> LLMProviderResponse:
    store = _require_store(state)
    runtime = _resolve_input(state, payload)
    if runtime.provider != "mock" and runtime.provider != "ollama" and not runtime.api_key:
        raise HTTPException(
            status_code=400,
            detail=f"provider {runtime.provider!r} requires an api_key",
        )
    try:
        store.save(runtime)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"persist failed: {exc}") from exc
    try:
        _hot_reload(state, runtime)
    except (ConfigError, NotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LLMProviderResponse.from_view(
        _current_view(state),
        warns_arq_worker=_arq_worker_warning(state),
    )


@router.delete(
    "/llm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear the runtime override and fall back to env-only config",
)
async def delete_llm(
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
) -> Response:
    store = _require_store(state)
    store.clear()
    try:
        _hot_reload(state, None)
    except (ConfigError, NotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/llm:test",
    response_model=LLMTestResponse,
    summary="Probe a candidate config without saving it",
)
async def test_llm(
    payload: LLMProviderInput,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
) -> LLMTestResponse:
    candidate = _resolve_input(state, payload)
    if candidate.provider != "mock" and candidate.provider != "ollama" and not candidate.api_key:
        return LLMTestResponse(
            ok=False,
            provider=candidate.provider,
            model=candidate.default_model,
            latency_ms=0,
            error=f"{candidate.provider!r} requires an api_key",
        )
    try:
        provider = _build_candidate_provider(candidate)
    except (ConfigError, NotFoundError) as exc:
        return LLMTestResponse(
            ok=False,
            provider=candidate.provider,
            model=candidate.default_model,
            latency_ms=0,
            error=str(exc),
        )
    latency, error = await _probe(provider, candidate.default_model or None)
    return LLMTestResponse(
        ok=error is None,
        provider=candidate.provider,
        model=candidate.default_model,
        latency_ms=latency,
        error=error,
    )


__all__ = ["router"]
