"""Hermes feature-level observability hooks.
Captures signals from Hermes features (kanban, goals, SOUL.md, personality,
/goal, execute_code, batch_runner) as observations in the Mastra log.
Every function is non-blocking: enqueues a write and returns.
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


def do_kanban_event(
    p,
    *,
    action: str,
    card_id: str,
    title: str = "",
    from_status: str = "",
    to_status: str = "",
) -> None:
    """Snapshot a kanban card lifecycle event as an observation.

    Hermes' `kanban_tools.py` exposes the kanban surface; this handler
    captures `move`, `create`, `complete`, etc. so the observation log
    retains task history that survives `/compress` and session resets.
    Skipped when card_id is empty (e.g. `list` actions).
    """
    if not _alive(p):
        return
    if not (card_id and card_id.strip()):
        return
    client, thread, profile = p._client, p._thread, p._profile
    parts = [f"Kanban {action}: {card_id}"]
    if title:
        parts.append(f"({title})")
    if from_status and to_status:
        parts.append(f"{from_status} -> {to_status}")
    elif to_status:
        parts.append(f"-> {to_status}")
    text = " ".join(parts)
    _safe_enqueue(lambda: client.write_observation(thread, profile, text, kind="kanban_event"))


def do_goal_event(
    p,
    *,
    action: str,
    goal_id: str,
    text: str = "",
    completed_at: str = "",
) -> None:
    """Snapshot a Hermes goal lifecycle event.

    Persisting to the observation log gives goals cross-session
    visibility via `mastra_search`.
    """
    if not _alive(p):
        return
    if not (goal_id and goal_id.strip()):
        return
    client, thread, profile = p._client, p._thread, p._profile
    parts = [f"Goal {action}: {goal_id}"]
    if text:
        parts.append(f"-- {text[:300]}")
    if completed_at:
        parts.append(f"(completed_at={completed_at})")
    body = " ".join(parts)
    _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="goal_event"))


def do_context_files_loaded(p, files=None, entries=None) -> None:
    """Snapshot which context files (AGENTS.md / CLAUDE.md / SOUL.md /
    .cursorrules) were loaded into the system prompt.
      * ``files=[abs_path, ...]`` — flat list, legacy form
      * ``entries=[(abs_path, size_bytes, source_dir), ...]`` — richer form
        with size + dir attribution.

    Deduped per-session per-fileset/entryset; empty/missing input is a no-op.
    """
    if not _alive(p) or (not files and not entries):
        return
    fingerprint, body = _format_context_files(files, entries)
    seen = getattr(p, "_context_files_seen", set())
    if fingerprint in seen:
        return
    seen.add(fingerprint)
    p._context_files_seen = seen
    client, thread, profile = p._client, p._thread, p._profile
    _safe_enqueue(
        lambda: client.write_observation(thread, profile, body, kind="context_files_loaded")
    )


def _format_context_files(files, entries) -> tuple[str, str]:
    """Return (fingerprint, body) for either call form."""
    from pathlib import Path as _P

    if entries:
        fp = "entries:" + "|".join(sorted(f"{f[0]}@{f[1]}@{f[2]}" for f in entries))
        rows = [
            f"  - {_P(path).name} ({int(size)} bytes) from {src_dir}"
            for path, size, src_dir in entries
        ]
        return fp, "Context files loaded:\n" + "\n".join(rows)
    fp = "files:" + "|".join(sorted(files))
    short = sorted({_P(f).name if "/" in f else f for f in files})
    return fp, "Context files loaded: " + ", ".join(short)


def do_soul_loaded(p, soul_text) -> None:
    """Snapshot ~/.hermes/SOUL.md as kind=soul_loaded.

    Hermes injects SOUL.md into the system prompt at session start.
    We persist a digest (size + first 240 chars) so cross-session search
    can answer 'what was the soul/personality framing when X was said?'.
    Deduped by content hash — re-loading unchanged SOUL.md is a no-op,
    editing it produces a fresh observation.
    """
    if not _alive(p):
        return
    text = (soul_text or "").strip() if isinstance(soul_text, str) else ""
    if not text:
        return
    import hashlib

    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    seen: set = getattr(p, "_soul_hashes_seen", set())
    if h in seen:
        return
    seen.add(h)
    p._soul_hashes_seen = seen
    client, thread, profile = p._client, p._thread, p._profile
    body = f"SOUL.md loaded ({len(text)} chars, hash={h}):\n{text[:240]}"
    _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="soul_loaded"))


def do_personality_changed(p, *, old_personality: str, new_personality: str) -> None:
    """Snapshot a /personality slash-command transition."""
    if not _alive(p):
        return
    new = (new_personality or "").strip()
    old = (old_personality or "").strip()
    if not new or new == old:
        return
    client, thread, profile = p._client, p._thread, p._profile
    body = f"Personality changed: '{old or '(unset)'}' -> '{new}'"
    _safe_enqueue(
        lambda: client.write_observation(thread, profile, body, kind="personality_change")
    )


def do_goal_command(p, *, goal_text: str) -> None:
    """Snapshot a /goal slash-command. Deduped per-session per-text so
    repeat invocations of the same goal don't bloat the observation log."""
    if not _alive(p):
        return
    text = (goal_text or "").strip() if isinstance(goal_text, str) else ""
    if not text:
        return
    seen: set = getattr(p, "_goals_seen", set())
    if text in seen:
        return
    seen.add(text)
    p._goals_seen = seen
    client, thread, profile = p._client, p._thread, p._profile
    body = f"Goal set: {text[:600]}"
    _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="goal_set"))


def do_execute_code(p, *, code: str, exit_code: int, output_excerpt: str = "") -> None:
    """Snapshot an execute_code invocation.

    Captures: first 240 chars of code, exit code, first 1200 chars of
    output. Truncates aggressively so this never bloats the observation
    log even on huge stdout dumps.
    """
    if not _alive(p):
        return
    code_str = (code or "")[:240] if isinstance(code, str) else ""
    out_str = (output_excerpt or "")[:1200] if isinstance(output_excerpt, str) else ""
    if not code_str:
        return
    client, thread, profile = p._client, p._thread, p._profile
    body = (
        f"execute_code exit={int(exit_code)}\n"
        f"--- code ---\n{code_str}\n"
        f"--- output (first 1200 chars) ---\n{out_str}"
    )
    _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="execute_code"))


def do_batch_start(p, *, run_id: str, total: int, parallel: int, prompt_summary: str = "") -> None:
    """Snapshot the start of a Hermes batch_runner run."""
    if not _alive(p):
        return
    rid = (run_id or "").strip()
    if not rid:
        return
    client, thread, profile = p._client, p._thread, p._profile
    body = f"Batch start: {rid} (total={int(total)}, parallel={int(parallel)})" + (
        f" — {prompt_summary[:200]}" if prompt_summary else ""
    )
    _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="batch_start"))


def do_batch_end(p, *, run_id: str, succeeded: int, failed: int, total_seconds: float) -> None:
    """Snapshot batch_runner completion stats."""
    if not _alive(p):
        return
    rid = (run_id or "").strip()
    if not rid:
        return
    client, thread, profile = p._client, p._thread, p._profile
    body = (
        f"Batch end: {rid} succeeded={int(succeeded)} failed={int(failed)} "
        f"total_seconds={float(total_seconds):.1f}"
    )
    _safe_enqueue(lambda: client.write_observation(thread, profile, body, kind="batch_end"))
