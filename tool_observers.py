"""Tool/skill observability hooks — extracted from `provider_lifecycle` to
keep that module under the 200-LOC budget.

Each function here is invoked when a Hermes tool or skill emits a signal
worth persisting as a Mastra observation:

  * `do_todo_snapshot` — agent's `todo` tool list updated
  * `do_skill_loaded` — `/skill-name` slash command or `skill_view()` call
"""

from __future__ import annotations

import logging

try:
    from . import async_runner_loader as _runner_loader
    from .lifecycle_helpers import alive as _alive
    from .lifecycle_helpers import safe_call as _safe_call
except ImportError:
    import async_runner_loader as _runner_loader  # type: ignore[no-redef]
    from lifecycle_helpers import alive as _alive  # type: ignore[no-redef]
    from lifecycle_helpers import safe_call as _safe_call

logger = logging.getLogger(__name__)


def _safe_enqueue(fn) -> None:
    _runner_loader.submit(lambda: _safe_call(fn))


def do_todo_snapshot(p, todos: list | None) -> None:
    """Snapshot the agent's `todo` tool state as an observation.

    Cross-session task continuity then survives via Mastra recall on
    the next turn. Skipped when the list is empty so we don't spam.
    """
    if not _alive(p) or not todos:
        return
    client, thread, profile = p._client, p._thread, p._profile
    lines = [f"- [{t.get('status', '?')}] {t.get('content', '')}" for t in todos]
    body = "Todo snapshot:\n" + "\n".join(lines)
    _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="todo_snapshot"))


def do_skill_loaded(p, skill_name: str, reason: str = "") -> None:
    """Persist a `kind=skill_loaded` observation when a skill enters context.

    Deduped per-session per-skill so loading `/plan` ten times in one
    conversation only writes once.
    """
    if not _alive(p):
        return
    skill_name = (skill_name or "").strip()
    if not skill_name:
        return
    seen: set[str] = getattr(p, "_skills_seen", set())
    if skill_name in seen:
        return
    seen.add(skill_name)
    p._skills_seen = seen
    client, thread, profile = p._client, p._thread, p._profile
    text = f"Skill loaded: {skill_name}" + (f" ({reason})" if reason else "")
    _safe_enqueue(lambda: client.write_observation(thread, profile, text, kind="skill_loaded"))


def do_memory_snapshot(p, memory_text: str = "", user_text: str = "") -> None:
    """Snapshot the current MEMORY.md / USER.md contents into Mastra.

    Hermes injects MEMORY.md + USER.md as a frozen snapshot at session
    start (max 2,200 + 1,375 chars). Mirroring those into the observation
    log lets future sessions recall the prior state via mastra_search.
    Each non-empty target gets its own `kind=memory_snapshot` observation
    so the source distinction (MEMORY.md vs USER.md) is preserved.
    """
    if not _alive(p):
        return
    client, thread, profile = p._client, p._thread, p._profile
    if memory_text and memory_text.strip():
        _emit_snapshot(client, thread, profile, "MEMORY.md", memory_text.strip())
    if user_text and user_text.strip():
        _emit_snapshot(client, thread, profile, "USER.md", user_text.strip())


def _emit_snapshot(client, thread: str, profile: str, label: str, text: str) -> None:
    """Capture *label*+*text* into the closure scope before enqueueing."""
    body = f"{label} snapshot:\n{text}"
    _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="memory_snapshot"))


# Hermes feature-level hooks moved to agent_observers.py to keep this
# file under the 200-LOC budget. Re-export here for back-compat.
try:
    from .agent_observers import (
        do_batch_end,
        do_batch_start,
        do_context_files_loaded,
        do_execute_code,
        do_goal_command,
        do_goal_event,
        do_kanban_event,
        do_personality_changed,
        do_soul_loaded,
    )
except ImportError:
    from agent_observers import (  # type: ignore[no-redef]  # noqa: F401
        do_batch_end,
        do_batch_start,
        do_context_files_loaded,
        do_execute_code,
        do_goal_command,
        do_goal_event,
        do_kanban_event,
        do_personality_changed,
        do_soul_loaded,
    )
