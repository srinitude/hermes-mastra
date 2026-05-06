"""R07 RED: server responses are validated before deserialization."""

from __future__ import annotations

import importlib
import importlib.util


def _guard():
    spec = importlib.util.find_spec("response_guard")
    assert spec is not None, "response_guard.py must exist before GREEN"
    return importlib.import_module("response_guard")


def test_non_json_wrong_schema_and_oversized_payloads_are_structured_errors():
    guard = _guard()
    bad_payloads = [b"not-json", b'{"observations": []}', b"{" + (b"x" * 1024 * 1024)]
    for payload in bad_payloads:
        try:
            guard.validate_recall_response(payload, max_bytes=1024)
        except guard.MastraResponseError as exc:
            assert exc.cause["category"] in {"non_json", "schema", "oversized"}
        else:  # pragma: no cover - RED evidence
            raise AssertionError(f"accepted malformed payload: {payload[:20]!r}")


def test_server_declares_healthz_timeout_and_bun_error_boundary():
    from pathlib import Path

    src = Path("server/src/index.ts").read_text(encoding="utf-8")
    routes = "\n".join(
        p.read_text(encoding="utf-8") for p in Path("server/src").glob("routes-*.ts")
    )
    assert "idleTimeout" in src and "error:" in src
    assert "/api/memory/healthz" in routes
    assert "503" in src + routes and "timeout" in src + routes
