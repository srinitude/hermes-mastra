"""Chaos smoke: faulted hooks never raise into the host loop."""

from __future__ import annotations

from provider import MastraMemoryProvider
from tests.helpers.chaos import assert_hooks_do_not_raise
from tests.helpers.fault_injectors import SlowCallClient


def test_chaos_faulted_hot_path_hooks_do_not_raise():
    p = MastraMemoryProvider()
    p._client = SlowCallClient(delay=0.001)
    p._cfg = {"recall_top_k": 4, "fault_injection": True}
    p._profile = "chaos-profile"
    p._thread = "chaos-thread"
    calls = [
        ("prefetch", p.prefetch, ("remember previous work",), {"session_id": "chaos-thread"}),
        ("sync_turn", p.sync_turn, ("user", "assistant"), {"session_id": "chaos-thread"}),
        ("on_pre_compress", p.on_pre_compress, ([{"role": "user", "content": "x"}],), {}),
        ("on_session_end", p.on_session_end, ([],), {}),
        ("on_memory_write", p.on_memory_write, ("add", "MEMORY.md", "fact"), {}),
        ("on_delegation", p.on_delegation, ("task", "result"), {}),
    ]
    assert_hooks_do_not_raise(calls)
    p.shutdown()
