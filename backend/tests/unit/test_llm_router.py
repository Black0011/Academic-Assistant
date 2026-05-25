"""Unit tests for :mod:`backend.core.llm.router`.

Cover:

* ``RoutingPolicy`` parsing (Pydantic model validation).
* ``_resolve_spec`` inheritance + ``api_key_env`` resolution.
* ``RoutingLLMProvider.for_route`` selects the correct sub-provider.
* Unknown route names degrade to default (no exception).
* Protocol-method delegation goes through the default provider.
* ``load_routing_policy`` round-trips a YAML file and returns ``None``
  when the file is missing.
* ``build_routing_provider`` produces real adapters from a custom
  registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.errors import ConfigError
from backend.core.llm.base import ChatMessage, collect_text
from backend.core.llm.mock import MockLLMProvider
from backend.core.llm.registry import LLMRegistry
from backend.core.llm.router import (
    RouteSpec,
    RoutingLLMProvider,
    RoutingPolicy,
    _resolve_spec,
    _RouteTaggedProvider,
    build_routing_provider,
    load_routing_policy,
)


def _registry_with_mocks() -> LLMRegistry:
    """A custom registry whose `mock` factory honours `default_model`."""

    reg = LLMRegistry()

    def _mock(cfg: dict) -> MockLLMProvider:
        return MockLLMProvider(default_model=cfg.get("default_model") or "mock-default")

    reg.register("mock", _mock)
    return reg


# ---------------------------------------------------------------------------
# RoutingPolicy + RouteSpec
# ---------------------------------------------------------------------------


def test_route_spec_defaults_blank() -> None:
    spec = RouteSpec()
    assert spec.provider == ""
    assert spec.model == ""
    assert spec.api_key == ""
    assert spec.api_key_env == ""
    assert spec.timeout_s is None


def test_routing_policy_validates_minimal_default() -> None:
    policy = RoutingPolicy.model_validate({"default": {"provider": "mock", "model": "m-1"}})
    assert policy.default.provider == "mock"
    assert policy.default.model == "m-1"
    assert policy.routes == {}


def test_routing_policy_accepts_routes() -> None:
    policy = RoutingPolicy.model_validate(
        {
            "default": {"provider": "mock", "model": "m-cheap"},
            "routes": {
                "reasoning": {"model": "m-strong"},
                "fast": {"model": "m-cheap"},
            },
        }
    )
    assert sorted(policy.routes) == ["fast", "reasoning"]
    assert policy.routes["reasoning"].model == "m-strong"


# ---------------------------------------------------------------------------
# _resolve_spec — inheritance + env-var resolution
# ---------------------------------------------------------------------------


def test_resolve_spec_inherits_blank_fields_from_default() -> None:
    default = RouteSpec(provider="mock", model="cheap", base_url="http://x", timeout_s=99)
    route = RouteSpec(model="strong")
    resolved = _resolve_spec(route, default)
    assert resolved.provider == "mock"
    assert resolved.model == "strong"
    assert resolved.base_url == "http://x"
    assert resolved.timeout_s == 99


def test_resolve_spec_route_overrides_default() -> None:
    default = RouteSpec(provider="mock", model="cheap", base_url="http://x")
    route = RouteSpec(provider="ollama", base_url="http://localhost:11434/v1", model="llama3")
    resolved = _resolve_spec(route, default)
    assert resolved.provider == "ollama"
    assert resolved.base_url == "http://localhost:11434/v1"


def test_resolve_spec_reads_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AAF_TEST_KEY", "sk-from-env")
    default = RouteSpec(provider="mock", model="m-1")
    route = RouteSpec(api_key_env="AAF_TEST_KEY")
    resolved = _resolve_spec(route, default)
    assert resolved.api_key == "sk-from-env"


def test_resolve_spec_route_env_takes_precedence_over_default_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AAF_TEST_KEY", "sk-route-env")
    default = RouteSpec(provider="mock", model="m-1", api_key="sk-default-literal")
    route = RouteSpec(api_key_env="AAF_TEST_KEY")
    resolved = _resolve_spec(route, default)
    assert resolved.api_key == "sk-route-env"


def test_resolve_spec_falls_back_to_default_api_key_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AAF_TEST_MISSING", raising=False)
    default = RouteSpec(provider="mock", model="m-1", api_key="sk-default")
    route = RouteSpec(api_key_env="AAF_TEST_MISSING")
    resolved = _resolve_spec(route, default)
    assert resolved.api_key == "sk-default"


# ---------------------------------------------------------------------------
# RoutingLLMProvider — for_route selection + Protocol delegation
# ---------------------------------------------------------------------------


def test_for_route_returns_default_when_name_blank_or_unknown() -> None:
    """Blank / None names ⇒ untagged default. Unknown names ⇒ tagged
    wrapper around default (so observability captures the *intent* even
    if the deployment hasn't defined that route yet)."""

    default_p = MockLLMProvider(default_model="m-default")
    other_p = MockLLMProvider(default_model="m-other")
    router = RoutingLLMProvider(
        default=default_p,
        routes={"reasoning": other_p},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="m-default")),
    )

    # Blank / None ⇒ raw default (no wrapper)
    assert router.for_route(None) is default_p
    assert router.for_route("") is default_p

    # Unknown name ⇒ tagged wrapper around default
    unknown = router.for_route("never-defined")
    assert isinstance(unknown, _RouteTaggedProvider)
    assert unknown.inner is default_p
    assert unknown.route == "never-defined"

    # Known name ⇒ tagged wrapper around the matching sub-provider
    reasoning = router.for_route("reasoning")
    assert isinstance(reasoning, _RouteTaggedProvider)
    assert reasoning.inner is other_p
    assert reasoning.route == "reasoning"


