"""Failure-streak circuit breaker for the full-download run."""

from dataclasses import dataclass


@dataclass
class FailureStreakBreaker:
    """
    Trip when post failures come in an unbroken streak.

    Scattered failures are per-post problems and only cost a skip each.
    An unbroken streak means the world around the run is broken (disk,
    permissions, network) - going on would grind for hours downloading
    nothing. Any success resets the streak.
    """

    threshold: int
    _streak: int = 0

    def record_success(self) -> None:
        """Reset the streak - a success proves the run is healthy."""
        self._streak = 0

    def record_failure(self) -> bool:
        """Count a failed post; True means the threshold is reached."""
        self._streak += 1
        return self._streak >= self.threshold
