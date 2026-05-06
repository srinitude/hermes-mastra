"""Bounded background work queue for the mastra memory provider.

Per the Hermes plugin contract
(https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin)
hot-path hooks (``sync_turn``, ``prefetch``, ``on_session_switch``,
``on_pre_compress``, ``on_session_end``, ``on_memory_write``,
``on_delegation``) MUST be non-blocking — every HTTP round-trip the
provider does sits inside the user-facing agent turn.

This module provides a small dedicated thread-pool style runner the
provider hands work to. Design notes:

  * **One module-level singleton** — the provider is a lightweight class
    that may be reinstantiated; we don't want to recreate the worker
    pool every time. The pool lives in module state and is created
    lazily on first ``submit()``.
  * **Bounded queue** — protect the agent process if Mastra goes away.
    When the queue is full we *drop the oldest* fire-and-forget write
    rather than block the producer.
  * **Daemon threads** — never keep the Python process alive on its own.
  * **Explicit drain** — ``shutdown(wait=...)`` is what the provider's
    ``shutdown()`` hook calls so pending work isn't orphaned at process
    exit.
  * **Test isolation** — ``reset()`` tears the singleton down so each
    pytest can start with a fresh runner.

This module never imports ``client.py`` or ``server_manager.py`` to keep
it dependency-free and fast to import (the provider's ``initialize`` is
itself on a hot path).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Tunables — keep small. The provider does cheap HTTP POSTs, so a couple
# of workers is enough to hide the latency of one slow Mastra call without
# building up a backlog. Queue size 256 is far more than a normal session
# would generate; if we hit it we're broken upstream and dropping is the
# right move.
DEFAULT_WORKERS = 2
DEFAULT_QUEUE_SIZE = 256
SHUTDOWN_TIMEOUT = 5.0


class _Sentinel:
    """Posted to the queue to signal a worker to exit."""


_STOP = _Sentinel()


class AsyncRunner:
    """Thread-pool-style runner with a bounded queue and explicit drain."""

    def __init__(
        self, workers: int = DEFAULT_WORKERS, queue_size: int = DEFAULT_QUEUE_SIZE
    ) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._closed = False
        self._dropped = 0
        self._drop_bursts = 0
        self._drop_active = False
        self._drop_log_pending = False
        for i in range(workers):
            t = threading.Thread(
                target=self._loop,
                name=f"mastra-runner-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    # ----- producer side -----

    def submit(self, fn: Callable[[], None]) -> bool:
        """Enqueue *fn* for background execution without blocking the producer."""
        if self._closed:
            return False
        if self._try_put(fn):
            return True
        return self._drop_oldest_and_put(fn)

    def _try_put(self, fn: Callable[[], None]) -> bool:
        try:
            self._queue.put_nowait(fn)
            return True
        except queue.Full:
            return False

    def _drop_oldest_and_put(self, fn: Callable[[], None]) -> bool:
        with self._lock:
            self._drop_one_locked()
            if self._try_put(fn):
                return True
            self._mark_drop_locked()
            return False

    def _drop_one_locked(self) -> None:
        try:
            self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:
            return
        self._mark_drop_locked()

    def _mark_drop_locked(self) -> None:
        self._dropped += 1
        if self._drop_active:
            return
        self._drop_bursts += 1
        self._drop_active = True
        self._drop_log_pending = True

    # ----- worker side -----

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                try:
                    item()
                except Exception as exc:  # pragma: no cover — defensive
                    logger.debug("mastra async work failed: %s", exc)
            finally:
                self._queue.task_done()

    # ----- lifecycle -----

    def drain(self, timeout: float = SHUTDOWN_TIMEOUT) -> bool:
        """Wait up to *timeout* seconds for all queued work to finish.

        Returns ``True`` if drained cleanly, ``False`` on timeout.
        Does NOT close the runner — callers can keep submitting after.
        """
        deadline = time.monotonic() + timeout
        while not self._queue.empty():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        # All items dequeued — give workers a moment to finish the in-flight
        # one. join() on a Queue waits for task_done() of every put().
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            return self._queue.unfinished_tasks == 0
        # queue.join() blocks indefinitely; emulate with poll.
        end = time.monotonic() + remaining
        while self._queue.unfinished_tasks > 0:
            if time.monotonic() >= end:
                return False
            time.sleep(0.01)
        return True

    def shutdown(self, wait: float = SHUTDOWN_TIMEOUT) -> bool:
        """Drain pending work, then signal workers to exit.

        Returns ``True`` if drained cleanly within *wait* seconds.
        Idempotent — safe to call multiple times.
        """
        with self._lock:
            if self._closed:
                return True
            self._closed = True
        clean = self.drain(timeout=wait)
        # Wake every worker exactly once so they exit their loop.
        for _ in self._workers:
            try:
                self._queue.put_nowait(_STOP)
            except queue.Full:  # pragma: no cover — drain would have failed
                pass
        for w in self._workers:
            w.join(timeout=wait)
        return clean

    # ----- introspection (used by tests + diagnostics) -----

    @property
    def pending(self) -> int:
        return self._queue.unfinished_tasks

    def _emit_drop_log(self) -> None:
        if not self._drop_log_pending:
            return
        self._drop_log_pending = False
        logger.warning("queue_saturation")

    @property
    def dropped(self) -> int:
        self._emit_drop_log()
        return self._dropped

    @property
    def drop_bursts(self) -> int:
        self._emit_drop_log()
        return self._drop_bursts


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------

_runner: AsyncRunner | None = None
_runner_lock = threading.Lock()


def get_runner() -> AsyncRunner:
    """Return the process-wide AsyncRunner, creating it on first call."""
    global _runner
    if _runner is None or _runner._closed:
        with _runner_lock:
            if _runner is None or _runner._closed:
                _runner = AsyncRunner()
    return _runner


def submit(fn: Callable[[], None]) -> bool:
    """Convenience: submit to the singleton runner."""
    return get_runner().submit(fn)


def shutdown(wait: float = SHUTDOWN_TIMEOUT) -> bool:
    """Drain + close the singleton. Safe if no runner exists yet."""
    global _runner
    with _runner_lock:
        if _runner is None:
            return True
        ok = _runner.shutdown(wait=wait)
        return ok


def reset() -> None:
    """Test-only: tear down and recreate the singleton."""
    global _runner
    with _runner_lock:
        if _runner is not None:
            _runner.shutdown(wait=2.0)
        _runner = None
