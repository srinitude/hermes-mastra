"""G04: outage-time write buffer.

When the Mastra server is unreachable (circuit breaker rejects the
request, or httpx raises before reaching it), every outbound POST is
appended as an ndjson line to ``$HERMES_HOME/data/mastra/replay-<thread>.ndjson``
so the write survives across the outage and can be drained back into
Mastra once the breaker recloses. The path follows A07 / G04: one file
per thread, 16 MiB rolling cap (next-line writes start a new file when
the active one crosses the cap), JSON line shape ``{ts, path, payload}``.

This module is intentionally tiny so the Mastra client only takes a
single dependency on it (``replay_log.append``); reading is left to
the test harness and the future drain worker (G11).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

ROLLOVER_BYTES = 16 * 1024 * 1024


def _resolve_home(home: str | None = None) -> Path | None:
    base = home or os.environ.get("HERMES_HOME") or ""
    return Path(base) if base else None


def _safe_thread_segment(thread: str) -> str:
    return (thread or "default-session").replace("/", "_").replace(os.sep, "_")


def _active_log_path(home: Path, thread: str) -> Path:
    log_dir = home / "data" / "mastra"
    log_dir.mkdir(parents=True, exist_ok=True)
    base = log_dir / f"replay-{_safe_thread_segment(thread)}.ndjson"
    if base.exists() and base.stat().st_size >= ROLLOVER_BYTES:
        return log_dir / f"replay-{_safe_thread_segment(thread)}-{int(time.time())}.ndjson"
    return base


def append(
    thread: str, path: str, payload: dict[str, Any], *, home: str | None = None
) -> Path | None:
    """Append a single replay record. Returns the file path on success."""
    target_home = _resolve_home(home)
    if target_home is None:
        return None
    try:
        log_path = _active_log_path(target_home, thread)
        line = json.dumps(
            {"ts": time.time(), "path": path, "payload": payload},
            separators=(",", ":"),
            default=str,
        )
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return log_path
    except OSError:
        return None
