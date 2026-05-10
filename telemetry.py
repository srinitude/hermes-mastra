"""G01 / G11 seed: structured telemetry per Mastra-bound hook call.

Every lifecycle hook records one entry into a process-wide ring buffer
(``ts``, ``op``, ``profile``, ``thread``, ``duration_us``, ``extra``).
The buffer is bounded at 4096 entries so memory stays predictable and
diagnostics tools (``hermes mastra status`` — landing in G10) can read
the tail to surface live latency / outcome stats.

The buffer is intentionally append-only and lock-protected so multi-
threaded producers (the hot-path hooks plus the async runner workers)
can write without coordination. Reads via ``snapshot`` return a list
copy of the last ``n`` records under the same lock. Signed NDJSON
persistence to ``$HERMES_HOME/logs/mastra.log`` is queued onto the
shared async runner so the hot-path hook never blocks on disk I/O.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

try:
    from . import async_runner_loader as _runner_loader
except ImportError:
    import async_runner_loader as _runner_loader  # type: ignore[no-redef]

_BUFFER: deque[dict[str, Any]] = deque(maxlen=4096)
_LINES: deque[str] = deque(maxlen=4096)
_LOCK = threading.Lock()
_LOG_PATH_CACHE: dict[str, Path] = {}


def _resolve_log_path() -> Path | None:
    """Return ~/.hermes/logs/mastra.log only when an existing logs dir is present.

    Hot-path policy: telemetry persistence MUST NOT create directories or
    enqueue async work on hot paths. Server startup
    (``server_process.start_server`` → ``safe_log_file``) is responsible
    for creating ``$HERMES_HOME/logs`` and touching ``mastra.log`` once,
    so live/server sessions still persist signed NDJSON on every record.
    Isolated temporary homes (no logs dir) silently skip persistence.
    """
    home = os.environ.get("HERMES_HOME") or ""
    cached = _LOG_PATH_CACHE.get(home)
    if cached is not None:
        return cached
    if not home:
        return None
    log_dir = Path(home) / "logs"
    if not log_dir.is_dir():
        return None
    path = log_dir / "mastra.log"
    _LOG_PATH_CACHE[home] = path
    return path


def record(
    op: str,
    *,
    profile: str = "",
    thread: str = "",
    duration_us: int = 0,
    outcome: str = "ok",
    extra: dict[str, Any] | None = None,
) -> None:
    entry: dict[str, Any] = {
        "ts": time.time(),
        "op": op,
        "profile": profile,
        "thread": thread,
        "duration_us": int(duration_us),
        "outcome": outcome,
    }
    if extra:
        entry["extra"] = dict(extra)
    serialized = json.dumps(entry, separators=(",", ":"), default=str)
    # G11 requirement: structured logs are tamper-evident — sign every line
    # with a SHA-256 hash so post-hoc audits can detect mutation. The signed
    # record is the canonical form persisted to ~/.hermes/logs/mastra.log.
    entry["_sig"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    signed = json.dumps(entry, separators=(",", ":"), default=str)
    with _LOCK:
        _BUFFER.append(entry)
        _LINES.append(signed)
    _enqueue_persist(signed)


def _enqueue_persist(line: str) -> None:
    """Hand persistence to the shared async runner so hot-path hooks never block."""
    path = _resolve_log_path()
    if path is None:
        return
    try:
        _runner_loader.submit(lambda p=path, ln=line: _persist_line(p, ln))
    except Exception:
        return


def _persist_line(path: Path, line: str) -> None:
    """Append one signed NDJSON record. Failures are silent (no hot-path coupling)."""
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        return


def _token_estimate(value: Any) -> int:
    if value in (None, "", {}, []):
        return 0
    text = json.dumps(value, separators=(",", ":"), default=str)
    return max(1, len(text) // 4)


def record_mastra_call(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    started: float,
    result: Any,
    error_class: str,
) -> None:
    """G11 — one structured ``mastra_call`` record per HTTP boundary call."""
    p = payload or {}
    success = result is not None
    profile = str(p.get("profile") or "")
    record(
        "mastra_call",
        profile=profile,
        thread=str(p.get("thread") or ""),
        duration_us=int((time.monotonic() - started) * 1_000_000),
        outcome="ok" if success else "error",
        extra={
            "method": str(method),
            "path": str(path),
            "resource_id": profile,
            "success": success,
            "tokens_in": _token_estimate(payload),
            "tokens_out": _token_estimate(result),
            "token_source": "estimated_chars",
            "error_class": "" if success else (error_class or "MastraRequestFailed"),
        },
    )


def time_hook(op: str, p: Any) -> _HookSpan:
    """Return a context manager that records duration on exit."""
    return _HookSpan(op, p)


def timed(op: str):
    """Decorator that records every call to a lifecycle hook helper.

    Usage::

        @timed("prefetch")
        def do_prefetch(p, ...): ...

    Each invocation appends one buffered telemetry record with the
    hook's wall-clock duration in microseconds, the provider's current
    profile + thread, and the call outcome ("ok" or "error").
    """

    def decorator(fn):
        def wrapper(p, *args, **kwargs):
            t0 = time.monotonic()
            outcome = "ok"
            try:
                return fn(p, *args, **kwargs)
            except BaseException:
                outcome = "error"
                raise
            finally:
                record(
                    op,
                    profile=str(getattr(p, "_profile", "") or ""),
                    thread=str(getattr(p, "_thread", "") or ""),
                    duration_us=int((time.monotonic() - t0) * 1_000_000),
                    outcome=outcome,
                )

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        wrapper.__name__ = getattr(fn, "__name__", "wrapper")
        return wrapper

    return decorator


def snapshot(n: int = 100) -> list[dict[str, Any]]:
    with _LOCK:
        if n >= len(_BUFFER):
            return list(_BUFFER)
        return list(_BUFFER)[-n:]


def reset() -> None:
    with _LOCK:
        _BUFFER.clear()
        _LINES.clear()


def lines(n: int = 100) -> list[str]:
    """Return the most recent serialized NDJSON-ready lines (G11 seed)."""
    with _LOCK:
        if n >= len(_LINES):
            return list(_LINES)
        return list(_LINES)[-n:]


class _HookSpan:
    __slots__ = ("_op", "_profile", "_started", "_thread")

    def __init__(self, op: str, p: Any) -> None:
        self._op = op
        self._profile = str(getattr(p, "_profile", "") or "")
        self._thread = str(getattr(p, "_thread", "") or "")
        self._started = 0.0

    def __enter__(self) -> _HookSpan:
        self._started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        duration_us = int((time.monotonic() - self._started) * 1_000_000)
        outcome = "ok" if exc_type is None else "error"
        record(
            self._op,
            profile=self._profile,
            thread=self._thread,
            duration_us=duration_us,
            outcome=outcome,
        )
