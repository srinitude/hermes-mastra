"""Two new model-driven tools — semantic_search + working_memory_get.

The Hermes integration map (§2.3 + §2.2) routes semantic recall and
working-memory READ deliberately as TOOLS rather than hot-path hooks:

  * Semantic recall is too expensive (vector query) for prefetch's 2 ms
    budget — but valuable when the model knows it needs deep search.
  * Working memory READ duplicates MEMORY.md / USER.md if injected into
    every system prompt — but useful when the model wants to inspect
    what was mirrored.

Both are exposed via `handle_tool_call`, which is the single
deliberately-blocking surface in the plugin (§1).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    # Default canned responses — overridden per test
    c.semantic_search.return_value = [
        {"thread": "thr-7", "text": "deadlines were tight in Q3", "score": 0.91},
        {"thread": "thr-2", "text": "shipped feature X on March 12", "score": 0.84},
    ]
    c.get_working_memory.return_value = "# User Profile\n- Name: Alice\n- Role: Lead engineer\n"
    return c


@pytest.fixture
def provider(fake_hermes_home, fake_client):
    from tests.helpers import make_provider

    p = make_provider(fake_client)
    yield p
    p.shutdown()


# ---------------------------------------------------------------------------
# A. mastra_semantic_search — vector-search tool
# ---------------------------------------------------------------------------


def test_semantic_search_in_tool_schemas(provider):
    names = {s["name"] for s in provider.get_tool_schemas()}
    assert "mastra_semantic_search" in names


def test_semantic_search_query_required(provider):
    schemas = {s["name"]: s for s in provider.get_tool_schemas()}
    params = schemas["mastra_semantic_search"]["parameters"]
    assert "query" in params["required"]


def test_semantic_search_calls_client_semantic_search(provider, fake_client):
    provider.handle_tool_call(
        "mastra_semantic_search",
        {"query": "what did we ship in March?", "limit": 5},
    )
    fake_client.semantic_search.assert_called_once()
    args = fake_client.semantic_search.call_args
    # Accept either positional or kwarg form — implementation choice.
    query = args.kwargs.get("query") or (args.args[0] if args.args else None)
    profile = args.kwargs.get("profile") or (args.args[1] if len(args.args) > 1 else None)
    limit = args.kwargs.get("limit") or (args.args[2] if len(args.args) > 2 else None)
    assert query == "what did we ship in March?"
    assert profile == "test-profile"
    assert limit == 5


def test_semantic_search_limit_clamped_to_20(provider, fake_client):
    provider.handle_tool_call(
        "mastra_semantic_search",
        {"query": "x", "limit": 999},
    )
    args = fake_client.semantic_search.call_args
    limit = args.kwargs.get("limit") or (args.args[2] if len(args.args) > 2 else None)
    assert limit == 20  # clamped


def test_semantic_search_returns_thread_correlation(provider, fake_client):
    raw = provider.handle_tool_call("mastra_semantic_search", {"query": "tight"})
    payload = json.loads(raw)
    assert payload["count"] == 2
    threads = [o["thread"] for o in payload["observations"]]
    assert "thr-7" in threads


def test_semantic_search_handles_zero_results(provider, fake_client):
    fake_client.semantic_search.return_value = []
    raw = provider.handle_tool_call("mastra_semantic_search", {"query": "no matches"})
    payload = json.loads(raw)
    assert payload["count"] == 0
    msg = (payload.get("message") or "").lower()
    # Some signal that nothing was found, ideally pointing at the alternative.
    assert "no" in msg and ("match" in msg or "result" in msg or "fall back" in msg)


def test_semantic_search_no_op_when_server_down(fake_hermes_home):
    """Tool path must error gracefully when the server is unreachable."""
    from tests.helpers import make_provider

    p = make_provider(MagicMock())
    p._client = None
    raw = p.handle_tool_call("mastra_semantic_search", {"query": "x"})
    payload = json.loads(raw)
    assert "error" in payload


def test_semantic_search_description_distinguishes_from_keyword(provider):
    schemas = {s["name"]: s for s in provider.get_tool_schemas()}
    desc = schemas["mastra_semantic_search"]["description"].lower()
    # Must reference both "semantic" and the alternative tool by name so
    # the model picks the right one.
    assert "semantic" in desc or "vector" in desc or "meaning" in desc
    assert "mastra_search" in desc  # points to keyword variant


# ---------------------------------------------------------------------------
# B. mastra_working_memory — read working memory mirror
# ---------------------------------------------------------------------------


def test_working_memory_get_in_tool_schemas(provider):
    names = {s["name"] for s in provider.get_tool_schemas()}
    assert "mastra_working_memory" in names


def test_working_memory_get_no_required_params(provider):
    schemas = {s["name"]: s for s in provider.get_tool_schemas()}
    params = schemas["mastra_working_memory"]["parameters"]
    # Reading working memory takes no required args.
    assert params.get("required", []) == []


def test_working_memory_get_calls_client_get_working_memory(provider, fake_client):
    provider.handle_tool_call("mastra_working_memory", {})
    fake_client.get_working_memory.assert_called_once()
    args = fake_client.get_working_memory.call_args
    profile = args.kwargs.get("profile") or (args.args[0] if args.args else None)
    assert profile == "test-profile"


def test_working_memory_get_returns_text(provider, fake_client):
    raw = provider.handle_tool_call("mastra_working_memory", {})
    payload = json.loads(raw)
    assert payload["profile"] == "test-profile"
    assert "Alice" in payload["working_memory"]


def test_working_memory_get_handles_empty(provider, fake_client):
    fake_client.get_working_memory.return_value = ""
    raw = provider.handle_tool_call("mastra_working_memory", {})
    payload = json.loads(raw)
    # Empty string is a legitimate state (nothing mirrored yet).
    assert payload["working_memory"] == ""
    assert "empty" in (payload.get("message") or "").lower() or payload["working_memory"] == ""


def test_working_memory_description_says_built_in_is_canonical(provider):
    """The model must know MEMORY.md / USER.md is authoritative."""
    schemas = {s["name"]: s for s in provider.get_tool_schemas()}
    desc = schemas["mastra_working_memory"]["description"].lower()
    assert "memory.md" in desc or "memory tool" in desc
    assert "mirror" in desc or "authoritative" in desc or "built-in" in desc


# ---------------------------------------------------------------------------
# C. Both tools are confined to handle_tool_call (not on hot path)
# ---------------------------------------------------------------------------


def test_neither_new_tool_runs_during_prefetch(provider, fake_client):
    """Hot-path prefetch must NEVER trigger semantic_search or get_working_memory."""
    fake_client.semantic_search.reset_mock()
    fake_client.get_working_memory.reset_mock()
    provider.prefetch("anything")
    assert fake_client.semantic_search.call_count == 0
    assert fake_client.get_working_memory.call_count == 0


def test_neither_new_tool_runs_during_sync_turn(provider, fake_client):
    fake_client.semantic_search.reset_mock()
    fake_client.get_working_memory.reset_mock()
    provider.sync_turn("u", "a")
    assert fake_client.semantic_search.call_count == 0
    assert fake_client.get_working_memory.call_count == 0