def test_route_names_lists_only_alternative_routes() -> None:
    default_p = MockLLMProvider()
    routes = {
        "reasoning": MockLLMProvider(default_model="r"),
        "fast": MockLLMProvider(default_model="f"),
    }
    router = RoutingLLMProvider(
        default=default_p,
        routes=routes,
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="m")),
    )
    assert router.route_names() == ["fast", "reasoning"]
    assert router.default_provider is default_p


@pytest.mark.asyncio
async def test_complete_delegates_to_default_provider() -> None:
    default_p = MockLLMProvider(default_model="m-default")
    default_p.queue_text("hi from default")
    other_p = MockLLMProvider(default_model="m-other")
    other_p.queue_text("hi from other")

    router = RoutingLLMProvider(
        default=default_p,
        routes={"reasoning": other_p},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="m-default")),
    )

    text, _, _ = await collect_text(
        await router.complete([ChatMessage(role="user", content="ping")])
    )
    assert text == "hi from default"
    # Default consumed; other untouched.
    assert default_p.remaining() == 0
    assert other_p.remaining() == 1


@pytest.mark.asyncio
async def test_for_route_complete_uses_route_provider() -> None:
    default_p = MockLLMProvider(default_model="m-default")
    default_p.queue_text("default-resp")
    reasoning_p = MockLLMProvider(default_model="m-reasoning")
    reasoning_p.queue_text("reasoning-resp")

    router = RoutingLLMProvider(
        default=default_p,
        routes={"reasoning": reasoning_p},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="m-default")),
    )

    text, _, _ = await collect_text(
        await router.for_route("reasoning").complete([ChatMessage(role="user", content="solve")])
    )
    assert text == "reasoning-resp"
    assert default_p.remaining() == 1
    assert reasoning_p.remaining() == 0


def test_protocol_helpers_delegate_to_default() -> None:
    default_p = MockLLMProvider(default_model="m-default", context_window=4096)
    other_p = MockLLMProvider(default_model="m-other", context_window=99999)
    router = RoutingLLMProvider(
        default=default_p,
        routes={"x": other_p},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="m-default")),
    )
    assert router.context_window("any") == 4096
    assert router.supports_tools() is True
    assert router.supports_streaming() is True
    assert router.name == "router"


# ---------------------------------------------------------------------------
# load_routing_policy / build_routing_provider — file + registry round trips
# ---------------------------------------------------------------------------


def test_load_routing_policy_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_routing_policy(tmp_path / "absent.yaml") is None


def test_load_routing_policy_parses_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "routing.yaml"
    cfg.write_text(
        """
default:
  provider: mock
  model: cheap
routes:
  reasoning:
    model: strong
  fast:
    model: cheap
""".lstrip(),
        encoding="utf-8",
    )
    policy = load_routing_policy(cfg)
    assert policy is not None
    assert policy.default.model == "cheap"
    assert sorted(policy.routes) == ["fast", "reasoning"]
    assert policy.routes["reasoning"].model == "strong"


def test_load_routing_policy_rejects_non_mapping(tmp_path: Path) -> None:
    cfg = tmp_path / "broken.yaml"
    cfg.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_routing_policy(cfg)
    assert "must be a YAML mapping" in str(excinfo.value)


