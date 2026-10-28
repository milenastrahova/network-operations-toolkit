"""Simple debounced incident state for repeated active check results."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class DebouncedAlert:
    failures_to_open: int = 3
    successes_to_close: int = 2
    active: bool = False
    failures: int = 0
    successes: int = 0

    def __post_init__(self):
        if self.failures_to_open < 1 or self.successes_to_close < 1:
            raise ValueError("Consecutive thresholds must be positive")

    def observe(self, is_healthy: bool) -> str | None:
        if is_healthy:
            self.successes += 1
            self.failures = 0
            if self.active and self.successes >= self.successes_to_close:
                self.active = False
                return "RECOVERED"
        else:
            self.failures += 1
            self.successes = 0
            if not self.active and self.failures >= self.failures_to_open:
                self.active = True
                return "OPENED"
        return None
