"""R09 RED: cron context skips bring-up and all tools/hooks."""

from __future__ import annotations

from provider import MastraMemoryProvider
from tests.helpers.fault_injectors import RecordingClient


def test_cron_initialize_clears_client_and_hides_tools():
    p = MastraMemoryProvider()
    p._client = RecordingClient()
    p.initialize("cron-session", agent_context="cron", platform="cli")
    assert p._cron_skipped is True
    assert p._client is None
    assert p.get_tool_schemas() == []
    p.sync_turn("user", "assistant")
    p.prefetch("remember last time", session_id="cron-session")
    assert p._client is None
