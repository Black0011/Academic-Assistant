"""LLM provider layer.

Public API:
    LLMProvider            -- Protocol every adapter must satisfy
    ChatMessage, ToolSpec, ToolCall, CompletionChunk, Usage, CostEstimate
    MockLLMProvider        -- scripted provider for tests
    OpenAICompatProvider   -- OpenAI-compatible HTTP adapter
    AnthropicProvider      -- Anthropic Messages API adapter
    LLMRegistry            -- name → factory mapping
    default_registry()     -- pre-populated registry
"""

from .anthropic import AnthropicProvider
from .base import (
    ChatMessage,
    CompletionChunk,
    ContentPart,
    CostEstimate,
    ImagePart,
    LLMProvider,
    TextPart,
    ToolCall,
    ToolSpec,
    Usage,
    collect_text,
)
from .mock import MockLLMProvider
from .openai_compat import OpenAICompatProvider
from .registry import LLMRegistry, default_registry, register_defaults
from .router import (
    RouteSpec,
    RoutingLLMProvider,
    RoutingPolicy,
    build_routing_provider,
    load_routing_policy,
)

__all__ = [
    "AnthropicProvider",
    "ChatMessage",
    "CompletionChunk",
    "ContentPart",
    "CostEstimate",
    "ImagePart",
    "LLMProvider",
    "LLMRegistry",
    "MockLLMProvider",
    "OpenAICompatProvider",
    "RouteSpec",
    "RoutingLLMProvider",
    "RoutingPolicy",
    "TextPart",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "build_routing_provider",
    "collect_text",
    "default_registry",
    "load_routing_policy",
    "register_defaults",
]
