"""Tests for the Mastra context-engine wrapper.

The wrapper takes any underlying ContextEngine (default: built-in
compressor) and adds two memory-aware behaviours without otherwise
changing its semantics:

  1. Just before delegating to ``compress()`` it does a SYNCHRONOUS
     fetch of the latest Mastra observations and injects them as a
     protected system message.  The compressor then preserves that
     block while summarising the middle of the conversation, so
     post-compression context contains up-to-date observations rather
     than just lossy summary.

  2. When ``update_from_response()`` reports that prompt tokens have
     crossed a "memory pressure" fraction of the threshold (default
     0.50), the wrapper raises ``recall_top_k`` for the *next*
     prefetch — denser recall before compression is triggered.

Every other ContextEngine method passes straight through to the
delegate with identical semantics.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_context_engine import MastraContextEngine

# Production `agent_context_engine.py` already does this same try/except —
# we mirror it in the test so the suite runs in a CI environment that
# doesn't have Hermes Agent installed (the `agent` namespace).
try:
    from agent.context_engine import ContextEngine
except ImportError:  # pragma: no cover — Hermes not installed in CI

    class ContextEngine:  # type: ignore[no-redef]
        pass


class _FakeDelegate(ContextEngine):
    """In-memory ContextEngine stub recording every call for assertions."""

    def __init__(self) -> None:
        self.compressed_with: list[list[dict[str, Any]]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.compress_focus: list[str | None] = []
        self.threshold_tokens = 100_000
        self.context_length = 200_000

    @property
    def name(self) -> str:
        return "fakecompressor"

    def update_from_response(self, usage):
        self.update_calls.append(dict(usage))
        self.last_prompt_tokens = int(usage.get("prompt_tokens", 0))

    def should_compress(self, prompt_tokens=None):
        return (prompt_tokens or self.last_prompt_tokens) > self.threshold_tokens

    def compress(self, messages, current_tokens=None, focus_topic=None):
        self.compressed_with.append(list(messages))
        self.compress_focus.append(focus_topic)
        # Pretend the delegate keeps every system message and the last user msg
        out = [m for m in messages if m.get("role") == "system"]
        if messages and messages[-1].get("role") != "system":
            out.append(messages[-1])
        return out

    def get_tool_schemas(self):
        return [{"name": "lcm_grep", "description": "stub"}]


class _FakeRecall:
    """Captures sync-fetch calls and serves the canned observation text."""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.fetch_count = 0

    def __call__(self) -> str:
        self.fetch_count += 1
        return self.text


class _FakeTopK:
    """Read/write hook for the wrapper to bump recall_top_k on pressure."""

    def __init__(self, initial: int = 4) -> None:
        self.value = initial
        self.history: list[int] = [initial]

    def get(self) -> int:
        return self.value

    def set(self, new: int) -> None:
        self.value = int(new)
        self.history.append(self.value)


# ---------------------------------------------------------------------------
# Identity / passthrough
# ---------------------------------------------------------------------------


def test_name_marks_wrapper_and_delegate():
    eng = MastraContextEngine(_FakeDelegate(), fetch_observations=_FakeRecall())
    assert eng.name == "fakecompressor+mastra"


def test_passthrough_token_state():
    delegate = _FakeDelegate()
    eng = MastraContextEngine(delegate, fetch_observations=_FakeRecall())
    eng.update_from_response({"prompt_tokens": 1234, "completion_tokens": 56})
    assert delegate.update_calls == [{"prompt_tokens": 1234, "completion_tokens": 56}]
    # Token-state mirrors the delegate so run_agent.py keeps working.
    assert eng.last_prompt_tokens == 1234
    assert eng.threshold_tokens == delegate.threshold_tokens
    assert eng.context_length == delegate.context_length


def test_should_compress_passthrough():
    delegate = _FakeDelegate()
    eng = MastraContextEngine(delegate, fetch_observations=_FakeRecall())
    assert eng.should_compress(50_000) is False
    assert eng.should_compress(150_000) is True


def test_get_tool_schemas_delegates():
    delegate = _FakeDelegate()
    eng = MastraContextEngine(delegate, fetch_observations=_FakeRecall())
    # Wrapper does NOT add new tools — the existing mastra_search /
    # mastra_recall tools live on the MemoryProvider, which is a
    # separate plugin layer.  Engine tools come from the delegate only.
    assert eng.get_tool_schemas() == [{"name": "lcm_grep", "description": "stub"}]


# ---------------------------------------------------------------------------
# Behaviour: synchronous observation injection before compression
# ---------------------------------------------------------------------------


def test_compress_injects_observations_before_delegate():
    delegate = _FakeDelegate()
    recall = _FakeRecall("- decided to use Bun for the server\n- prefers tabs over spaces")
    eng = MastraContextEngine(delegate, fetch_observations=recall)

    msgs = [
        {"role": "system", "content": "You are Hermes."},
        {"role": "user", "content": "first message"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "many turns later"},
    ]

    out = eng.compress(msgs)

    # Synchronous fetch happened exactly once before delegation
    assert recall.fetch_count == 1
    # The delegate received the messages WITH a mastra observation block
    # injected as a system message that the compressor must preserve.
    seen = delegate.compressed_with[0]
    injected = [m for m in seen if m.get("role") == "system" and "Mastra" in m.get("content", "")]
    assert len(injected) == 1
    assert "decided to use Bun" in injected[0]["content"]
    # And that block survives in the compressed output
    survivors = [m for m in out if m.get("role") == "system" and "Mastra" in m.get("content", "")]
    assert survivors


def test_compress_skips_injection_when_no_observations():
    delegate = _FakeDelegate()
    recall = _FakeRecall("")  # nothing to recall
    eng = MastraContextEngine(delegate, fetch_observations=recall)

    msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    eng.compress(msgs)

    seen = delegate.compressed_with[0]
    injected = [m for m in seen if "Mastra" in (m.get("content") or "")]
    assert injected == []


def test_compress_isolates_fetch_failures():
    """A broken Mastra server must NOT break compression."""
    delegate = _FakeDelegate()

    def boom():
        raise RuntimeError("server down")

    eng = MastraContextEngine(delegate, fetch_observations=boom)
    msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    out = eng.compress(msgs)
    # Delegate still ran; output is whatever the delegate produced.
    assert delegate.compressed_with == [msgs]
    assert out  # compressor produced something


def test_compress_forwards_focus_topic():
    delegate = _FakeDelegate()
    eng = MastraContextEngine(delegate, fetch_observations=_FakeRecall("obs"))
    eng.compress([{"role": "user", "content": "x"}], focus_topic="auth bug")
    assert delegate.compress_focus == ["auth bug"]


# ---------------------------------------------------------------------------
# Behaviour: token-aware recall_top_k boost
# ---------------------------------------------------------------------------


def test_top_k_bumps_when_pressure_exceeds_fraction():
    delegate = _FakeDelegate()
    delegate.threshold_tokens = 100_000
    top_k = _FakeTopK(initial=4)
    eng = MastraContextEngine(
        delegate,
        fetch_observations=_FakeRecall("obs"),
        get_top_k=top_k.get,
        set_top_k=top_k.set,
        pressure_fraction=0.60,
        boosted_top_k=8,
    )
    # 50k of a 100k threshold is below pressure → no change
    eng.update_from_response({"prompt_tokens": 50_000})
    assert top_k.value == 4
    # 70k exceeds 60% pressure → bump
    eng.update_from_response({"prompt_tokens": 70_000})
    assert top_k.value == 8


def test_top_k_resets_when_pressure_clears():
    delegate = _FakeDelegate()
    delegate.threshold_tokens = 100_000
    top_k = _FakeTopK(initial=4)
    eng = MastraContextEngine(
        delegate,
        fetch_observations=_FakeRecall("obs"),
        get_top_k=top_k.get,
        set_top_k=top_k.set,
        pressure_fraction=0.60,
        boosted_top_k=8,
    )
    eng.update_from_response({"prompt_tokens": 70_000})  # boost
    assert top_k.value == 8
    # After compression the prompt drops back well under pressure
    eng.update_from_response({"prompt_tokens": 30_000})
    assert top_k.value == 4


def test_top_k_no_boost_when_hooks_omitted():
    """Hooks are optional — without them the wrapper just passes through."""
    delegate = _FakeDelegate()
    eng = MastraContextEngine(delegate, fetch_observations=_FakeRecall())
    # Should not raise, even at high token count.
    eng.update_from_response({"prompt_tokens": 500_000})
