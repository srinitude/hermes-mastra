"""Tiny indirection so `recall_cache.RecallCache` can be tested without
having both relative + absolute import branches.

Both Hermes (package) and pytest (standalone) import this module the
same way, and it forwards to ``async_runner.submit``.
"""

from __future__ import annotations

try:
    from . import async_runner as _ar
except ImportError:
    import async_runner as _ar  # type: ignore[no-redef]


def submit(fn) -> bool:
    return _ar.submit(fn)
