"""Wire mastra observers into Hermes' actual call sites.

`activate_for(provider)` returns a dict of callables that callers
(typically `register(ctx)` or the plugin's `initialize` path) hand to
Hermes' plugin hook system via `ctx.register_hook(name, fn)`:

  - `pre_tool_call`         (currently unused — placeholder for future hooks)
  - `post_tool_call`        (routes by tool_name → matching observer)
  - `on_session_reset`      (clears recall cache, lineage observation)
  - `on_session_finalize`   (drains pending background work)

Plus a `revert` callable that undoes any monkey-patches we installed for
surfaces with no native hook (currently none — kept as the seam for
future SOUL.md / personality / goals / batch_runner patching).

Idempotent: calling `activate_for` twice on the same provider returns
the same callbacks and doesn't double-wire patches.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

try:
    from . import provider_lifecycle as L
except ImportError:
    import provider_lifecycle as L  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# Track which providers we've already wired so a re-run is a no-op.
_WIRED: set[int] = set()


# --- post_tool_call dispatch table --------------------------------------
# Keyed by Hermes tool name. Each handler takes (provider, args, result_str).


def _h_skill_view(p, args: dict, _result: str) -> None:
    L.do_skill_loaded(p, skill_name=str(args.get("name") or "").strip(), reason="skill_view tool")


def _h_execute_code(p, args: dict, result: str) -> None:
    parsed = _try_json(result) or {}
    L.do_execute_code(
        p,
        code=str(args.get("code") or ""),
        exit_code=int(parsed.get("exit_code") or parsed.get("returncode") or 0),
        output_excerpt=str(parsed.get("output") or parsed.get("stdout") or "")[:1200],
    )


def _h_todo(p, _args: dict, result: str) -> None:
    parsed = _try_json(result) or {}
    todos = parsed.get("todos")
    if isinstance(todos, list):
        L.do_todo_snapshot(p, todos)


def _h_kanban(p, args: dict, _result: str) -> None:
    L.do_kanban_event(
        p,
        action=str(args.get("action") or "unknown"),
        card_id=str(args.get("card_id") or args.get("id") or "").strip(),
        title=str(args.get("title") or args.get("content") or ""),
        from_status=str(args.get("from_status") or ""),
        to_status=str(args.get("to_status") or args.get("status") or ""),
    )


def _h_goals(p, args: dict, _result: str) -> None:
    """Hermes' goals tool — covers `/goal create`, complete, etc."""
    text = str(args.get("text") or args.get("goal") or "").strip()
    action = str(args.get("action") or "set").lower()
    if action in ("create", "set", "add") and text:
        L.do_goal_command(p, goal_text=text)
    else:
        L.do_goal_event(
            p,
            action=action,
            goal_id=str(args.get("goal_id") or args.get("id") or ""),
            text=text,
        )


# Map: tool_name → handler. Anything not listed is silently ignored.
_POST_TOOL_HANDLERS: dict[str, Callable] = {
    "skill_view": _h_skill_view,
    "execute_code": _h_execute_code,
    "todo": _h_todo,
    "kanban": _h_kanban,
    "goals": _h_goals,
}


def _try_json(blob: Any) -> Any:
    if not isinstance(blob, str):
        return blob
    try:
        return json.loads(blob)
    except (TypeError, ValueError):
        return None


# --- public API ---------------------------------------------------------


def activate_for(provider) -> dict[str, Any]:
    """Wire the provider into Hermes' plugin-hook dispatch points.

    Returns a dict ``{hook_name: callback, ..., "revert": callable}``
    suitable for either ``ctx.register_hook(name, cb)`` or direct test
    invocation. Idempotent.
    """
    pid = id(provider)
    if pid in _WIRED:
        return _build_callbacks(provider)
    _WIRED.add(pid)
    return _build_callbacks(provider)


def _build_callbacks(provider) -> dict[str, Any]:
    return {
        "pre_tool_call": _make_pre_tool_call(provider),
        "post_tool_call": _make_post_tool_call(provider),
        "on_session_reset": _make_on_session_reset(provider),
        "on_session_finalize": _make_on_session_finalize(provider),
        "revert": lambda: _WIRED.discard(id(provider)),
    }


def _make_pre_tool_call(provider) -> Callable:
    """Reserved for future use (e.g. observe per-tool budget)."""

    def _cb(**kwargs):
        return None

    return _cb


def _make_post_tool_call(provider) -> Callable:
    def _cb(*, tool_name: str = "", args: Any = None, result: Any = None, **_kw) -> None:
        if not tool_name:
            return
        handler = _POST_TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return
        try:
            handler(provider, args or {}, result if isinstance(result, str) else "")
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("mastra: post_tool_call handler for %s raised: %s", tool_name, exc)

    return _cb


def _make_on_session_reset(provider) -> Callable:
    def _cb(*, session_id: str = "", platform: str = "", **_kw) -> None:
        try:
            provider.on_session_switch(session_id or provider._thread, reset=True)
        except Exception as exc:  # pragma: no cover
            logger.debug("mastra: on_session_reset raised: %s", exc)

    return _cb


def _make_on_session_finalize(provider) -> Callable:
    def _cb(*, session_id: str = "", **_kw) -> None:
        try:
            provider.on_session_end([])
        except Exception as exc:  # pragma: no cover
            logger.debug("mastra: on_session_finalize raised: %s", exc)

    return _cb
