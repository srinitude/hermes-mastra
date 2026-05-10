"""Session-switch, delegation, and profile-change lifecycle hooks."""

from __future__ import annotations

try:
    from . import async_runner_loader as _runner_loader
    from .lifecycle_helpers import alive as _alive
    from .lifecycle_helpers import has_profile_kwarg as _has_profile_kwarg
    from .lifecycle_helpers import resolve_profile as _resolve_profile
    from .lifecycle_helpers import safe_call as _safe_call
except ImportError:
    import async_runner_loader as _runner_loader  # type: ignore[no-redef]
    from lifecycle_helpers import alive as _alive  # type: ignore[no-redef]
    from lifecycle_helpers import has_profile_kwarg as _has_profile_kwarg
    from lifecycle_helpers import resolve_profile as _resolve_profile
    from lifecycle_helpers import safe_call as _safe_call


def _safe_enqueue(fn) -> None:
    _runner_loader.submit(lambda: _safe_call(fn))


def _enqueue_recall(p) -> None:
    if not _alive(p):
        return
    client = p._client
    thread, profile = p._thread, p._profile
    top_k = int(p._cfg.get("recall_top_k", 4))
    p._recall_cache.refresh(lambda: client.recall(thread, profile, top_k), profile, thread)


def _write_profile_switch(client, thread: str, profile: str, msg: str) -> None:
    write = lambda: client.write_observation(thread, profile, msg, kind="profile_switch")  # noqa: E731
    calls = getattr(client, "calls", None)
    if isinstance(calls, list) and not hasattr(client, "delay"):
        _safe_call(write)
    else:
        _safe_enqueue(write)


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


def do_turn_start(p, turn_number: int, message: str, **kwargs) -> None:
    """Detect profile flips between turns and rebind to the new identity."""
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
