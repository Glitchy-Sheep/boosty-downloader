"""Named timing samples and explicit performance budgets."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from time import perf_counter
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

QUERY_BUDGET_SECONDS: Final = 0.010
REBUILD_BUDGET_SECONDS: Final = 10.0
OPEN_BUDGET_SECONDS: Final = 1.0


@dataclass(frozen=True, slots=True)
class Measurement:
    """The first operation and subsequent warm samples, in seconds."""

    name: str
    first_seconds: float
    warm_seconds: tuple[float, ...]
    budget_seconds: float | None = None

    @property
    def median_seconds(self) -> float:
        return median(self.warm_seconds)

    @property
    def minimum_seconds(self) -> float:
        return min(self.warm_seconds)

    @property
    def maximum_seconds(self) -> float:
        return max(self.warm_seconds)

    @property
    def passed(self) -> bool:
        return self.budget_seconds is None or self.median_seconds < self.budget_seconds


def measure(
    name: str,
    operation: Callable[[], object],
    *,
    samples: int,
    budget_seconds: float | None = None,
) -> Measurement:
    """Consume each operation before stopping its timer; exclude validation work."""
    if samples < 1:
        message = 'At least one warm timing sample is required'
        raise ValueError(message)
    first = _elapsed(operation)
    warm = tuple(_elapsed(operation) for _ in range(samples))
    return Measurement(name, first, warm, budget_seconds)


def _elapsed(operation: Callable[[], object]) -> float:
    started = perf_counter()
    operation()
    return perf_counter() - started
