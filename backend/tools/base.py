"""Tool protocol + `ToolResult` (PLAN §12.2).

Tools are *framework-shared utilities* — anything that isn't private to a
single Skill lives here (`arxiv__search`, `pdf__parse`, `web__search`, …).

Design notes:

* **One-arg `call(arguments)`** instead of `__call__(**kwargs)` — keeps the
  dispatcher simple (no `**` splatting into unknown positional args) and
  lets tools validate the payload through their declared JSON schema.
* **JSON-Schema `parameters`** mirrors OpenAI / Anthropic function-call
  schemas verbatim, so `to_llm_spec()` is a cheap projection.
* Every tool advertises two capability flags:
  - ``requires_network`` — refused in sandboxed runs
  - ``requires_paid_api`` — gated by ``settings.allow_paid_apis``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from backend.core.llm.base import ToolSpec


@dataclass
class ToolResult:
    """Outcome of one tool call. Kept deliberately small and JSON-safe."""

    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "error": self.error, "meta": dict(self.meta)}


@runtime_checkable
class Tool(Protocol):
    """Runtime-checkable protocol every registered tool must satisfy."""

    name: str
    description: str
    parameters: dict[str, Any]
    requires_network: bool
    requires_paid_api: bool

    async def call(self, arguments: dict[str, Any]) -> ToolResult: ...


class BaseTool:
    """Convenience base class. Tools may subclass this or duck-type `Tool`.

    Attributes are set at the class level so a single instance can serve
    every call (tools are stateless singletons in the registry). Shared
    mutable defaults are intentional; ``# noqa: RUF012`` keeps ruff quiet.
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}  # noqa: RUF012
    requires_network: bool = False
    requires_paid_api: bool = False

    async def call(self, arguments: dict[str, Any]) -> ToolResult:  # pragma: no cover
        raise NotImplementedError

    def to_llm_spec(self) -> ToolSpec:
        """Project into the `ToolSpec` type the LLM layer already understands."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=dict(self.parameters),
        )


__all__ = ["BaseTool", "Tool", "ToolResult"]
