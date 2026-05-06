"""MemoryProvider hook implementations."""

from __future__ import annotations

import logging
import os
from typing import Any

# fmt: off
try:
    from . import async_runner_loader as _runner_loader
    from .client import client_from_env
    from .lifecycle_helpers import alive as _alive
    from .lifecycle_helpers import has_profile_kwarg as _has_profile_kwarg
    from .lifecycle_helpers import resolve_profile as _resolve_profile
    from .lifecycle_helpers import safe_call as _safe_call
    from .observation_dedup import ObservationDeduper
    from .server_manager import ensure_running, load_config
except ImportError:
    import async_runner_loader as _runner_loader  # type: ignore[no-redef]
    from client import client_from_env  # type: ignore[no-redef]
    from lifecycle_helpers import alive as _alive  # type: ignore[no-redef]
    from lifecycle_helpers import has_profile_kwarg as _has_profile_kwarg
    from lifecycle_helpers import resolve_profile as _resolve_profile
    from lifecycle_helpers import safe_call as _safe_call
    from observation_dedup import ObservationDeduper  # type: ignore[no-redef]
    from server_manager import ensure_running, load_config  # type: ignore[no-redef]
# fmt: on

logger = logging.getLogger(__name__)


def _enqueue(fn) -> None:
    _runner_loader.submit(lambda: _safe_call(fn))


def _safe_enqueue(fn) -> None:
    _runner_loader.submit(lambda: _safe_call(fn))


def _write_profile_switch(client, thread: str, profile: str, msg: str) -> None:
    def _write() -> bool:
        return client.write_observation(thread, profile, msg, kind="profile_switch")

    calls = getattr(client, "calls", None)
    if isinstance(calls, list) and not hasattr(client, "delay"):
        _safe_call(_write)
        return
    _safe_enqueue(_write)


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
    _enqueue(lambda: _bring_up_server(p))


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
        client = client_from_env()
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
    _enqueue_recall(p)
    text = p._recall_cache.get(p._profile, p._thread)
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
    text = p._recall_cache.get(p._profile, p._thread)
    if text:
        snapshot = text[:4000]
        msg = f"Pre-compression snapshot:\n{snapshot}"
        _safe_enqueue(lambda: client.write_observation(thread, profile, msg, kind="pre_compress"))
    _safe_enqueue(lambda: client.flush(thread, profile))
    _enqueue_recall(p)
    return f"Mastra observations before compression:\n{text}" if text else ""


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
    _enqueue_recall(p)


def do_session_end(p, messages: list[dict[str, Any]]) -> None:
    if not _alive(p):
        return
    client, thread, profile = p._client, p._thread, p._profile
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


def do_delegation(p, task: str, result: str, *, child_session_id: str = "", **kwargs) -> None:
    if not _alive(p):
        return
    client, thread, profile = p._client, p._thread, p._profile
    obs = (
        f"Delegated task: {task[:300]}\n"
        f"Subagent ({child_session_id or 'unknown'}) returned: {result[:600]}"
    )
    _safe_enqueue(lambda: client.write_observation(thread, profile, obs, kind="delegation"))


def do_session_switch(
    p, new_session_id: str, *, parent_session_id: str = "", reset: bool = False, **kwargs
) -> None:
    if not _alive(p):
        return
    old_thread = p._thread
    p._thread = new_session_id or p._thread
    p._recall_cache.clear_profile(p._profile)
    if reset or not parent_session_id:
        _enqueue_recall(p)
        return
    client, new_thread, profile = p._client, p._thread, p._profile
    msg = f"Session continues from prior thread {parent_session_id} (lineage)."
    _safe_enqueue(lambda: client.write_observation(new_thread, profile, msg, kind="lineage"))
    top_k = int(p._cfg.get("recall_top_k", 4))
    _safe_enqueue(
        lambda: p._recall_cache.store(
            profile,
            new_thread,
            client.recall(parent_session_id or old_thread, profile, top_k),
        )
    )


# ----- on_turn_start: synthetic profile-switch detection -------------------


def do_turn_start(p, turn_number: int, message: str, **kwargs) -> None:
    """Detect profile flips between turns and rebind to the new identity.

    Hermes has no upstream profile-switch hook; we reuse on_turn_start.
    """
    if not _alive(p):
        return
    new_profile = _resolve_profile(kwargs)
    if new_profile == "default" and not _has_profile_kwarg(kwargs):
        return
    old_profile = p._profile
    if new_profile == old_profile:
        return
    p._recall_cache.clear_profile(old_profile)
    p._profile = new_profile
    client, thread = p._client, p._thread
    msg = f"Profile switched from '{old_profile}' to '{new_profile}' (lineage)."
    _write_profile_switch(client, thread, new_profile, msg)
    _enqueue_recall(p)


# ----- tool integration: see tool_observers.py + agent_observers.py.
# Re-exported via a sibling shim to keep this file under the LOC budget.

try:
    from .lifecycle_observer_reexports import *  # noqa: F403
except ImportError:
    from lifecycle_observer_reexports import *  # type: ignore[no-redef]  # noqa: F403
