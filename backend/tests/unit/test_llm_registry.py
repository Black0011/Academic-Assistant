import pytest

from backend.core.errors import ConfigError, NotFoundError
from backend.core.llm import (
    AnthropicProvider,
    LLMRegistry,
    MockLLMProvider,
    OpenAICompatProvider,
    default_registry,
    register_defaults,
)


def test_default_registry_has_builtins():
    reg = default_registry()
    assert set(reg.names()) >= {"openai", "anthropic", "mock", "ollama"}


def test_get_openai_returns_correct_type():
    reg = default_registry()
    p = reg.get("openai", {"api_key": "x"})
    assert isinstance(p, OpenAICompatProvider)
    assert p.name == "openai"


def test_get_anthropic_returns_correct_type():
    reg = default_registry()
    p = reg.get("anthropic", {"api_key": "x"})
    assert isinstance(p, AnthropicProvider)
    assert p.name == "anthropic"


def test_get_mock_returns_mock():
    reg = default_registry()
    p = reg.get("mock", {})
    assert isinstance(p, MockLLMProvider)


def test_get_unknown_raises():
    reg = default_registry()
    with pytest.raises(NotFoundError):
        reg.get("fictional_provider")


def test_register_duplicate_raises():
    reg = LLMRegistry()
    reg.register("x", lambda cfg: MockLLMProvider())
    with pytest.raises(ConfigError):
        reg.register("x", lambda cfg: MockLLMProvider())


def test_register_custom_factory():
    reg = LLMRegistry()
    register_defaults(reg)
    reg.register(
        "custom", lambda cfg: MockLLMProvider(default_model=cfg.get("default_model", "custom-1"))
    )
    p = reg.get("custom", {"default_model": "zzz-7b"})
    assert isinstance(p, MockLLMProvider)
    assert p.default_model == "zzz-7b"


def test_unregister():
    reg = LLMRegistry()
    register_defaults(reg)
    assert reg.has("openai")
    reg.unregister("openai")
    assert not reg.has("openai")


def test_ollama_uses_openai_compat():
    reg = default_registry()
    p = reg.get("ollama", {})
    assert isinstance(p, OpenAICompatProvider)
    assert p.name == "ollama"
