"""MemoryProvider hook implementations."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

# fmt: off
try:
    from . import async_runner_loader as _runner_loader
    from . import telemetry as _telemetry
    from .client import client_from_env
    from .lifecycle_helpers import alive as _alive
    from .lifecycle_helpers import is_recap_query as _is_recap
    from .lifecycle_helpers import join_extraction as _join_extraction
    from .lifecycle_helpers import merge_recap as _merge_recap
    from .lifecycle_helpers import recent_message_digest as _recent_digest
    from .lifecycle_helpers import refresh_recap as _refresh_recap
    from .lifecycle_helpers import resolve_profile as _resolve_profile
    from .lifecycle_helpers import safe_call as _safe_call
    from .lifecycle_helpers import session_observation_bodies as _session_bodies
    from .lifecycle_helpers import should_refresh_prefetch as _should_refresh_prefetch
    from .observation_dedup import ObservationDeduper
    from .server_manager import ensure_running, load_config
except ImportError:
    import async_runner_loader as _runner_loader  # type: ignore[no-redef]
    import telemetry as _telemetry  # type: ignore[no-redef]
    from client import client_from_env  # type: ignore[no-redef]
    from lifecycle_helpers import alive as _alive  # type: ignore[no-redef]
    from lifecycle_helpers import is_recap_query as _is_recap
    from lifecycle_helpers import join_extraction as _join_extraction
    from lifecycle_helpers import merge_recap as _merge_recap
    from lifecycle_helpers import recent_message_digest as _recent_digest
    from lifecycle_helpers import refresh_recap as _refresh_recap
    from lifecycle_helpers import resolve_profile as _resolve_profile
    from lifecycle_helpers import safe_call as _safe_call
    from lifecycle_helpers import session_observation_bodies as _session_bodies
    from lifecycle_helpers import should_refresh_prefetch as _should_refresh_prefetch
    from observation_dedup import ObservationDeduper  # type: ignore[no-redef]
    from server_manager import ensure_running, load_config  # type: ignore[no-redef]
# fmt: on

logger = logging.getLogger(__name__)


def _safe_enqueue(fn) -> None:
    _runner_loader.submit(lambda: _safe_call(fn))


def _breaker_open(p) -> bool:
    breaker = getattr(getattr(p, "_client", None), "_breaker", None)
    return getattr(breaker, "state", "") == "OPEN"


def _enqueue_recall(p) -> None:
    if not _alive(p):
        return
    client = p._client
    thread, profile = p._thread, p._profile
    top_k = int(p._cfg.get("recall_top_k", 4))
    p._recall_cache.refresh(lambda: client.recall(thread, profile, top_k), profile, thread)


# ----- initialize ----------------------------------------------------------


def do_initialize(p, session_id: str, **kwargs) -> None:
    agent_context = kwargs.get("agent_context") or "primary"
    platform = kwargs.get("platform") or "cli"
    if agent_context in ("cron", "flush") or platform == "cron":
        p._cron_skipped = True
        p._client = None
        return
    p._cfg = load_config()
    p._recall_cache.max_entries = int(
        p._cfg.get("recall_cache_lru_size", p._recall_cache.max_entries)
    )
    p._profile = _resolve_profile(kwargs)
    p._thread = session_id or "default-session"
    hermes_home = kwargs.get("hermes_home")
    if isinstance(hermes_home, str) and hermes_home:
        p._hermes_home = hermes_home
    _safe_enqueue(lambda: _bring_up_server(p))


def _bring_up_server(p) -> None:
    home_override = getattr(p, "_hermes_home", "")
    if home_override:
        os.environ["HERMES_HOME"] = home_override
        p._cfg = load_config()
    ok, msg = ensure_running()
    if not ok:
        logger.warning("mastra: server unavailable (%s) — provider will no-op", msg)
        return
    try:
        client = client_from_env(home_basename=Path(home_override).name if home_override else "")
        client.health()
        p._client = client
        _enqueue_recall(p)
    except Exception as exc:  # pragma: no cover
        logger.warning("mastra: bring-up failed: %s", exc)
        p._client = None


# ----- prefetch / queue_prefetch / pre_compress ----------------------------


def do_prefetch(p, query: str, *, session_id: str = "") -> str:
    if not _alive(p):
        return ""
    if session_id and session_id != p._thread:
        p._thread = session_id
        p._recall_cache.clear_profile(p._profile)
    p._last_user_message = query
    p._recall_cache.set_current(p._profile, p._thread)
    cached = p._recall_cache.get(p._profile, p._thread)
    if _breaker_open(p):
        return f"### Observational memory ({p._profile})\n{cached}\n" if cached else ""
    if _should_refresh_prefetch(p, cached):
        _enqueue_recall(p)
    if _is_recap(query):
        _safe_enqueue(lambda: _refresh_recap(p, query, int(p._cfg.get("recall_top_k", 8))))
    text = _merge_recap(cached, getattr(p, "_last_recap", "") or "")
    return f"### Observational memory ({p._profile})\n{text}\n" if text else ""


def do_queue_prefetch(p, query: str, *, session_id: str = "") -> None:
    if not _alive(p):
        return
    if session_id and session_id != p._thread:
        p._thread = session_id
    p._last_user_message = query
    p._recall_cache.set_current(p._profile, p._thread)
    _enqueue_recall(p)


def do_pre_compress(p, messages: list[dict[str, Any]]) -> str:
    if not _alive(p):
        return ""
    client, thread, profile = p._client, p._thread, p._profile
    cached = p._recall_cache.get(p._profile, p._thread)
    digest = _recent_digest(messages, limit=80)
    extraction = _join_extraction(cached, digest)
    if extraction:
        body = f"Pre-compression snapshot:\n{extraction[:6000]}"
        _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="pre_compress"))
    _safe_enqueue(lambda: client.flush(thread, profile))
    _enqueue_recall(p)
    return extraction


# ----- write-side hooks ----------------------------------------------------


def do_sync_turn(p, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
    if not _alive(p):
        return
    thread = session_id or p._thread
    client, profile = p._client, p._profile
    _safe_enqueue(
        lambda: client.save_turn(
            thread=thread, profile=profile, user=user_content, assistant=assistant_content
        )
    )


def do_session_end(p, messages: list[dict[str, Any]]) -> None:
    if not _alive(p):
        return
    client, thread, profile = p._client, p._thread, p._profile
    for b in _session_bodies(messages, max_count=20):
        _safe_enqueue(lambda b=b: client.write_observation(thread, profile, b, kind="session_end"))
    _safe_enqueue(lambda: client.flush(thread, profile))


def do_memory_write(
    p, action: str, target: str, content: str, metadata: dict[str, Any] | None = None
) -> None:
    """Mirror MEMORY.md / USER.md edits two ways.

    1. update_working_memory — Mastra's own working-memory log (one source
       of truth for the Observer to draw from).
    2. write_observation kind=memory_write — preserves the target
       distinction (MEMORY.md vs USER.md) which working-memory loses.
    """
    if not _alive(p):
        return
    client, thread, profile = p._client, p._thread, p._profile
    body = f"[{target}:{action}] {content}"
    _safe_enqueue(
        lambda: client.update_working_memory(
            profile=profile, content=body, thread=thread, action="append"
        )
    )
    obs = f"Built-in {target} {action}: {content}"
    dedup = getattr(p, "_dedup", None) or ObservationDeduper(int(p._cfg.get("dedup_lru_size", 512)))
    p._dedup = dedup
    if dedup.should_write(thread, profile, "memory_write", obs):
        _safe_enqueue(lambda: client.write_observation(thread, profile, obs, kind="memory_write"))


# ----- tool integration: see tool_observers.py + agent_observers.py.
# Re-exported via sibling shims to keep this file under the LOC budget.

for _f, _o in (
    (do_prefetch, "prefetch"),
    (do_sync_turn, "sync_turn"),
    (do_pre_compress, "pre_compress"),
    (do_memory_write, "memory_write"),
):
    globals()[_f.__name__] = _telemetry.timed(_o)(_f)

try:
    from . import lifecycle_session_hooks as _session_hooks
    from .lifecycle_observer_reexports import *  # noqa: F403
except ImportError:
    import lifecycle_session_hooks as _session_hooks  # type: ignore[no-redef]
    from lifecycle_observer_reexports import *  # type: ignore[no-redef]  # noqa: F403

do_delegation = _session_hooks.do_delegation
do_session_switch = _session_hooks.do_session_switch
do_turn_start = _session_hooks.do_turn_start
