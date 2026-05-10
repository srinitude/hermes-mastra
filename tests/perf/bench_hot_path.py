"""B02 — hot-path performance benchmark harness.

Runs ``N`` simulated turns through ``MastraMemoryProvider`` against a live
Mastra server and measures the four hot-path hooks defined in
``analysis/latency-budget.json``:

  * ``prefetch`` (cache-only return)
  * ``sync_turn`` (enqueue-only)
  * ``on_memory_write`` (enqueue-only)
  * ``on_pre_compress`` (enqueue-only)

Writes ``analysis/perf-baseline.json`` with the recorded p50/p99 per hook.

When the live server can't be reached (no bun, no creds, server down), the
harness writes a ``status: unavailable`` artifact and exits ``0`` so the
BOOTSTRAP gate doesn't fail; the RED phase tests assert the actual
contract against this artifact.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = REPO_ROOT / "analysis" / "perf-baseline.json"
DEFAULT_TURNS = 200


def _ensure_plugin_path() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _server_available() -> bool:
    if not shutil.which("bun"):
        return False
    if not (REPO_ROOT / "server" / "node_modules").is_dir():
        return False
    if not os.environ.get("VENICE_API_KEY"):
        return False
    google = (
        os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    return bool(google)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, round(pct / 100.0 * (len(s) - 1))))
    return s[idx]


def _provider() -> Any:
    _ensure_plugin_path()
    from __init__ import MastraMemoryProvider  # type: ignore[no-redef]

    return MastraMemoryProvider()


def _measure(fn, *args, **kwargs) -> float:
    """Return wall-clock duration of ``fn`` in milliseconds."""
    start = time.monotonic()
    fn(*args, **kwargs)
    return (time.monotonic() - start) * 1000.0


def _run_turn(provider: Any, idx: int) -> dict[str, float]:
    user_msg = f"bench turn {idx} — what did I work on previously?"
    assistant_msg = f"bench turn {idx} reply summarising previous work"
    return {
        "prefetch_ms": _measure(provider.prefetch, user_msg),
        "sync_turn_ms": _measure(provider.sync_turn, user_msg, assistant_msg),
        "on_memory_write_ms": _measure(
            provider.on_memory_write, "add", "MEMORY.md", f"bench fact {idx}", {}
        ),
        "on_pre_compress_ms": _measure(
            provider.on_pre_compress,
            [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg},
            ],
        ),
    }


def _aggregate(samples: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    fields = ("prefetch_ms", "sync_turn_ms", "on_memory_write_ms", "on_pre_compress_ms")
    out: dict[str, dict[str, float]] = {}
    for f in fields:
        col = [s[f] for s in samples]
        out[f] = {
            "n": len(col),
            "p50": _percentile(col, 50),
            "p99": _percentile(col, 99),
            "mean": statistics.fmean(col) if col else 0.0,
        }
    return out


def _write_unavailable(reason: str) -> int:
    payload = {
        "schema_version": "1.0.0",
        "status": "unavailable",
        "reason": reason,
        "turns": 0,
    }
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"status": "unavailable", "reason": reason}))
    return 0


def _initialize_provider(provider: Any) -> None:
    """Best-effort initialize against $HERMES_HOME; harness is fault-tolerant."""
    try:
        provider.initialize("perf-bench-session", hermes_home=os.environ.get("HERMES_HOME") or "")
    except Exception:  # pragma: no cover
        return


def _await_client(provider: Any, deadline_seconds: float = 15.0) -> bool:
    """Wait for ``do_initialize``'s background bring-up to attach the client.

    Without this the bench loop runs while ``provider._client is None``,
    every hook short-circuits via ``_alive(p)``, and ``perf-baseline.json``
    records no-op sub-microsecond values that violate G01 / R11.
    """
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if provider._client is not None:
            return True
        time.sleep(0.1)
    return provider._client is not None


def _health_ok(provider: Any) -> bool:
    client = getattr(provider, "_client", None)
    if client is None:
        return False
    try:
        return bool((client.health() or {}).get("ok"))
    except Exception:
        return False


def run(turns: int = DEFAULT_TURNS) -> int:
    if not _server_available():
        return _write_unavailable("server prerequisites missing (bun / creds / deps)")
    try:
        provider = _provider()
    except Exception as exc:
        return _write_unavailable(f"provider import failed: {exc}")
    _initialize_provider(provider)
    if not _await_client(provider):
        return _write_unavailable("provider client did not come up against live server")
    if not _health_ok(provider):
        return _write_unavailable("provider health check failed against live server")
    samples = [_run_turn(provider, i) for i in range(turns)]
    payload = {
        "schema_version": "1.0.0",
        "status": "ok",
        "server_health_ok": True,
        "turns": turns,
        "metrics": _aggregate(samples),
    }
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run())
