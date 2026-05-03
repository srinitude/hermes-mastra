"""Tests for the SOUL/personality/AGENTS/goal/execute_code/batch surface.

Six new tool_observers — all tests-first, all non-blocking, all dedup'd
where it matters. Bundled in one file because they share fixtures and
the patterns are nearly identical (call hook → wait → assert observation
shape).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def slow_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.recall.return_value = ""
    c.write_observation.return_value = True
    return c


@pytest.fixture
def provider(fake_hermes_home, slow_client):
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    yield p
    p.shutdown()


def _wait_for(slow_client, attr: str, count: int = 1, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while getattr(slow_client, attr).call_count < count and time.monotonic() < deadline:
        time.sleep(0.02)


def _kinds(slow_client, kind: str) -> list:
    return [c for c in slow_client.write_observation.call_args_list if c.kwargs.get("kind") == kind]


# ---- A. SOUL.md observation --------------------------------------------


def test_soul_loaded_persists_observation(provider, slow_client):
    from provider_lifecycle import do_soul_loaded

    do_soul_loaded(provider, soul_text="You are a witty assistant.\nBe concise.")
    _wait_for(slow_client, "write_observation")
    assert _kinds(slow_client, "soul_loaded")
    text = _kinds(slow_client, "soul_loaded")[0].args[2]
    assert "SOUL.md" in text and "witty" in text


def test_soul_loaded_dedups_unchanged_content(provider, slow_client):
    from provider_lifecycle import do_soul_loaded

    for _ in range(3):
        do_soul_loaded(provider, soul_text="same content")
    time.sleep(0.05)
    assert len(_kinds(slow_client, "soul_loaded")) == 1


def test_soul_loaded_re_emits_on_edit(provider, slow_client):
    from provider_lifecycle import do_soul_loaded

    do_soul_loaded(provider, soul_text="original")
    do_soul_loaded(provider, soul_text="edited content")
    _wait_for(slow_client, "write_observation", count=2)
    assert len(_kinds(slow_client, "soul_loaded")) == 2


def test_soul_loaded_skips_blank(provider, slow_client):
    from provider_lifecycle import do_soul_loaded

    for v in ("", None, "   "):
        do_soul_loaded(provider, soul_text=v)
    time.sleep(0.05)
    assert not slow_client.write_observation.called


def test_soul_loaded_non_blocking(provider, slow_client):
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    from provider_lifecycle import do_soul_loaded

    t0 = time.monotonic()
    do_soul_loaded(provider, soul_text="some soul content")
    assert time.monotonic() - t0 < 0.1


# ---- B. personality change observation ---------------------------------


def test_personality_changed_persists(provider, slow_client):
    from provider_lifecycle import do_personality_changed

    do_personality_changed(provider, old_personality="default", new_personality="builder")
    _wait_for(slow_client, "write_observation")
    text = _kinds(slow_client, "personality_change")[0].args[2]
    assert "default" in text and "builder" in text


def test_personality_changed_skips_when_same(provider, slow_client):
    from provider_lifecycle import do_personality_changed

    do_personality_changed(provider, old_personality="builder", new_personality="builder")
    time.sleep(0.05)
    assert not slow_client.write_observation.called


def test_personality_changed_handles_initial_set(provider, slow_client):
    from provider_lifecycle import do_personality_changed

    do_personality_changed(provider, old_personality="", new_personality="velocity")
    _wait_for(slow_client, "write_observation")
    assert "velocity" in _kinds(slow_client, "personality_change")[0].args[2]


def test_personality_changed_non_blocking(provider, slow_client):
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    from provider_lifecycle import do_personality_changed

    t0 = time.monotonic()
    do_personality_changed(provider, old_personality="a", new_personality="b")
    assert time.monotonic() - t0 < 0.1


# ---- C. context-files extended form (entries with size + dir) ----------


def test_context_files_loaded_accepts_entries_form(provider, slow_client):
    from provider_lifecycle import do_context_files_loaded

    do_context_files_loaded(
        provider,
        entries=[
            ("/Users/k/work/proj/AGENTS.md", 1840, "/Users/k/work/proj"),
            ("/Users/k/work/proj/SOUL.md", 920, "/Users/k/work/proj"),
        ],
    )
    _wait_for(slow_client, "write_observation")
    text = _kinds(slow_client, "context_files_loaded")[0].args[2]
    assert "AGENTS.md" in text and "SOUL.md" in text
    assert "1840" in text
    assert "/Users/k/work/proj" in text


def test_context_files_loaded_legacy_files_form_still_works(provider, slow_client):
    from provider_lifecycle import do_context_files_loaded

    do_context_files_loaded(provider, files=["/path/AGENTS.md"])
    _wait_for(slow_client, "write_observation")
    assert _kinds(slow_client, "context_files_loaded")


def test_context_files_loaded_entries_dedup(provider, slow_client):
    from provider_lifecycle import do_context_files_loaded

    entries = [("/path/AGENTS.md", 100, "/path")]
    for _ in range(3):
        do_context_files_loaded(provider, entries=entries)
    time.sleep(0.05)
    assert len(_kinds(slow_client, "context_files_loaded")) == 1


# ---- D. cron-context skip for these three -------------------------------


@pytest.mark.parametrize(
    "hook_name,args",
    [
        ("do_soul_loaded", {"soul_text": "x"}),
        ("do_personality_changed", {"old_personality": "a", "new_personality": "b"}),
        ("do_context_files_loaded", {"files": ["/x/AGENTS.md"]}),
    ],
)
def test_cron_context_skips(fake_hermes_home, slow_client, hook_name, args):
    import provider_lifecycle as L
    from provider_lifecycle import do_initialize
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    p._client = None
    do_initialize(p, "sess", agent_context="cron")
    getattr(L, hook_name)(p, **args)
    time.sleep(0.05)
    assert not slow_client.write_observation.called
    p.shutdown()
