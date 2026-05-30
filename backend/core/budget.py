"""Per-task budget: tokens, USD, wallclock seconds.

Workflows call `budget.assert_ok()` at the start of every stage and
`budget.accrue_llm(...)` after every LLM call. When any limit is exceeded
the Budget raises :class:`BudgetExceededError` — workflows translate that
into a `task.error` event with `retryable=False`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.core.errors import BudgetExceededError


@dataclass
class Budget:
    max_prompt_tokens: int | None = None
    max_completion_tokens: int | None = None
    max_total_tokens: int | None = None
    max_cost_usd: float | None = None
    max_wallclock_s: float | None = None

    # running totals
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    _started: float = field(default_factory=time.monotonic)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._started

    def accrue_llm(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        self.prompt_tokens += max(0, prompt_tokens)
        self.completion_tokens += max(0, completion_tokens)
        self.cost_usd += max(0.0, cost_usd)

    def assert_ok(self) -> None:
        if self.max_prompt_tokens is not None and self.prompt_tokens > self.max_prompt_tokens:
            raise BudgetExceededError(
                f"prompt tokens exceeded: {self.prompt_tokens} > {self.max_prompt_tokens}",
                kind="prompt_tokens",
                used=self.prompt_tokens,
                limit=self.max_prompt_tokens,
            )
        if (
            self.max_completion_tokens is not None
            and self.completion_tokens > self.max_completion_tokens
        ):
            raise BudgetExceededError(
                f"completion tokens exceeded: {self.completion_tokens} > {self.max_completion_tokens}",
                kind="completion_tokens",
                used=self.completion_tokens,
                limit=self.max_completion_tokens,
            )
        if self.max_total_tokens is not None and self.total_tokens > self.max_total_tokens:
            raise BudgetExceededError(
                f"total tokens exceeded: {self.total_tokens} > {self.max_total_tokens}",
                kind="total_tokens",
                used=self.total_tokens,
                limit=self.max_total_tokens,
            )
        if self.max_cost_usd is not None and self.cost_usd > self.max_cost_usd:
            raise BudgetExceededError(
                f"cost exceeded: ${self.cost_usd:.4f} > ${self.max_cost_usd:.4f}",
                kind="cost_usd",
                used=self.cost_usd,
                limit=self.max_cost_usd,
            )
        if self.max_wallclock_s is not None and self.elapsed_s > self.max_wallclock_s:
            raise BudgetExceededError(
                f"wallclock exceeded: {self.elapsed_s:.1f}s > {self.max_wallclock_s:.1f}s",
                kind="wallclock_s",
                used=self.elapsed_s,
                limit=self.max_wallclock_s,
            )

    def snapshot(self) -> dict[str, float | int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_s": round(self.elapsed_s, 3),
        }


__all__ = ["Budget"]
