"""ToolRegistry — registration, discovery, and a single dispatch entrypoint.

Workflows never import a concrete tool class. They ask the registry::

    result = await registry.call("arxiv__search", {"query": "RLHF", "max_results": 5})

Why a single dispatcher? Three cross-cutting concerns land in one place:

1. **Capability gating** — reject network / paid-API calls when the
   settings forbid them.
2. **Telemetry** — emit ``skill.call`` / ``skill.result`` events with a
   consistent shape; upstream workflow gets a uniform trace.
3. **Error shaping** — any exception is translated into a
   ``ToolResult(ok=False, error=...)`` so the caller never has to wrap
   the invocation in try/except.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from backend.core.errors import ConfigError, NotFoundError
from backend.core.llm.base import ToolSpec

from .base import Tool, ToolResult

log = structlog.get_logger(__name__)

EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # ---- registration ------------------------------------------------

    def register(self, tool: Tool, *, overwrite: bool = False) -> None:
        if not tool.name:
            raise ConfigError("tool has no name", tool=type(tool).__name__)
        if tool.name in self._tools and not overwrite:
            raise ConfigError(f"tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise NotFoundError(f"tool '{name}' not registered", available=self.names())
        return tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    # ---- LLM-facing view --------------------------------------------

    def list_for_injection(
        self,
        *,
        allow_network: bool = True,
        allow_paid_api: bool = True,
        only: list[str] | None = None,
    ) -> list[ToolSpec]:
        """Return the ToolSpecs that a given run is allowed to invoke."""
        specs: list[ToolSpec] = []
        for name, tool in self._tools.items():
            if only is not None and name not in only:
                continue
            if tool.requires_network and not allow_network:
                continue
            if tool.requires_paid_api and not allow_paid_api:
                continue
            specs.append(
                ToolSpec(
                    name=tool.name,
                    description=tool.description,
                    parameters=dict(tool.parameters),
                )
            )
        return specs

    # ---- dispatch ----------------------------------------------------

    async def call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        allow_network: bool = True,
        allow_paid_api: bool = True,
        sink: EventSink | None = None,
    ) -> ToolResult:
        """Single entrypoint for invoking a tool."""
        args = dict(arguments or {})
        try:
            tool = self.get(name)
        except NotFoundError as exc:
            result = ToolResult(ok=False, error=str(exc), meta={"code": exc.code})
            await _emit(sink, "skill.result", {"tool": name, "ok": False, "error": result.error})
            return result

        if tool.requires_network and not allow_network:
            return _deny(name, "network access disabled in this run", sink)
        if tool.requires_paid_api and not allow_paid_api:
            return _deny(name, "paid-API tool disabled in this run", sink)

        await _emit(sink, "skill.call", {"tool": name, "arguments": _redact(args)})
        started = time.monotonic()
        try:
            result = await tool.call(args)
        except Exception as exc:  # registry is the error boundary for tools
            log.exception("tool.call_failed", tool=name)
            result = ToolResult(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                meta={"code": "aaf.tool_error"},
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        await _emit(
            sink,
            "skill.result",
            {
                "tool": name,
                "ok": result.ok,
                "error": result.error,
                "duration_ms": duration_ms,
            },
        )
        return result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _emit(sink: EventSink | None, event_type: str, data: dict[str, Any]) -> None:
    if sink is None:
        return
    try:
        await sink(event_type, data)
    except Exception:
        log.warning("tool.sink_failed", event=event_type)


def _deny(name: str, reason: str, sink: EventSink | None) -> ToolResult:
    result = ToolResult(ok=False, error=reason, meta={"code": "aaf.tool_denied"})
    # Best-effort telemetry without awaiting (we're in a sync path here).
    log.info("tool.denied", tool=name, reason=reason)
    # Emit through the sink when possible.
    if sink is not None:
        import asyncio

        try:
            asyncio.get_running_loop().create_task(
                _emit(sink, "skill.result", {"tool": name, "ok": False, "error": reason})
            )
        except RuntimeError:
            pass
    return result


_SENSITIVE_KEYS = {"api_key", "token", "authorization", "password"}


def _redact(args: dict[str, Any]) -> dict[str, Any]:
    return {k: ("<redacted>" if k.lower() in _SENSITIVE_KEYS else v) for k, v in args.items()}


# ---------------------------------------------------------------------------
# default registry: populated lazily to avoid network-probe imports at import
# time. Call `build_default_registry()` once per app startup (FastAPI lifespan).
# ---------------------------------------------------------------------------


def build_default_registry() -> ToolRegistry:
    from .arxiv_search import ArxivSearchTool
    from .pdf_parse import PdfParseTool

    reg = ToolRegistry()
    reg.register(ArxivSearchTool())
    reg.register(PdfParseTool())
    return reg


__all__ = ["ToolRegistry", "build_default_registry"]
