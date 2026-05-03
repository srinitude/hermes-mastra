"""Hermes-artifact <-> Mastra prompt-blocks bridge.

This module manages SOUL.md / MEMORY.md / USER.md / per-project AGENTS.md
as **versioned Mastra prompt-blocks**.  The Hermes-side files become an
atomic on-disk *cache* of each block's active version, so:

  * Mastra is the source of truth (full version history, per-profile rows).
  * Files on disk are always readable — Hermes' system prompt assembly
    keeps working even when the Bun server is unreachable.
  * `on_memory_write` writes to the prompt-block (background) AND
    refreshes the file cache (atomic temp+rename).

See ``docs/HERMES_INTEGRATION_MAP.md`` §2.6 for the full contract.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


VALID_KINDS = ("soul", "memory", "user", "agents")


# ---------------------------------------------------------------------------
# Default file locations
# ---------------------------------------------------------------------------


def file_path_for(hermes_home: Path, kind: str, profile: str = "default") -> Path:
    """Where the file-cache copy of a Hermes artifact lives on disk."""
    home = Path(hermes_home)
    if profile and profile != "default":
        # Per-profile artifacts live under the profile's own directory.
        if kind == "soul":
            return home / "profiles" / profile / "SOUL.md"
        return home / "profiles" / profile / "memories" / f"{kind.upper()}.md"
    if kind == "soul":
        return home / "SOUL.md"
    return home / "memories" / f"{kind.upper()}.md"


# ---------------------------------------------------------------------------
# File-cache writer — atomic temp+rename, idempotent on identical content
# ---------------------------------------------------------------------------


def write_file_cache(target: Path, content: str) -> bool:
    """Atomically write *content* to *target*.  Returns True if changed.

    No-op when the file already contains the same bytes (preserves mtime).
    Uses a sibling temp file + ``os.replace`` so concurrent readers
    (Hermes' system-prompt assembly) never see a torn write.
    """
    target = Path(target)
    if target.exists() and target.read_text(encoding="utf-8") == content:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup if the rename failed.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return True


# ---------------------------------------------------------------------------
# Seed existing on-disk artifacts into prompt-blocks (one-time on activation)
# ---------------------------------------------------------------------------


def seed_artifacts_from_files(
    client: Any,
    hermes_home: Path,
    profile: str = "default",
) -> dict[str, bool]:
    """Read existing SOUL/MEMORY/USER.md and upsert each as a prompt-block.

    Returns ``{kind: True/False}`` indicating whether each kind was seeded.
    Idempotent — seeding the same content again is a server-side no-op.
    Skips ``agents`` (project-scoped, not seeded centrally).
    """
    out: dict[str, bool] = {}
    for kind in ("soul", "memory", "user"):
        out[kind] = _seed_one(client, hermes_home, profile, kind)
    return out


def _seed_one(client: Any, hermes_home: Path, profile: str, kind: str) -> bool:
    path = file_path_for(hermes_home, kind, profile)
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return False
    try:
        client.upsert_artifact(
            kind=kind,
            content=content,
            profile=profile,
            path=str(path),
            change_message="Seeded from existing file on plugin activation",
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("artifact seed failed for %s: %s", kind, exc)
        return False
    return True
