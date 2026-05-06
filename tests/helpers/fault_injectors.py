"""Fault injectors for resilience contract tests.

These helpers are deterministic classes used by RED/GREEN tests to exercise
real provider boundaries without patching production internals.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class SlowCallClient:
    """Client-like object that sleeps on every method call."""

    def __init__(self, delay: float = 0.5) -> None:
        self.delay = delay
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., str]:
        def _call(*args: Any, **kwargs: Any) -> str:
            self.calls.append((name, args, kwargs))
            time.sleep(self.delay)
            return ""

        return _call

    def close(self) -> None:
        self.calls.append(("close", (), {}))


class RecordingClient:
    """Client-like object that records observable calls and returns configured data."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.recall_text: str = ""
        self.failures: dict[str, BaseException] = {}

    def _record(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        failure = self.failures.get(name)
        if failure is not None:
            raise failure
        if name == "recall":
            return self.recall_text
        return True

    def recall(self, *args: Any, **kwargs: Any) -> str:
        return str(self._record("recall", *args, **kwargs))

    def write_observation(self, *args: Any, **kwargs: Any) -> bool:
        return bool(self._record("write_observation", *args, **kwargs))

    def update_working_memory(self, *args: Any, **kwargs: Any) -> bool:
        return bool(self._record("update_working_memory", *args, **kwargs))

    def save_turn(self, *args: Any, **kwargs: Any) -> bool:
        return bool(self._record("save_turn", *args, **kwargs))

    def flush(self, *args: Any, **kwargs: Any) -> bool:
        return bool(self._record("flush", *args, **kwargs))

    def close(self) -> None:
        self._record("close")
