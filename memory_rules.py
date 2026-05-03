"""Canonical Mastra rules installed into MEMORY.md and USER.md.

The point of this module: the moment a user activates the plugin, both
built-in memory files get exactly ONE entry that tells the agent:

  1. What to off-load to mastra (almost everything).
  2. What stays in the small built-in stores (a tiny core).
  3. Which tool to use when (`mastra_observe` to write,
     `mastra_recall` for current thread, `mastra_search` for
     keyword search).

Net effect: MEMORY.md / USER.md stay small forever because the routing
rule itself prevents them from growing.

Both rules are anchored with the literal `[mastra-rule]` token so the
plugin can find them later for idempotent re-install or clean uninstall.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Canonical rule text — kept tiny on purpose.
# ---------------------------------------------------------------------------

# 397 chars; fits 18% of MEMORY.md's 2200-char cap, leaving room for ~10
# user-curated entries.
MEMORY_MD_RULE = (
    "[mastra-rule] mastra plugin is active — keep MEMORY.md SMALL. "
    "Store here ONLY: stable environment facts (OS, installed runtimes, "
    "shells), durable project conventions (paths, commands, lockfiles), "
    "and corrections that must be in the system prompt. "
    "Everything else — task progress, decisions, lessons learned, larger "
    "facts — goes to mastra via `mastra_observe`. "
    "Recall current thread: `mastra_recall`. "
    "Keyword search across all sessions: `mastra_search`. "
    "Raw transcripts: `session_search`."
)

# 246 chars; fits 18% of USER.md's 1375-char cap.
USER_MD_RULE = (
    "[mastra-rule] mastra plugin is active — keep USER.md SMALL. "
    "Store here ONLY: name, contact, timezone, communication preferences, "
    "always-true habits. Everything else (corrections, evolving "
    "preferences, project-scoped style notes) → `mastra_observe`."
)

ANCHOR = "[mastra-rule]"
# Hermes' built-in memory format: entries in MEMORY.md / USER.md are
# delimited by a single line containing only the section sign U+00A7
# ("§").  The character is rare in regular prose so it never collides
# with entry text, single-line so it's easy to grep and split, and
# semantically apt — `§` literally means "section" in legal typography.
# Picking any other delimiter (---, ===, blank lines) would break the
# `memory` tool's substring-based replace/remove operations, which need
# to address entries individually.
SECTION_SEPARATOR = "\n§\n"


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def _memories_dir() -> Path:
    from hermes_constants import get_hermes_home  # type: ignore[import]

    home = Path(get_hermes_home())
    out = home / "memories"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _path(name: str) -> Path:
    return _memories_dir() / name


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _write(p: Path, text: str) -> None:
    p.write_text(text.rstrip() + "\n", encoding="utf-8")


def _has_anchor(text: str) -> bool:
    return ANCHOR in text


def _strip_anchor_entry(text: str) -> str:
    """Remove every entry that contains the anchor, leaving everything else.

    Entries are split on ``SECTION_SEPARATOR`` (``\\n§\\n``) — Hermes'
    canonical entry delimiter for ``MEMORY.md`` / ``USER.md``.  See
    SKILL.md → "MEMORY.md / USER.md format" for the rationale.
    """
    if not text:
        return ""
    parts = text.split(SECTION_SEPARATOR)
    kept = [p for p in parts if ANCHOR not in p]
    out = SECTION_SEPARATOR.join(kept).strip()
    return out


def _append_anchor_entry(text: str, rule: str) -> str:
    """Append the rule as a new entry; idempotent — no-op if already present."""
    if _has_anchor(text):
        return text
    if not text.strip():
        return rule
    return text.rstrip() + SECTION_SEPARATOR + rule


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install_memory_rules() -> dict[str, bool]:
    """Append the canonical rule to MEMORY.md and USER.md if not already present.

    Returns a dict telling the caller whether each file was modified.
    Idempotent — safe to run on every plugin startup.
    """
    return {
        "MEMORY.md": _install_one("MEMORY.md", MEMORY_MD_RULE),
        "USER.md": _install_one("USER.md", USER_MD_RULE),
    }


def _install_one(filename: str, rule: str) -> bool:
    p = _path(filename)
    before = _read(p)
    after = _append_anchor_entry(before, rule)
    if after == before:
        return False
    _write(p, after)
    return True


def uninstall_memory_rules() -> dict[str, bool]:
    """Strip the canonical rule from both files, preserving everything else."""
    return {
        "MEMORY.md": _uninstall_one("MEMORY.md"),
        "USER.md": _uninstall_one("USER.md"),
    }


def _uninstall_one(filename: str) -> bool:
    p = _path(filename)
    before = _read(p)
    if not _has_anchor(before):
        return False
    after = _strip_anchor_entry(before)
    _write(p, after)
    return True
