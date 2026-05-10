"""Tiny helpers used across provider_lifecycle hooks. Kept here so the
main lifecycle module fits the 200-LOC budget."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_RECAP_RE = re.compile(
    r"\b("
    r"what (did|do) i (do|work)|"
    r"previously|earlier today|"
    r"yesterday i|did i (do|work)|"
    r"last (week|time|session)|"
    r"recap|recall what"
    r")\b",
    re.IGNORECASE,
)


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


def _msg_text(m: dict[str, Any]) -> str:
    body = m.get("content") or m.get("text") or ""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        if isinstance(body.get("content"), str):
            return body["content"]
        parts = body.get("parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], dict):
            return str(parts[0].get("text", ""))
    return ""


def recent_message_digest(messages: list[dict[str, Any]], limit: int = 50) -> str:
    """Return a fact-dense joined digest of the most recent ``limit`` turns."""
    rows: list[str] = []
    for m in messages[-limit:]:
        text = _msg_text(m)
        if text:
            rows.append(f"[{m.get('role', '?')}] {text}")
    return "\n".join(rows)


def session_observation_bodies(messages: list[dict[str, Any]], max_count: int = 20) -> list[str]:
    """Stable fact-dense observation bodies for on_session_end persistence.

    Users emit before assistants so partial async persistence still
    surfaces distinct facts instead of early u/a acknowledgement pairs.
    """
    out: list[str] = []
    digest = recent_message_digest(messages, limit=max_count * 2)
    if digest:
        out.append(f"Session summary:\n{digest[:6000]}")
    users: list[str] = []
    asst: list[str] = []
    for m in messages:
        text = _msg_text(m)
        role = m.get("role")
        if not text or role not in ("user", "assistant"):
            continue
        (users if role == "user" else asst).append(f"[{role}] {text[:400]}")
    for body in users + asst:
        if len(out) >= max_count:
            break
        out.append(body)
    return out


def join_extraction(cached: str, digest: str) -> str:
    """Compose the on_pre_compress extraction text from cached recall + digest."""
    parts: list[str] = []
    if cached:
        parts.append(f"Mastra observations before compression:\n{cached}")
    if digest:
        parts.append(f"Recent conversation:\n{digest}")
    return "\n\n".join(parts)


def is_recap_query(query: str) -> bool:
    """G08: detect recap-shaped queries that should fan out cross-thread."""
    return bool(query) and bool(_RECAP_RE.search(query))


def should_refresh_prefetch(p, cached: str) -> bool:
    """Refresh only on cache miss or near compression pressure."""
    breaker = getattr(getattr(p, "_client", None), "_breaker", None)
    if getattr(breaker, "state", "") == "OPEN":
        return False
    if not cached:
        return True
    cfg = getattr(p, "_cfg", {}) or {}
    context_len = int(cfg.get("context_length") or 0)
    threshold = float(cfg.get("compression_threshold") or 0.0)
    tokens = int(getattr(p, "_last_prompt_tokens", 0) or 0)
    if context_len <= 0 or threshold <= 0 or tokens <= 0:
        return False
    return tokens >= context_len * threshold * 0.9


def fetch_recap(client, query: str, profile: str, top_k: int = 8) -> str:
    """G08: cross-thread Mastra-first recap. Returns '' on miss/outage."""
    try:
        hits = client.semantic_search(query, profile, top_k)
    except Exception as exc:  # pragma: no cover - defensive boundary
        logger.debug("mastra: recap search failed: %s", exc)
        return ""
    if not hits:
        return ""
    return "\n".join(f"- {h.get('text', '')}" for h in hits if h.get("text"))


def merge_recap(text: str, recap: str) -> str:
    """G08 async path: append a previously-fetched recap to current cache text."""
    if not recap:
        return text
    return recap if not text else f"{text}\n\n{recap}"


def refresh_recap(p, query: str, top_k: int) -> None:
    """G08 async worker: populate p._last_recap from a cross-thread search."""
    if not is_recap_query(query):
        return
    client = getattr(p, "_client", None)
    if client is None:
        return
    profile = getattr(p, "_profile", "default")
    p._last_recap = fetch_recap(client, query, profile, top_k)
