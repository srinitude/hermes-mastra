"""Tiny helpers used across provider_lifecycle hooks. Kept here so the
main lifecycle module fits the 200-LOC budget."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def alive(p) -> bool:
    return not p._cron_skipped and p._client is not None


def has_profile_kwarg(kwargs: dict) -> bool:
    for key in ("agent_identity", "profile"):
        v = kwargs.get(key)
        if isinstance(v, str) and v.strip():
            return True
    return False


def resolve_profile(kwargs: dict) -> str:
    """Pick the profile name from any of the kwargs Hermes might use."""
    for key in ("agent_identity", "profile"):
        v = kwargs.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "default"


def safe_call(fn) -> None:
    try:
        fn()
    except Exception as exc:  # pragma: no cover
        logger.debug("mastra: background work failed: %s", exc)
