"""Tests for the integration between session_search and Mastra.

`session_search` searches the Hermes SQLite session database (raw
conversation transcripts) via FTS5 and LLM-summarizes matches. Mastra
holds the distilled observation log per-thread per-profile. The two are
complementary — and the plugin should expose them as such so the agent
knows when to reach for which.

Three integrations covered here:

  A. A new `mastra_search` tool — keyword search across stored
     observations (parallel API to session_search). Returns observations
     matching the query plus the threadId they came from.

  B. Tool schemas explicitly mention session_search in their descriptions
     so the agent picks the right tool for the right question.

  C. The system_prompt_block names session_search as a complementary
     recall surface when the session_search toolset is also active.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def slow_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.recall.return_value = "obs A\nobs B"
    c.search_observations.return_value = [
        {"thread": "thr-99", "text": "user prefers concise responses", "kind": "preference"},
        {"thread": "thr-42", "text": "decision: use mise as canonical CLI", "kind": "decision"},
    ]
    return c


@pytest.fixture
def provider(fake_hermes_home, slow_client):
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    yield p
    p.shutdown()


# ---- A. mastra_search tool exists and queries the right endpoint -----


def test_mastra_search_tool_schema_present(provider):
    """The plugin exposes a `mastra_search` tool alongside recall + observe."""
    schemas = provider.get_tool_schemas()
    names = {s["name"] for s in schemas}
    assert "mastra_search" in names, f"mastra_search must be in the tool surface (got: {names})"


def test_mastra_search_query_required(provider):
    schemas = {s["name"]: s for s in provider.get_tool_schemas()}
    params = schemas["mastra_search"]["parameters"]
    assert "query" in params["properties"]
    assert "query" in params.get("required", [])


def test_mastra_search_calls_client_search(provider, slow_client):
    result = provider.handle_tool_call(
        "mastra_search",
        {"query": "user preferences", "limit": 5},
    )
    parsed = json.loads(result)
    assert parsed["profile"] == "test-profile"
    assert "observations" in parsed
    assert len(parsed["observations"]) == 2
    slow_client.search_observations.assert_called_once()
    call_kwargs = slow_client.search_observations.call_args.kwargs
    call_args = slow_client.search_observations.call_args.args
    # Accept either positional or kwarg form
    profile = call_kwargs.get("profile") or (call_args[1] if len(call_args) > 1 else None)
    query = call_kwargs.get("query") or (call_args[0] if call_args else None)
    assert profile == "test-profile"
    assert query == "user preferences"


def test_mastra_search_returns_thread_ids(provider, slow_client):
    """Each result MUST carry the threadId so the agent can correlate
    with session_search results from the same session."""
    result = provider.handle_tool_call("mastra_search", {"query": "anything"})
    parsed = json.loads(result)
    assert all("thread" in o for o in parsed["observations"]), (
        "every observation result must include its threadId — without it "
        "the agent can't correlate Mastra hits with session_search hits."
    )


def test_mastra_search_limit_clamped(provider, slow_client):
    """Mirror session_search's [1, 20] clamp so behaviour matches."""
    provider.handle_tool_call("mastra_search", {"query": "x", "limit": 999})
    call_kwargs = slow_client.search_observations.call_args.kwargs
    call_args = slow_client.search_observations.call_args.args
    limit = call_kwargs.get("limit") or (call_args[2] if len(call_args) > 2 else None)
    assert isinstance(limit, int) and 1 <= limit <= 20, (
        f"limit must be clamped to [1, 20]; got {limit!r}"
    )


def test_mastra_search_handles_zero_results(provider, slow_client):
    slow_client.search_observations.return_value = []
    result = provider.handle_tool_call("mastra_search", {"query": "no matches"})
    parsed = json.loads(result)
    assert parsed["observations"] == []
    assert "no matches" in parsed.get("message", "").lower() or parsed["count"] == 0


def test_mastra_search_no_op_when_server_down(fake_hermes_home, slow_client):
    """Tool returns a clean error JSON, never raises."""
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    p._client = None
    result = p.handle_tool_call("mastra_search", {"query": "x"})
    parsed = json.loads(result)
    assert "error" in parsed
    p.shutdown()


# ---- B. tool descriptions cross-reference session_search ----------------


def test_recall_tool_description_mentions_session_search(provider):
    schemas = {s["name"]: s for s in provider.get_tool_schemas()}
    desc = schemas["mastra_recall"]["description"].lower()
    assert "session_search" in desc, (
        "mastra_recall description must mention session_search so the "
        "agent knows when to reach for which (raw transcripts vs observations)."
    )


def test_search_tool_description_mentions_session_search(provider):
    schemas = {s["name"]: s for s in provider.get_tool_schemas()}
    desc = schemas["mastra_search"]["description"].lower()
    assert "session_search" in desc


# ---- C. system_prompt_block hints at the integration --------------------


def test_system_prompt_mentions_session_search(provider):
    """When Mastra is active, the system prompt should hint that
    session_search complements it."""
    block = provider.system_prompt_block()
    assert "session_search" in block.lower(), (
        "system_prompt_block should name session_search so the agent learns "
        "the recall hierarchy: observations (Mastra) for distilled facts, "
        "session_search for raw past-conversation transcripts."
    )


# ---- D. non-blocking + cron-skip guarantees still hold ------------------


def test_search_is_synchronous_returning_value(provider, slow_client):
    """Unlike write hooks, this is a query tool the agent awaits — must
    actually return real data, not enqueue and return blank."""
    result = provider.handle_tool_call("mastra_search", {"query": "x"})
    parsed = json.loads(result)
    assert "observations" in parsed
    assert isinstance(parsed["observations"], list)


def test_search_skipped_in_cron_context(fake_hermes_home, slow_client):
    from provider_lifecycle import do_initialize
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    p._client = None
    do_initialize(p, "sess", agent_context="cron")
    schemas = p.get_tool_schemas()
    assert schemas == [], "tool surface must be empty in cron context"
    p.shutdown()
