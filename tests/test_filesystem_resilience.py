"""R06 RED: filesystem failures degrade to logged no-ops."""

from __future__ import annotations

from pathlib import Path

import server_config


def test_pid_log_and_config_write_failures_do_not_raise(tmp_path, caplog):
    denied = tmp_path / "missing" / "nested"
    assert server_config.safe_write_pid(denied / "mastra.pid", 12345) is False
    log_path = server_config.safe_log_file(denied / "logs" / "mastra.log")
    assert log_path is None or isinstance(log_path, Path)
    assert (
        server_config.safe_save_config(denied / "mastra.json", {"auth_token_env": "SECRET"})
        is False
    )
    assert "SECRET" not in caplog.text
