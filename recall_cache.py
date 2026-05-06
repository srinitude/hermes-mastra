"""Profile/thread keyed recall cache served by hot-path hooks."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable

logger = logging.getLogger(__name__)


class RecallCache:
    """Thread-safe bounded LRU with the old single-snapshot API preserved."""

    def __init__(self, max_entries: int = 32) -> None:
        self.max_entries = max(1, int(max_entries))
        self._items: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._legacy_text = ""
        self._legacy_manual = False
        self._lock = threading.Lock()
        self._in_flight = threading.Event()
        self._current = ("", "")

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def _text(self) -> str:
        return self.get()

    @_text.setter
    def _text(self, value: str) -> None:
        with self._lock:
            self._legacy_text = value or ""
            self._legacy_manual = True
            self._items[self._current] = self._legacy_text
            self._trim()

    def set_current(self, profile: str, thread: str) -> None:
        with self._lock:
            self._current = (profile or "", thread or "")

    def get(self, profile: str | None = None, thread: str | None = None) -> str:
        with self._lock:
            key = self._key(profile, thread)
            text = self._items.get(key, "")
            if not text and self._legacy_manual:
                text = self._legacy_text
            if key in self._items:
                self._items.move_to_end(key)
            return text

    def store(self, profile: str, thread: str, text: str) -> None:
        with self._lock:
            key = (profile or "", thread or "")
            self._items[key] = text or ""
            self._legacy_text = text or ""
            self._legacy_manual = False
            self._items.move_to_end(key)
            self._current = key
            self._trim()

    def clear(self, profile: str | None = None, thread: str | None = None) -> None:
        with self._lock:
            if profile is None and thread is None:
                self._items.clear()
                self._legacy_text = ""
                self._legacy_manual = False
                return
            key = self._key(profile, thread)
            self._items.pop(key, None)
            if key == self._current:
                self._legacy_text = ""
                self._legacy_manual = False

    def clear_profile(self, profile: str) -> None:
        with self._lock:
            doomed = [key for key in self._items if key[0] == (profile or "")]
            for key in doomed:
                self._items.pop(key, None)
            if self._legacy_manual:
                self._items.pop(self._current, None)
            self._legacy_text = ""
            self._legacy_manual = False

    def refresh(
        self,
        fetch: Callable[[], str | None],
        profile: str | None = None,
        thread: str | None = None,
    ) -> bool:
        if self._in_flight.is_set():
            return False
        self._in_flight.set()
        key = self._key(profile, thread)

        def _work() -> None:
            try:
                self.store(key[0], key[1], fetch() or "")
            except Exception as exc:  # pragma: no cover - defensive boundary
                logger.debug("mastra: recall refresh failed: %s", exc)
            finally:
                self._in_flight.clear()

        self.set_current(*key)
        self._submit(_work)
        return True

    def _key(self, profile: str | None, thread: str | None) -> tuple[str, str]:
        if profile is None and thread is None:
            return self._current
        return (profile or "", thread or "")

    def _trim(self) -> None:
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    @staticmethod
    def _submit(fn: Callable[[], None]) -> None:
        try:
            from .async_runner_loader import submit as _submit  # type: ignore
        except ImportError:
            from async_runner_loader import submit as _submit  # type: ignore[no-redef]
        _submit(fn)
