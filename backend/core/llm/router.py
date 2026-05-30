"""Task-level model routing.

The :class:`RoutingLLMProvider` wraps multiple :class:`LLMProvider`
instances and exposes :meth:`for_route` so callers can pick a different
provider/model per request without changing the public Protocol.

Default behaviour is **identical to the underlying default provider** —
existing workflows that don't know about routing keep working untouched.
Workflows that want routing call::

    provider = ctx.llm.for_route("reasoning")  # or "fast", "local", ...
    async for chunk in await provider.complete(messages):
        ...

Configuration lives in a YAML file (default ``./config/model_routing.yaml``)
shaped like::

    default:
      provider: openai
      api_key_env: DEEPSEEK_API_KEY
      base_url: https://api.deepseek.com/v1
      model: deepseek-chat
    routes:
      reasoning:
        model: deepseek-reasoner       # inherits provider/api_key/base_url
      fast:
        model: deepseek-chat
      local:
        provider: ollama
        base_url: http://localhost:11434/v1
        model: llama3.1:8b

When the YAML file is absent, ``load_routing_policy`` returns ``None`` —
the framework then keeps using the single-provider path from
``backend.app._build_llm`` so zero-config setups stay zero-config.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.errors import ConfigError

from .base import (
    ChatMessage,
    CompletionChunk,
    CostEstimate,
    LLMProvider,
    ToolSpec,
)
from .registry import LLMRegistry, default_registry
from .telemetry import reset_active_route, set_active_route

# ---------------------------------------------------------------------------
# Policy models
# ---------------------------------------------------------------------------


class RouteSpec(BaseModel):
    """One route's provider+model configuration.

    Empty string fields mean "inherit from default". ``api_key_env`` is
    read from the process environment at build time and takes precedence
    over a literal ``api_key``.
    """

    model_config = ConfigDict(extra="ignore")

    provider: str = ""
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    timeout_s: int | None = None


class RoutingPolicy(BaseModel):
    """Default route + named alternative routes."""

    model_config = ConfigDict(extra="ignore")

    default: RouteSpec
    routes: dict[str, RouteSpec] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class RoutingLLMProvider:
    """Multi-provider router that satisfies the :class:`LLMProvider` Protocol.

    The router itself proxies all Protocol methods to the **default**
    provider, so dropping it into ``app.state.aaf.llm`` is fully
    backward-compatible. Callers wanting a different model on a given
    request use :meth:`for_route` to fetch the right sub-provider.
    """

    name = "router"

    def __init__(
        self,
        *,
        default: LLMProvider,
        # Mapping (not dict): callers commonly construct
        # ``{"reasoning": MockLLMProvider(), ...}`` — `dict` is invariant in
        # its value type, so accepting Mapping[str, LLMProvider] lets a
        # ``dict[str, MockLLMProvider]`` (Protocol-conformant) flow in
        # without an explicit cast.
        routes: Mapping[str, LLMProvider],
        policy: RoutingPolicy,
    ) -> None:
        self._default = default
        self._routes: dict[str, LLMProvider] = dict(routes)
        self.policy = policy

    # ---- introspection ------------------------------------------------

    @property
    def default_provider(self) -> LLMProvider:
        return self._default

    def route_names(self) -> list[str]:
        """Sorted list of named alternative routes (excludes the default)."""
        return sorted(self._routes)

    def for_route(self, name: str | None) -> LLMProvider:
        """Return the provider for ``name``, falling back to default.

        * Blank / ``None`` ⇒ untagged default provider (no telemetry tag).
        * Known route name ⇒ wrapper that tags every ``record(...)`` made
          by the inner adapter with this route via the
          :data:`backend.core.llm.telemetry._ACTIVE_ROUTE` contextvar.
        * Unknown route name ⇒ degrade to a tagged wrapper around the
          default provider (so observability still shows "the workflow
          asked for X" even when the deployment doesn't define X).
        """
        if not name:
            return self._default
        inner = self._routes.get(name, self._default)
        return _RouteTaggedProvider(inner=inner, route=name)

    # ---- LLMProvider Protocol — delegates to default -------------------

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
        return await self._default.complete(
            messages,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        return await self._default.embed(texts, model=model)

    def supports_tools(self) -> bool:
        return self._default.supports_tools()

    def supports_streaming(self) -> bool:
        return self._default.supports_streaming()

    def context_window(self, model: str) -> int:
        return self._default.context_window(model)

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate:
        return await self._default.estimate_cost(messages, model=model)


# ---------------------------------------------------------------------------
# Route-tagged sub-provider
# ---------------------------------------------------------------------------


class _RouteTaggedProvider:
    """Thin wrapper that tags telemetry with the active route name.

    Adapters (``openai_compat``, ``anthropic``, ``mock``, …) already emit
    ``backend.core.llm.telemetry.record(...)`` themselves. To label those
    records with the workflow-declared route without changing every
    adapter, we set a contextvar around the inner ``complete()`` call;
    :func:`backend.core.llm.telemetry.record` reads it as a default for
    its ``route`` argument.

    The wrapper itself satisfies the ``LLMProvider`` Protocol so callers
    can ``await provider.complete(...)`` exactly as before.
    """

    name = "router.route"

    def __init__(self, *, inner: LLMProvider, route: str) -> None:
        self._inner = inner
        self._route = route

    @property
    def inner(self) -> LLMProvider:
        return self._inner

    @property
    def route(self) -> str:
        return self._route

    # ---- LLMProvider Protocol ----------------------------------------

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
        return self._tagged_stream(
            messages,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    async def _tagged_stream(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
    ) -> AsyncIterator[CompletionChunk]:
        token = set_active_route(self._route)
        try:
            inner_stream = await self._inner.complete(
                messages,
                tools=tools,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
            )
            async for chunk in inner_stream:
                yield chunk
        finally:
            reset_active_route(token)

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        token = set_active_route(self._route)
        try:
            return await self._inner.embed(texts, model=model)
        finally:
            reset_active_route(token)

    def supports_tools(self) -> bool:
        return self._inner.supports_tools()

    def supports_streaming(self) -> bool:
        return self._inner.supports_streaming()

    def context_window(self, model: str) -> int:
        return self._inner.context_window(model)

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate:
        return await self._inner.estimate_cost(messages, model=model)


# ---------------------------------------------------------------------------
# Builder + loader
# ---------------------------------------------------------------------------


def _resolve_spec(spec: RouteSpec, default: RouteSpec) -> RouteSpec:
    """Fill blank fields from default and resolve api_key from env vars.

    The api_key resolution order is:
      1. spec.api_key_env (process env at build time)
      2. spec.api_key (literal)
      3. default.api_key_env (process env at build time)
      4. default.api_key (literal)
    """

    api_key = ""
    if spec.api_key_env:
        api_key = os.environ.get(spec.api_key_env, "") or api_key
    if not api_key:
        api_key = spec.api_key
    if not api_key and default.api_key_env:
        api_key = os.environ.get(default.api_key_env, "") or api_key
    if not api_key:
        api_key = default.api_key

    return RouteSpec(
        provider=spec.provider or default.provider,
        model=spec.model or default.model,
        base_url=spec.base_url or default.base_url,
        api_key=api_key,
        api_key_env=spec.api_key_env or default.api_key_env,
        timeout_s=spec.timeout_s if spec.timeout_s is not None else default.timeout_s,
    )


def _make_provider(registry: LLMRegistry, spec: RouteSpec) -> LLMProvider:
    """Construct a single provider from a fully-resolved RouteSpec."""

    # Any: provider factories accept arbitrary kwargs at the registry boundary
    # (api_key / base_url / default_model / timeout_s / vendor-specific knobs).
    # Each factory in `register_defaults` validates its own subset internally;
    # we only assemble the dict here.
    cfg: dict[str, Any] = {}
    if spec.api_key:
        cfg["api_key"] = spec.api_key
    if spec.base_url:
        cfg["base_url"] = spec.base_url
    if spec.model:
        cfg["default_model"] = spec.model
    if spec.timeout_s is not None:
        cfg["timeout_s"] = spec.timeout_s
    return registry.get(spec.provider or "openai", cfg)


def build_routing_provider(
    policy: RoutingPolicy,
    *,
    registry: LLMRegistry | None = None,
) -> RoutingLLMProvider:
    """Construct a :class:`RoutingLLMProvider` from a policy + registry.

    Each route inherits from the default; missing fields are filled in,
    and ``api_key_env`` is resolved against ``os.environ``.
    """

    reg = registry or default_registry()
    default_spec = _resolve_spec(policy.default, policy.default)
    default_provider = _make_provider(reg, default_spec)

    routes: dict[str, LLMProvider] = {}
    for name, spec in policy.routes.items():
        resolved = _resolve_spec(spec, default_spec)
        routes[name] = _make_provider(reg, resolved)

    return RoutingLLMProvider(default=default_provider, routes=routes, policy=policy)


def load_routing_policy(path: Path) -> RoutingPolicy | None:
    """Load a YAML routing policy, or return ``None`` if the file is absent.

    Any malformed input (bad YAML, non-mapping root, failed pydantic
    validation) surfaces as a :class:`backend.core.errors.ConfigError` so
    the boot path in ``backend.app._build_llm`` can catch a single error
    type and fall back to the single-provider mode while preserving the
    full traceback via ``log.exception``.
    """

    if not Path(path).is_file():
        return None
    import yaml

    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"routing policy at {path} is not valid YAML",
            path=str(path),
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            f"routing policy at {path} must be a YAML mapping",
            path=str(path),
        )
    try:
        return RoutingPolicy.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            f"routing policy at {path} failed schema validation",
            path=str(path),
        ) from exc


__all__ = [
    "RouteSpec",
    "RoutingLLMProvider",
    "RoutingPolicy",
    "_RouteTaggedProvider",  # exposed for tests + observability tooling
    "build_routing_provider",
    "load_routing_policy",
]
