"""R13 RED: parent thread observations warm the new thread cache."""

from __future__ import annotations

from provider import MastraMemoryProvider
from tests.helpers.fault_injectors import RecordingClient


def test_session_switch_prefetches_parent_thread_into_new_thread(monkeypatch):
    import provider_lifecycle as lifecycle

    p = MastraMemoryProvider()
    p._client = RecordingClient()
    p._client.recall_text = "parent observation"
    p._profile = "profile-a"
    p._thread = "child-thread"
    p._cfg = {"recall_top_k": 4}
    monkeypatch.setattr(lifecycle._runner_loader, "submit", lambda fn: fn())
    p.on_session_switch("new-thread", parent_session_id="parent-thread")
    recall_calls = [c for c in p._client.calls if c[0] == "recall"]
    assert recall_calls[0][1][:2] == ("parent-thread", "profile-a")
    assert p._recall_cache.get("profile-a", "new-thread") == "parent observation"
