"""Small fail-closed circuit breaker for Mastra client calls."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class CircuitBreaker:
    """CLOSED/OPEN/HALF_OPEN state machine with a fast fallback path."""

    def __init__(
        self,
        threshold: int = 5,
        cooldown_seconds: float = 5.0,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.threshold = max(1, int(threshold))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._now = now or time.monotonic
        self._lock = threading.Lock()
        self._state = "CLOSED"
        self._failures = 0
        self._opened_at = 0.0
        self._trial = False

    @property
    def state(self) -> str:
        with self._lock:
            self._advance()
            return self._state

    def call(self, fn: Callable[[], T], fallback: T) -> T:
        if not self._admit():
            return fallback
        try:
            result = fn()
        except Exception:
            self._record_failure()
            return fallback
        self._record_success()
        return result

    def _advance(self) -> None:
        if self._state == "OPEN" and self._now() - self._opened_at >= self.cooldown_seconds:
            self._state = "HALF_OPEN"
            self._trial = False

    def _admit(self) -> bool:
        with self._lock:
            self._advance()
            if self._state == "OPEN":
                return False
            if self._state == "HALF_OPEN" and self._trial:
                return False
            if self._state == "HALF_OPEN":
                self._trial = True
            return True

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == "HALF_OPEN" or self._failures >= self.threshold:
                self._state = "OPEN"
                self._opened_at = self._now()
                self._trial = False

    def _record_success(self) -> None:
        with self._lock:
            self._state = "CLOSED"
            self._failures = 0
            self._trial = False
