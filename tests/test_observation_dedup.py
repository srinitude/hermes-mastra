"""R04 RED: observation writes are idempotent per profile/thread/kind/text."""

from __future__ import annotations

import importlib
import importlib.util


def _module():
    spec = importlib.util.find_spec("observation_dedup")
    assert spec is not None, "observation_dedup.py must exist before GREEN"
    return importlib.import_module("observation_dedup")


def test_identical_observations_are_claimed_once_and_keyed_by_profile():
    module = _module()
    dedup = module.ObservationDeduper(max_size=4)
    first = ("thread-a", "profile-a", "memory_write", "  Same Text\n")
    assert dedup.should_write(*first) is True
    assert dedup.should_write(*first) is False
    assert dedup.should_write("thread-a", "profile-b", "memory_write", "Same Text") is True
    assert dedup.should_write("thread-a", "profile-a", "delegation", "Same Text") is True


def test_dedup_lru_is_bounded():
    module = _module()
    dedup = module.ObservationDeduper(max_size=2)
    for i in range(4):
        assert dedup.should_write(f"thread-{i}", "profile", "kind", "text") is True
    assert len(dedup) == 2