def test_load_routing_policy_rejects_invalid_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "broken.yaml"
    # Unbalanced bracket → yaml.YAMLError → re-raised as ConfigError.
    cfg.write_text("default: [unterminated", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_routing_policy(cfg)
    assert "is not valid YAML" in str(excinfo.value)


def test_load_routing_policy_rejects_schema_mismatch(tmp_path: Path) -> None:
    cfg = tmp_path / "broken.yaml"
    # Missing required `default` field → pydantic ValidationError → ConfigError.
    cfg.write_text("routes:\n  reasoning:\n    model: r1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_routing_policy(cfg)
    assert "schema validation" in str(excinfo.value)


def test_build_routing_provider_uses_custom_registry() -> None:
    reg = _registry_with_mocks()
    policy = RoutingPolicy.model_validate(
        {
            "default": {"provider": "mock", "model": "m-cheap"},
            "routes": {"reasoning": {"model": "m-strong"}},
        }
    )
    router = build_routing_provider(policy, registry=reg)
    assert isinstance(router.default_provider, MockLLMProvider)
    assert router.default_provider.default_model == "m-cheap"
    reasoning = router.for_route("reasoning")
    assert isinstance(reasoning, _RouteTaggedProvider)
    inner = reasoning.inner
    assert isinstance(inner, MockLLMProvider)
    assert inner.default_model == "m-strong"
    assert reasoning.route == "reasoning"


@pytest.mark.asyncio
async def test_build_routing_provider_round_trip(tmp_path: Path) -> None:
    cfg = tmp_path / "routing.yaml"
    cfg.write_text(
        """
default:
  provider: mock
  model: cheap
routes:
  reasoning:
    model: strong
""".lstrip(),
        encoding="utf-8",
    )
    policy = load_routing_policy(cfg)
    assert policy is not None
    reg = _registry_with_mocks()
    router = build_routing_provider(policy, registry=reg)

    cheap = router.default_provider
    strong_wrapper = router.for_route("reasoning")
    assert isinstance(cheap, MockLLMProvider) and cheap.default_model == "cheap"
    assert isinstance(strong_wrapper, _RouteTaggedProvider)
    strong = strong_wrapper.inner
    assert isinstance(strong, MockLLMProvider) and strong.default_model == "strong"

    # Wire and exercise both providers to prove the right model name is
    # surfaced on each call.
    cheap.queue_text("cheap-said")
    strong.queue_text("strong-said")

    cheap_text, _, _ = await collect_text(
        await router.complete([ChatMessage(role="user", content="hi")])
    )
    strong_text, _, _ = await collect_text(
        await router.for_route("reasoning").complete([ChatMessage(role="user", content="hi")])
    )
    assert cheap_text == "cheap-said"
    assert strong_text == "strong-said"
    assert cheap.calls[0]["model"] == "cheap"
    assert strong.calls[0]["model"] == "strong"


# ---------------------------------------------------------------------------
# _RouteTaggedProvider — telemetry route propagation end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_tagged_provider_propagates_route_to_telemetry() -> None:
    """A complete() call made via for_route('reasoning') must produce a
    telemetry Record whose .route == 'reasoning'."""

    from backend.core.llm.telemetry import recorder

    recorder().reset()
    default_p = MockLLMProvider(default_model="cheap")
    default_p.queue_text("cheap-resp")
    reasoning_p = MockLLMProvider(default_model="strong")
    reasoning_p.queue_text("strong-resp")

    router = RoutingLLMProvider(
        default=default_p,
        routes={"reasoning": reasoning_p},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="cheap")),
    )

    # Default path (no route) → record.route should be None.
    await collect_text(await router.complete([ChatMessage(role="user", content="x")]))
    # Reasoning path → record.route should be "reasoning".
    await collect_text(
        await router.for_route("reasoning").complete([ChatMessage(role="user", content="y")])
    )

    records = recorder().records()
    assert len(records) == 2
    assert records[0].route is None
    assert records[0].model == "cheap"
    assert records[1].route == "reasoning"
    assert records[1].model == "strong"


@pytest.mark.asyncio
async def test_route_tagged_provider_resets_contextvar_after_complete() -> None:
    """The route contextvar must not leak past the streaming generator."""

    from backend.core.llm.telemetry import active_route

    inner = MockLLMProvider(default_model="m1")
    inner.queue_text("ok")
    router = RoutingLLMProvider(
        default=inner,
        routes={"reasoning": inner},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="m1")),
    )

    await collect_text(
        await router.for_route("reasoning").complete([ChatMessage(role="user", content="ping")])
    )
    # Even though we ran inside a tagged context, after the stream
    # completes the contextvar must be back to its default.
    assert active_route() is None


def test_route_tagged_provider_delegates_protocol_helpers() -> None:
    inner = MockLLMProvider(default_model="m", context_window=12345)
    wrapper = _RouteTaggedProvider(inner=inner, route="reasoning")
    assert wrapper.context_window("any") == 12345
    assert wrapper.supports_tools() is inner.supports_tools()
    assert wrapper.supports_streaming() is inner.supports_streaming()
    assert wrapper.name == "router.route"
