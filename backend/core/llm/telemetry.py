"""Lightweight LLM call telemetry — token counting and cost estimation.

For M1 we keep everything in-memory. M3 will persist to Postgres via
`ModelUsage` table and expose through `/api/v1/models/usage`.

Per-task model routing (M-Router, see PLAN §9.5) tags each call with
the *route name* the workflow asked for (e.g. ``"reasoning"`` /
``"fast"``). The route flows through the :func:`active_route`
contextvar so adapters that already call :func:`record` automatically
pick it up — no API change to existing providers required.
"""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PRICES_CACHE: dict[str, dict[str, dict[str, float]]] | None = None
_PRICES_LOCK = threading.Lock()


def _load_prices() -> dict[str, dict[str, dict[str, float]]]:
    """Load prices.yaml once, cache in-process."""
    global _PRICES_CACHE
    if _PRICES_CACHE is not None:
        return _PRICES_CACHE
    with _PRICES_LOCK:
        if _PRICES_CACHE is not None:
            return _PRICES_CACHE
        path = Path(__file__).parent / "prices.yaml"
        _PRICES_CACHE = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return _PRICES_CACHE


def reset_prices_cache() -> None:
    """Test hook."""
    global _PRICES_CACHE
    with _PRICES_LOCK:
        _PRICES_CACHE = None


def estimate_cost_usd(
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    """Return USD cost for a single call, or None if pricing is unknown."""
    prices = _load_prices()
    provider_prices = prices.get(provider) or {}
    model_prices = provider_prices.get(model)
    if model_prices is None:
        model_prices = provider_prices.get("_default")
    if model_prices is None:
        return None
    in_rate = float(model_prices.get("input", 0.0))
    out_rate = float(model_prices.get("output", 0.0))
    return (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000.0


@dataclass
class Record:
    provider: str
    model: str
    task_id: str | None
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    cost_usd: float | None
    error_code: str | None = None
    # Workflow-declared model route (e.g. "reasoning" / "fast" / "local").
    # ``None`` means the call ran on the default provider without an
    # explicit route — the call site didn't (or doesn't need to) opt in
    # to per-task routing.
    route: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Active route propagation (used by RoutingLLMProvider)
# ---------------------------------------------------------------------------

_ACTIVE_ROUTE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aaf.llm.active_route", default=None
)


def active_route() -> str | None:
    """Return the route name set by the surrounding ``for_route(...)`` wrapper.

    Returns ``None`` when the call is happening outside any router-tagged
    context (e.g. direct provider use, or via ``RoutingLLMProvider``'s
    delegate-to-default Protocol path).
    """

    return _ACTIVE_ROUTE.get()


def set_active_route(name: str | None) -> contextvars.Token[str | None]:
    """Set the active route for the current async task; return a reset token."""

    return _ACTIVE_ROUTE.set(name)


def reset_active_route(token: contextvars.Token[str | None]) -> None:
    """Reset the active route using a token returned by :func:`set_active_route`."""

    _ACTIVE_ROUTE.reset(token)


class TelemetryRecorder:
    """In-process ring buffer of recent LLM calls.

    Thread-safe; bounded to avoid unbounded memory growth.
    """

    def __init__(self, max_records: int = 1000) -> None:
        self._records: list[Record] = []
        self._lock = threading.Lock()
        self._max = max_records
        self._totals: dict[str, float] = {
            "prompt_tokens": 0.0,
            "completion_tokens": 0.0,
            "cost_usd": 0.0,
            "calls": 0.0,
            "errors": 0.0,
        }

    def record(self, r: Record) -> None:
        with self._lock:
            self._records.append(r)
            if len(self._records) > self._max:
                self._records.pop(0)
            self._totals["prompt_tokens"] += r.prompt_tokens
            self._totals["completion_tokens"] += r.completion_tokens
            if r.cost_usd is not None:
                self._totals["cost_usd"] += r.cost_usd
            self._totals["calls"] += 1
            if r.error_code is not None:
                self._totals["errors"] += 1

    def totals(self) -> dict[str, float]:
        with self._lock:
            return dict(self._totals)

    def records(self) -> list[Record]:
        with self._lock:
            return list(self._records)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            for k in self._totals:
                self._totals[k] = 0.0


_RECORDER = TelemetryRecorder()


def recorder() -> TelemetryRecorder:
    return _RECORDER


def record(
    *,
    provider: str,
    model: str,
    task_id: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: float = 0.0,
    cost_usd: float | None = None,
    error_code: str | None = None,
    route: str | None = None,
    **extra: Any,
) -> None:
    """Record a completed LLM call.

    If ``route`` is omitted, the contextvar set by
    :func:`set_active_route` is consulted — this lets adapters that
    don't know about routing still emit route-tagged records when called
    via ``RoutingLLMProvider.for_route(...)``.
    """

    if route is None:
        route = _ACTIVE_ROUTE.get()
    _RECORDER.record(
        Record(
            provider=provider,
            model=model,
            task_id=task_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            error_code=error_code,
            route=route,
            extra=extra,
        )
    )


__all__ = [
    "Record",
    "TelemetryRecorder",
    "active_route",
    "estimate_cost_usd",
    "record",
    "recorder",
    "reset_active_route",
    "reset_prices_cache",
    "set_active_route",
]
