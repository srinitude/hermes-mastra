"""R12 RED: capacity hints choose observe vs search by context need."""

from __future__ import annotations

from provider import MastraMemoryProvider


def test_capacity_hint_prefers_observe_only_when_observation_floor_is_low():
    p = MastraMemoryProvider()
    p._memory_usage_pct = 0.60
    p._user_usage_pct = 0.20
    p._observation_count = 2
    p._observation_floor = 5
    assert "mastra_observe" in p._capacity_hint()
    p._observation_count = 25
    assert "mastra_observe" not in p._capacity_hint()


def test_capacity_hint_recommends_search_for_explicit_recall_need():
    p = MastraMemoryProvider()
    p._memory_usage_pct = 0.10
    p._user_usage_pct = 0.10
    p._last_user_message = "remember what we did last time"
    p._recall_cache.clear()
    hint = p._capacity_hint()
    assert "mastra_search" in hint
    assert "mastra_observe" not in hint
