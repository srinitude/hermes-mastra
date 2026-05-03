"""Implementation of every MemoryProvider hook as a free function.

Keeping hooks out of the class lets each fit the 30-LOC budget and lets
us share helpers via `lifecycle_helpers`.  The `MastraMemoryProvider`
class in `__init__.py` is a thin shell that dispatches to these.
"""

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
    from .server_manager import ensure_running, load_config
except ImportError:
    import async_runner_loader as _runner_loader  # type: ignore[no-redef]
    from client import client_from_env  # type: ignore[no-redef]
    from lifecycle_helpers import alive as _alive  # type: ignore[no-redef]
    from lifecycle_helpers import has_profile_kwarg as _has_profile_kwarg
    from lifecycle_helpers import resolve_profile as _resolve_profile
    from lifecycle_helpers import safe_call as _safe_call
    from server_manager import ensure_running, load_config  # type: ignore[no-redef]
# fmt: on

logger = logging.getLogger(__name__)


def _enqueue(fn) -> None:
    _runner_loader.submit(fn)


def _safe_enqueue(fn) -> None:
    """Enqueue a callable wrapped in safe_call so background errors are logged."""
    _runner_loader.submit(lambda: _safe_call(fn))


def _enqueue_recall(p) -> None:
    """Schedule a background recall to refresh the cache."""
    if not _alive(p):
        return
    client = p._client
    thread, profile = p._thread, p._profile
    top_k = int(p._cfg.get("recall_top_k", 4))
    p._recall_cache.refresh(lambda: client.recall(thread, profile, top_k))


# ----- initialize ----------------------------------------------------------


def do_initialize(p, session_id: str, **kwargs) -> None:
    agent_context = kwargs.get("agent_context") or "primary"
    platform = kwargs.get("platform") or "cli"
    if agent_context in ("cron", "flush") or platform == "cron":
        p._cron_skipped = True
        return
    p._cfg = load_config()
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
        p._recall_cache.clear()
    _enqueue_recall(p)
    text = p._recall_cache.get()
    return f"### Observational memory ({p._profile})\n{text}\n" if text else ""


def do_queue_prefetch(p, query: str, *, session_id: str = "") -> None:
    if not _alive(p):
        return
    if session_id and session_id != p._thread:
        p._thread = session_id
    _enqueue_recall(p)


def do_pre_compress(p, messages: list[dict[str, Any]]) -> str:
    """Persist cached observations as a synthetic Mastra observation
    (Hermes discards the return value), then enqueue flush + recall so
    the next prefetch sees post-compression state.
    """
    if not _alive(p):
        return ""
    client, thread, profile = p._client, p._thread, p._profile
    text = p._recall_cache.get()
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
    p._recall_cache.clear()
    if reset or not parent_session_id or not old_thread:
        _enqueue_recall(p)
        return
    client, new_thread, profile = p._client, p._thread, p._profile
    msg = f"Session continues from prior thread {old_thread} (lineage)."
    _safe_enqueue(lambda: client.write_observation(new_thread, profile, msg, kind="lineage"))
    _enqueue_recall(p)


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
    p._recall_cache.clear()
    p._profile = new_profile
    client, thread = p._client, p._thread
    msg = f"Profile switched from '{old_profile}' to '{new_profile}' (lineage)."
    _safe_enqueue(lambda: client.write_observation(thread, new_profile, msg, kind="profile_switch"))
    _enqueue_recall(p)


# ----- tool integration: see tool_observers.py + agent_observers.py.
# Re-exported via a sibling shim to keep this file under the LOC budget.

try:
    from .lifecycle_observer_reexports import *  # noqa: F403
except ImportError:
    from lifecycle_observer_reexports import *  # type: ignore[no-redef]  # noqa: F403
