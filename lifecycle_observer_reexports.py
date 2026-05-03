"""Backward-compatible re-exports of tool observers.

Older callers imported these symbols from `provider_lifecycle`. Keep the
import path working without padding the lifecycle module's LOC budget.
"""

from __future__ import annotations

# fmt: off
try:
    from .tool_observers import (
        do_batch_end,
        do_batch_start,
        do_context_files_loaded,
        do_execute_code,
        do_goal_command,
        do_goal_event,
        do_kanban_event,
        do_memory_snapshot,
        do_personality_changed,
        do_skill_loaded,
        do_soul_loaded,
        do_todo_snapshot,
    )
except ImportError:
    from tool_observers import (  # type: ignore[no-redef]  # noqa: F401
        do_batch_end,
        do_batch_start,
        do_context_files_loaded,
        do_execute_code,
        do_goal_command,
        do_goal_event,
        do_kanban_event,
        do_memory_snapshot,
        do_personality_changed,
        do_skill_loaded,
        do_soul_loaded,
        do_todo_snapshot,
    )
# fmt: on
