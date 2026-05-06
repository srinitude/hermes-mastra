"""R05 RED: profile flips never leak cached observations."""

from __future__ import annotations

from recall_cache import RecallCache
from tests.helpers.fault_injectors import RecordingClient


def test_recall_cache_is_partitioned_by_profile_and_thread():
    cache = RecallCache(max_entries=4)
    cache.store("profile-a", "thread-1", "alpha observation")
    cache.store("profile-b", "thread-1", "beta observation")
    assert cache.get("profile-a", "thread-1") == "alpha observation"
    assert cache.get("profile-b", "thread-1") == "beta observation"
    cache.clear_profile("profile-a")
    assert cache.get("profile-a", "thread-1") == ""
    assert cache.get("profile-b", "thread-1") == "beta observation"


def test_profile_flip_writes_one_lineage_observation_and_clears_cache():
    from provider import MastraMemoryProvider

    p = MastraMemoryProvider()
    p._client = RecordingClient()
    p._recall_cache.store("old", "thread", "old observation")
    p._profile = "old"
    p._thread = "thread"
    p.on_turn_start(2, "hello", profile="new")
    calls = [c for c in p._client.calls if c[0] == "write_observation"]
    assert len(calls) == 1
    assert p._recall_cache.get("old", "thread") == ""
