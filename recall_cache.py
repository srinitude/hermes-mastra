"""Cached observation snapshot served by `prefetch()` and `on_pre_compress()`.

The plugin contract demands these hooks return synchronously without
HTTP I/O. We cache the most recent recall response and refresh it in
the background through ``async_runner``.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class RecallCache:
    """Thread-safe last-known observation block + coalesced refresher."""

    def __init__(self) -> None:
        self._text: str = ""
        self._lock = threading.Lock()
        self._in_flight = threading.Event()

    def get(self) -> str:
        with self._lock:
            return self._text

    def clear(self) -> None:
        with self._lock:
            self._text = ""

    def _store(self, text: str) -> None:
        with self._lock:
            self._text = text or ""

    def refresh(self, fetch) -> bool:
        """Schedule *fetch()* to update the cache; coalesces concurrent calls.

        ``fetch`` is a zero-arg callable returning the new text (or "" / None).
        Returns ``True`` if a refresh was enqueued, ``False`` if one was
        already in flight.
        """
        if self._in_flight.is_set():
            return False
        self._in_flight.set()

        def _work() -> None:
            try:
                self._store(fetch() or "")
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug("mastra: recall refresh failed: %s", exc)
            finally:
                self._in_flight.clear()

        try:
            from .async_runner_loader import submit as _submit  # type: ignore
        except ImportError:
            from async_runner_loader import submit as _submit  # type: ignore[no-redef]
        _submit(_work)
        return True
