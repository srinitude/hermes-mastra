"""G11 — structured telemetry observability.

Every Mastra-bound hook helper records one entry into ``telemetry``'s
in-memory ring buffer (and one signed NDJSON line into
``$HERMES_HOME/logs/mastra.log`` when the home is set). This module
exercises the contract end-to-end with the live provider so the test
fails the day a hook stops emitting telemetry — for example after a
refactor reorders the lifecycle wrapper or a future module forgets to
route through ``telemetry.timed``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.red_phase import bring_up


def _hook_ops_recorded() -> set[str]:
    import telemetry

    return {entry.get("op") for entry in telemetry.snapshot(n=4096)}


def _parse_json_or_none(line: str) -> dict | None:
    if not line.strip().startswith("{"):
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _read_log_lines(home: Path) -> list[dict]:
    log_path = home / "logs" / "mastra.log"
    if not log_path.exists():
        return []
    parsed = [
        _parse_json_or_none(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    return [entry for entry in parsed if entry is not None and "op" in entry]


def _latest_mastra_call_entry() -> dict:
    import telemetry

    entries = [e for e in telemetry.snapshot(n=4096) if e.get("op") == "mastra_call"]
    assert entries, "telemetry buffer missing 'mastra_call' entry from _guarded_request"
    return entries[-1]


def _assert_mastra_call_entry(entry: dict) -> None:
    extra = entry.get("extra") or {}
    required = {
        "path",
        "method",
        "resource_id",
        "success",
        "tokens_in",
        "tokens_out",
        "token_source",
        "error_class",
    }
    missing = required - set(extra)
    assert not missing, f"mastra_call telemetry missing {sorted(missing)} (entry={entry!r})"
    assert entry["duration_us"] >= 0
    assert entry["outcome"] == "ok"
    assert extra["method"] == "get" and extra["path"] == "/health"
    assert extra["success"] is True and extra["error_class"] == ""
    assert extra["token_source"] == "estimated_chars"
    assert isinstance(extra["tokens_in"], int)
    assert isinstance(extra["tokens_out"], int) and extra["tokens_out"] > 0


@pytest.mark.integration
def test_every_hot_path_hook_emits_telemetry(mastra_server, mastra_client) -> None:
    """G11 — every wrapped lifecycle hook records exactly one telemetry entry."""
    import telemetry

    assert mastra_client.health() is not None
    telemetry.reset()
    provider = bring_up("g11-observability")
    try:
        provider.prefetch("g11 hello")
        provider.sync_turn("g11 user", "g11 assistant")
        provider.on_memory_write("add", "MEMORY.md", "g11 fact", {})
        provider.on_pre_compress([{"role": "user", "content": "g11 msg"}])
        ops = _hook_ops_recorded()
        expected = {"prefetch", "sync_turn", "memory_write", "pre_compress"}
        missing = expected - ops
        assert not missing, f"telemetry buffer missing ops {sorted(missing)}; saw {sorted(ops)}"
        import async_runner

        assert async_runner.get_runner().drain(timeout=10.0)
        log_entries = _read_log_lines(Path(str(mastra_server["home"])))
        ops_on_disk = {entry.get("op") for entry in log_entries}
        assert expected.issubset(ops_on_disk), (
            f"NDJSON log missing ops {sorted(expected - ops_on_disk)}; got {sorted(ops_on_disk)}"
        )
    finally:
        provider.shutdown()


@pytest.mark.integration
def test_mastra_client_call_emits_structured_mastra_call_telemetry(mastra_client) -> None:
    """G11 — every Mastra HTTP call records a structured ``mastra_call`` entry.

    The hard-goal observability clause says every Mastra call records latency,
    tokens, success/failure and outcome. Hook-level telemetry alone does not
    cover the HTTP boundary; this test asserts ``client._guarded_request``
    emits one structured ``mastra_call`` record per call, with required fields.
    """
    import telemetry

    telemetry.reset()
    result = mastra_client.health()
    assert result is not None, "live mastra server health() returned None"
    _assert_mastra_call_entry(_latest_mastra_call_entry())
