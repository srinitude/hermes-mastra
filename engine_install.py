"""Hermes ContextEngine wiring for the mastra plugin.

Lives in its own module so the plugin's `__init__.py` stays under the
200-LOC budget required by `tests/test_code_size_policy.py`.

The `install_engine(ctx, provider)` function is called from `register()`
and:

  1. Skips silently if the host gateway/CLI doesn't expose
     ``register_context_engine`` (older Hermes versions).
  2. Skips if the user disabled the wrapper via
     ``context_engine_wrapper: false`` in the plugin config.
  3. Otherwise constructs a built-in ``ContextCompressor`` delegate
     and wraps it with ``MastraContextEngine`` so observations are
     injected at compression time and ``recall_top_k`` boosts under
     memory pressure.

Failure-isolated: any exception during install is logged at WARNING
and the rest of the plugin keeps working with the built-in compressor.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def install_engine(ctx: Any, provider: Any) -> None:
    """Install the Mastra-aware ContextEngine wrapper if the host allows."""
    if not hasattr(ctx, "register_context_engine"):
        return
    cfg = _load_cfg()
    if not cfg.get("context_engine_wrapper", True):
        return
    try:
        engine = _build_engine(provider, cfg)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("mastra: failed to install context-engine wrapper: %s", exc)
        return
    ctx.register_context_engine(engine)
    logger.info("mastra: registered ContextEngine wrapper around compressor")


def _load_cfg() -> dict:
    try:
        try:
            from .server_manager import load_config  # type: ignore  # noqa: PLC0415
        except ImportError:
            from server_manager import load_config  # type: ignore[no-redef]  # noqa: PLC0415
        return load_config() or {}
    except Exception:  # pragma: no cover
        return {}


def _build_engine(provider: Any, cfg: dict):
    """Construct ``MastraContextEngine(ContextCompressor(...))``."""
    try:
        from .agent_context_engine import MastraContextEngine  # type: ignore  # noqa: PLC0415
    except ImportError:
        from agent_context_engine import (  # noqa: PLC0415
            MastraContextEngine,  # type: ignore[no-redef]
        )
    from agent.context_compressor import ContextCompressor  # noqa: PLC0415

    delegate = ContextCompressor(model="placeholder", quiet_mode=True)
    return MastraContextEngine(
        delegate,
        fetch_observations=_fetch_factory(provider),
        get_top_k=lambda: int(provider._cfg.get("recall_top_k", 4)),
        set_top_k=_set_top_k_factory(provider),
        pressure_fraction=float(cfg.get("context_engine_pressure_fraction", 0.50)),
        boosted_top_k=int(cfg.get("context_engine_boosted_top_k", 8)),
        # Match by `context.engine: "mastra"` in config.yaml.
        name_override="mastra",
    )


def _fetch_factory(provider: Any) -> Callable[[], str]:
    """Return a zero-arg fn yielding the cached observation block.

    Reads from ``provider._recall_cache`` first (no I/O) and only falls
    back to ``client.recall`` when the cache is empty *and* the client
    is alive — keeping `compress()` non-blocking on the hot path.
    """

    def _fetch() -> str:
        text = provider._recall_cache.get()
        if text:
            return text
        client = provider._client
        if client is None:
            return ""
        try:
            top_k = int(provider._cfg.get("recall_top_k", 4))
            return client.recall(provider._thread, provider._profile, top_k) or ""
        except Exception:
            return ""

    return _fetch


def _set_top_k_factory(provider: Any) -> Callable[[int], None]:
    def _set(value: int) -> None:
        provider._cfg["recall_top_k"] = int(value)

    return _set
