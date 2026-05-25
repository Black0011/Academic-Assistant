"""Provider registry.

`LLMRegistry.register(name, factory)` binds a short identifier to a
factory function `(config: dict) -> LLMProvider`.

`LLMRegistry.get(name, config)` returns a freshly-constructed provider;
the caller is responsible for reusing/closing it.

Built-in providers (openai, anthropic, ollama, mock) are registered by
`register_defaults(registry)`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.core.errors import ConfigError, NotFoundError

from .base import LLMProvider

Factory = Callable[[dict[str, Any]], LLMProvider]


class LLMRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Factory] = {}

    def register(self, name: str, factory: Factory) -> None:
        if name in self._factories:
            raise ConfigError(f"LLM provider '{name}' already registered")
        self._factories[name] = factory

    def unregister(self, name: str) -> None:
        self._factories.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._factories)

    def has(self, name: str) -> bool:
        return name in self._factories

    def get(self, name: str, config: dict[str, Any] | None = None) -> LLMProvider:
        factory = self._factories.get(name)
        if factory is None:
            raise NotFoundError(f"LLM provider '{name}' is not registered", available=self.names())
        return factory(config or {})


def register_defaults(reg: LLMRegistry) -> None:
    """Register the four built-in providers. Idempotent if called twice only
    with a fresh registry."""

    from .anthropic import AnthropicProvider
    from .mock import MockLLMProvider
    from .openai_compat import OpenAICompatProvider

    def _openai(cfg: dict[str, Any]) -> LLMProvider:
        return OpenAICompatProvider(
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url") or "https://api.openai.com/v1",
            default_model=cfg.get("default_model") or "gpt-4o-mini",
            timeout_s=float(cfg.get("timeout_s") or 120.0),
            verify_ssl=bool(cfg.get("verify_ssl", True)),
            name="openai",
        )

    def _ollama(cfg: dict[str, Any]) -> LLMProvider:
        return OpenAICompatProvider(
            api_key=cfg.get("api_key", "") or "ollama",
            base_url=cfg.get("base_url") or "http://localhost:11434/v1",
            default_model=cfg.get("default_model") or "llama3.1:8b",
            timeout_s=float(cfg.get("timeout_s") or 120.0),
            name="ollama",
        )

    def _anthropic(cfg: dict[str, Any]) -> LLMProvider:
        return AnthropicProvider(
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url") or "https://api.anthropic.com/v1",
            default_model=cfg.get("default_model") or "claude-3-5-sonnet-latest",
            timeout_s=float(cfg.get("timeout_s") or 120.0),
        )

    def _mock(cfg: dict[str, Any]) -> LLMProvider:
        return MockLLMProvider(
            default_model=cfg.get("default_model") or "mock-1",
            context_window=int(cfg.get("context_window") or 8192),
        )

    reg.register("openai", _openai)
    reg.register("ollama", _ollama)
    reg.register("anthropic", _anthropic)
    reg.register("mock", _mock)


_DEFAULT = LLMRegistry()
register_defaults(_DEFAULT)


def default_registry() -> LLMRegistry:
    """Process-wide registry with built-in providers already registered."""
    return _DEFAULT


__all__ = ["LLMRegistry", "default_registry", "register_defaults"]
