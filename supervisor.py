"""Bounded supervisor policy for the Bun server lifecycle."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class ServerSupervisor:
    """Crash restart limiter with exponential backoff metadata."""

    def __init__(
        self,
        max_restarts_per_minute: int = 3,
        base_delay_seconds: float = 0.25,
        max_backoff_seconds: float = 5.0,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.max_restarts_per_minute = max(1, int(max_restarts_per_minute))
        self.base_delay_seconds = max(0.0, float(base_delay_seconds))
        self.max_backoff_seconds = max(self.base_delay_seconds, float(max_backoff_seconds))
        self.host_hook_budget_ms = 99
        self._now = now or time.monotonic
        self._restarts: deque[float] = deque()
        self._crashes = 0
        self.next_delay_seconds = self.base_delay_seconds

    def record_crash(self, restart: Callable[[], None]) -> bool:
        self._trim()
        if len(self._restarts) < self.max_restarts_per_minute:
            restart()
            self._restarts.append(self._now())
        self._crashes += 1
        self.next_delay_seconds = min(
            self.max_backoff_seconds,
            self.base_delay_seconds * (2 ** max(0, self._crashes - 1)),
        )
        return True

    def _trim(self) -> None:
        cutoff = self._now() - 60.0
        while self._restarts and self._restarts[0] < cutoff:
            self._restarts.popleft()
