"""R10 RED: partial init failures leave deterministic no-op state."""

from __future__ import annotations

from provider import MastraMemoryProvider


def test_initialize_failure_before_client_assignment_never_escapes(monkeypatch, tmp_path):
    import provider_lifecycle as lifecycle

    p = MastraMemoryProvider()
    monkeypatch.setattr(lifecycle, "load_config", lambda: {"recall_top_k": 4})
    monkeypatch.setattr(lifecycle._runner_loader, "submit", lambda fn: fn())
    monkeypatch.setattr(lifecycle, "ensure_running", lambda: (_ for _ in ()).throw(OSError("boom")))
    p.initialize("session", hermes_home=str(tmp_path), profile="profile-a")
    assert p._client is None
    assert p.prefetch("q") == ""
    p.sync_turn("u", "a")
