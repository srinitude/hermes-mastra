"""Mastra-aware ContextEngine wrapper.

This wraps any underlying :class:`ContextEngine` (built-in
``compressor`` by default, or anything else like LCM) and adds two
memory-aware behaviours without otherwise altering its semantics:

1. **Synchronous observation injection at compress time.**  Just
   before delegating to ``compress()`` we fetch the latest Mastra
   observations for the current thread and prepend them as a
   protected system message.  The compressor then preserves that
   block while summarising the middle of the conversation, so
   post-compression context contains *current* observations rather
   than only the lossy summary.  This addresses the docs' explicit
   note that ``MemoryProvider.on_pre_compress`` returns are *discarded*
   — putting the recall block on the message list instead means it
   actually rides through compression.

2. **Token-aware ``recall_top_k`` boost.**  When ``update_from_response``
   reports prompt tokens crossing a "memory pressure" fraction of the
   compressor's threshold, the wrapper raises the MemoryProvider's
   ``recall_top_k`` config so the *next* prefetch returns more
   observations.  After pressure clears (e.g. post-compression) the
   value reverts.  The MemoryProvider has no token-counting context
   of its own; the engine does.

Every other ``ContextEngine`` method is a straight passthrough.  Token
state attributes (``last_prompt_tokens`` etc.) are mirrored from the
delegate so ``run_agent.py``'s display/logging sees no change.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

try:
    from agent.context_engine import ContextEngine
except ImportError:  # pragma: no cover — pytest stub

    class ContextEngine:  # type: ignore[no-redef]
        pass


logger = logging.getLogger(__name__)


# Read-only attributes mirrored from the delegate after each delegating call.
_MIRRORED_TOKEN_ATTRS = (
    "last_prompt_tokens",
    "last_completion_tokens",
    "last_total_tokens",
    "threshold_tokens",
    "context_length",
    "compression_count",
    "threshold_percent",
    "protect_first_n",
    "protect_last_n",
)


class MastraContextEngine(ContextEngine):
    """ContextEngine wrapper that injects Mastra observations and
    bumps recall density under memory pressure.

    Args:
        delegate: The underlying ContextEngine doing the real work.
            Default in production is the built-in ``ContextCompressor``;
            users can pass any engine they like.
        fetch_observations: Zero-arg callable returning the current
            observation block (string).  Called synchronously during
            ``compress()``.  May raise — exceptions are swallowed and
            logged so a dead Mastra server never blocks compression.
        get_top_k / set_top_k: Optional read/write hooks for the
            MemoryProvider's ``recall_top_k`` config.  When both are
            provided, the wrapper boosts on memory pressure and reverts
            when pressure clears.  When omitted, no boost happens.
        pressure_fraction: Fraction of ``threshold_tokens`` at which
            we boost ``recall_top_k``.  Default 0.50.
        boosted_top_k: Value to set when boosting.  Default 8.
    """

    def __init__(
        self,
        delegate: ContextEngine,
        *,
        fetch_observations: Callable[[], str],
        get_top_k: Callable[[], int] | None = None,
        set_top_k: Callable[[int], None] | None = None,
        pressure_fraction: float = 0.50,
        boosted_top_k: int = 8,
        name_override: str | None = None,
    ) -> None:
        self._delegate = delegate
        self._fetch_observations = fetch_observations
        self._get_top_k = get_top_k
        self._set_top_k = set_top_k
        self._pressure_fraction = float(pressure_fraction)
        self._boosted_top_k = int(boosted_top_k)
        self._baseline_top_k: int | None = None
        self._name_override = name_override
        self._sync_token_state()

    # -- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        if self._name_override:
            return self._name_override
        return f"{self._delegate.name}+mastra"

    # -- token state -------------------------------------------------------

    def _sync_token_state(self) -> None:
        for attr in _MIRRORED_TOKEN_ATTRS:
            if hasattr(self._delegate, attr):
                setattr(self, attr, getattr(self._delegate, attr))

    def update_from_response(self, usage: dict[str, Any]) -> None:
        self._delegate.update_from_response(usage)
        self._sync_token_state()
        self._maybe_adjust_top_k()

    def _maybe_adjust_top_k(self) -> None:
        if self._get_top_k is None or self._set_top_k is None:
            return
        threshold = getattr(self._delegate, "threshold_tokens", 0) or 0
        if threshold <= 0:
            return
        used = getattr(self._delegate, "last_prompt_tokens", 0) or 0
        pressure_at = self._pressure_fraction * threshold
        try:
            current = int(self._get_top_k())
        except Exception:  # pragma: no cover — defensive
            return
        if used >= pressure_at:
            if self._baseline_top_k is None:
                self._baseline_top_k = current
            if current < self._boosted_top_k:
                self._safe_set_top_k(self._boosted_top_k)
        elif self._baseline_top_k is not None:
            self._safe_set_top_k(self._baseline_top_k)
            self._baseline_top_k = None

    def _safe_set_top_k(self, value: int) -> None:
        try:
            self._set_top_k(value)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("mastra engine: set_top_k failed: %s", exc)

    # -- compaction --------------------------------------------------------

    def should_compress(self, prompt_tokens: int | None = None) -> bool:
        return self._delegate.should_compress(prompt_tokens)

    def should_compress_preflight(self, messages: list[dict[str, Any]]) -> bool:
        return self._delegate.should_compress_preflight(messages)

    def has_content_to_compress(self, messages: list[dict[str, Any]]) -> bool:
        return self._delegate.has_content_to_compress(messages)

    def compress(
        self,
        messages: list[dict[str, Any]],
        current_tokens: int | None = None,
        focus_topic: str | None = None,
    ) -> list[dict[str, Any]]:
        observation_block = self._fetch_observation_block()
        if observation_block:
            injected = {
                "role": "system",
                "content": (
                    "## Mastra observations (preserved across compression)\n" + observation_block
                ),
            }
            messages = self._inject_observation_block(messages, injected)
        out = self._delegate.compress(
            messages, current_tokens=current_tokens, focus_topic=focus_topic
        )
        self._sync_token_state()
        return out

    def _fetch_observation_block(self) -> str:
        try:
            text = self._fetch_observations() or ""
        except Exception as exc:
            logger.debug("mastra engine: observation fetch failed: %s", exc)
            return ""
        return text.strip()

    @staticmethod
    def _inject_observation_block(
        messages: list[dict[str, Any]],
        injected: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Insert *injected* directly after the leading system message(s).

        Compressors universally protect the head of the message list,
        so the recall block lands inside the protected zone.
        """
        out: list[dict[str, Any]] = []
        seen_first_non_system = False
        inserted = False
        for msg in messages:
            if not inserted and seen_first_non_system:
                out.append(injected)
                inserted = True
            if msg.get("role") != "system":
                seen_first_non_system = True
            out.append(msg)
        if not inserted:
            out.append(injected)
        return out

    # -- session lifecycle -------------------------------------------------

    def on_session_start(self, session_id: str, **kwargs) -> None:
        self._delegate.on_session_start(session_id, **kwargs)

    def on_session_end(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        self._delegate.on_session_end(session_id, messages)

    def on_session_reset(self) -> None:
        self._delegate.on_session_reset()
        self._sync_token_state()
        self._baseline_top_k = None

    # -- engine tools ------------------------------------------------------

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return self._delegate.get_tool_schemas()

    def handle_tool_call(self, name: str, args: dict[str, Any], **kwargs) -> str:
        return self._delegate.handle_tool_call(name, args, **kwargs)

    # -- status / model switch --------------------------------------------

    def get_status(self) -> dict[str, Any]:
        status = dict(self._delegate.get_status())
        status["wrapper"] = "mastra"
        status["recall_boost_active"] = self._baseline_top_k is not None
        return status

    def update_model(self, model: str, context_length: int, **kwargs) -> None:
        self._delegate.update_model(model, context_length, **kwargs)
        self._sync_token_state()
