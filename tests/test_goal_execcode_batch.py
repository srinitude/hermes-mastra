"""Tests for /goal, execute_code, and batch_runner observation hooks."""

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


# ---- /goal slash command ------------------------------------------------


def test_goal_command_persists_observation(provider, slow_client):
    from provider_lifecycle import do_goal_command

    do_goal_command(provider, goal_text="ship 1.0 by EOQ")
    _wait_for(slow_client, "write_observation")
    assert "ship 1.0" in _kinds(slow_client, "goal_set")[0].args[2]


def test_goal_command_skips_empty(provider, slow_client):
    from provider_lifecycle import do_goal_command

    for v in ("", None, "   "):
        do_goal_command(provider, goal_text=v)
    time.sleep(0.05)
    assert not slow_client.write_observation.called


def test_goal_command_dedup_within_session(provider, slow_client):
    from provider_lifecycle import do_goal_command

    do_goal_command(provider, goal_text="finish migration")
    do_goal_command(provider, goal_text="finish migration")
    time.sleep(0.05)
    assert len(_kinds(slow_client, "goal_set")) == 1


def test_goal_command_re_emits_when_goal_changes(provider, slow_client):
    from provider_lifecycle import do_goal_command

    do_goal_command(provider, goal_text="goal A")
    do_goal_command(provider, goal_text="goal B")
    _wait_for(slow_client, "write_observation", count=2)
    assert len(_kinds(slow_client, "goal_set")) == 2


# ---- execute_code tool --------------------------------------------------


def test_execute_code_persists_observation(provider, slow_client):
    from provider_lifecycle import do_execute_code

    code = "from hermes_tools import web_search\nprint(web_search('mastra'))"
    do_execute_code(
        provider, code=code, exit_code=0, output_excerpt="Mastra is a TypeScript agent framework..."
    )
    _wait_for(slow_client, "write_observation")
    text = _kinds(slow_client, "execute_code")[0].args[2]
    assert "exit=0" in text and "web_search" in text


def test_execute_code_records_failures(provider, slow_client):
    from provider_lifecycle import do_execute_code

    do_execute_code(
        provider,
        code="x = undefined_var",
        exit_code=1,
        output_excerpt="NameError: name 'undefined_var'",
    )
    _wait_for(slow_client, "write_observation")
    text = _kinds(slow_client, "execute_code")[0].args[2]
    assert "exit=1" in text


def test_execute_code_truncates_long_output(provider, slow_client):
    from provider_lifecycle import do_execute_code

    do_execute_code(provider, code="print('x' * 100000)", exit_code=0, output_excerpt="X" * 100_000)
    _wait_for(slow_client, "write_observation")
    text = _kinds(slow_client, "execute_code")[0].args[2]
    assert len(text) < 8000


def test_execute_code_non_blocking(provider, slow_client):
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    from provider_lifecycle import do_execute_code

    t0 = time.monotonic()
    do_execute_code(provider, code="x", exit_code=0, output_excerpt="")
    assert time.monotonic() - t0 < 0.1


# ---- batch_runner start / end ------------------------------------------


def test_batch_start_persists_observation(provider, slow_client):
    from provider_lifecycle import do_batch_start

    do_batch_start(
        provider,
        run_id="batch-2026-05-03-abc",
        total=12,
        parallel=4,
        prompt_summary="GRPO sweep on 12 prompts",
    )
    _wait_for(slow_client, "write_observation")
    text = _kinds(slow_client, "batch_start")[0].args[2]
    assert "batch-2026-05-03-abc" in text and "12" in text and "4" in text


def test_batch_end_persists_with_stats(provider, slow_client):
    from provider_lifecycle import do_batch_end

    do_batch_end(
        provider, run_id="batch-2026-05-03-abc", succeeded=11, failed=1, total_seconds=420.5
    )
    _wait_for(slow_client, "write_observation")
    text = _kinds(slow_client, "batch_end")[0].args[2]
    assert "11" in text and "420" in text


def test_batch_hooks_skip_when_run_id_empty(provider, slow_client):
    from provider_lifecycle import do_batch_end, do_batch_start

    do_batch_start(provider, run_id="", total=1, parallel=1, prompt_summary="x")
    do_batch_end(provider, run_id="", succeeded=1, failed=0, total_seconds=1.0)
    time.sleep(0.05)
    assert not slow_client.write_observation.called


def test_batch_hooks_non_blocking(provider, slow_client):
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    from provider_lifecycle import do_batch_end, do_batch_start

    t0 = time.monotonic()
    do_batch_start(provider, run_id="r", total=1, parallel=1, prompt_summary="p")
    do_batch_end(provider, run_id="r", succeeded=1, failed=0, total_seconds=1.0)
    assert time.monotonic() - t0 < 0.1


# ---- cron-context skip --------------------------------------------------


@pytest.mark.parametrize(
    "hook_name,args",
    [
        ("do_goal_command", {"goal_text": "x"}),
        ("do_execute_code", {"code": "x", "exit_code": 0, "output_excerpt": ""}),
        ("do_batch_start", {"run_id": "r", "total": 1, "parallel": 1, "prompt_summary": "p"}),
        ("do_batch_end", {"run_id": "r", "succeeded": 1, "failed": 0, "total_seconds": 1.0}),
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
