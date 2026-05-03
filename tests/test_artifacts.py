"""Tests for the artifacts subsystem.

The plugin manages SOUL.md / MEMORY.md / USER.md / AGENTS.md as versioned
Mastra prompt-blocks (`@mastra/memory` storage domain).  Files on disk
become an atomic *cache* of the active version — system prompt always
works, even when the Bun server is unreachable (non-blocking contract).

Coverage:
  A. Seeding existing files into prompt-blocks on first activation
  B. Atomic file-cache writeback when an artifact is upserted
  C. Three new model-driven tools:
        mastra_artifact_get / mastra_artifact_history /
        mastra_artifact_revert
  D. Deadline budgets: artifact paths must NOT block a Hermes hook
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.get_artifact.return_value = {
        "kind": "soul",
        "profile": "default",
        "content": "You are Hermes.",
        "version": 3,
        "exists": True,
    }
    c.upsert_artifact.return_value = True

    def _v(n, t, m, txt):
        return {"version": n, "created_at": t, "change_message": m, "content": txt}

    c.list_artifact_versions.return_value = [
        _v(3, "2026-05-03T01:00:00Z", "edit", "v3"),
        _v(2, "2026-05-03T00:30:00Z", "edit", "v2"),
        _v(1, "2026-05-03T00:00:00Z", "Initial", "v1"),
    ]
    c.revert_artifact.return_value = True
    return c


@pytest.fixture
def provider(fake_hermes_home, fake_client):
    from tests.helpers import make_provider

    p = make_provider(fake_client)
    yield p
    p.shutdown()


# ---------------------------------------------------------------------------
# A. Seed existing files on first activation
# ---------------------------------------------------------------------------


def test_seed_uploads_existing_files_as_prompt_blocks(fake_hermes_home, fake_client):
    """When the plugin activates, existing SOUL/MEMORY/USER content seeds
    into Mastra prompt-blocks (one block per file).
    """
    home: Path = fake_hermes_home
    (home / "SOUL.md").write_text("You are Hermes.\n", encoding="utf-8")
    mem_dir = home / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "MEMORY.md").write_text("Project X\n§\nProject Y\n", encoding="utf-8")
    (mem_dir / "USER.md").write_text("User: Alice\n", encoding="utf-8")

    from artifacts import seed_artifacts_from_files

    seeded = seed_artifacts_from_files(
        client=fake_client,
        hermes_home=home,
        profile="default",
    )

    # All three files seeded
    assert seeded == {"soul": True, "memory": True, "user": True}
    # Each call passed the right kind + content
    calls = {
        c.kwargs.get("kind") or (c.args[0] if c.args else None): c.kwargs.get("content")
        or (c.args[1] if len(c.args) > 1 else None)
        for c in fake_client.upsert_artifact.call_args_list
    }
    assert "You are Hermes." in calls["soul"]
    assert "Project X" in calls["memory"]
    assert "User: Alice" in calls["user"]


def test_seed_is_idempotent_when_no_files_exist(fake_hermes_home, fake_client):
    """No file → no upsert. Plugin activation is safe on a fresh home."""
    from artifacts import seed_artifacts_from_files

    seeded = seed_artifacts_from_files(
        client=fake_client,
        hermes_home=fake_hermes_home,
        profile="default",
    )
    assert seeded == {"soul": False, "memory": False, "user": False}
    fake_client.upsert_artifact.assert_not_called()


# ---------------------------------------------------------------------------
# B. Atomic file-cache writeback
# ---------------------------------------------------------------------------


def test_writeback_atomic_temp_then_rename(fake_hermes_home, fake_client):
    """upsert_artifact + writeback writes via temp file + atomic rename.

    During the write, the original file must remain readable — Hermes'
    system prompt assembly happens on a separate thread and cannot
    tolerate a torn file.
    """
    from artifacts import write_file_cache

    target = fake_hermes_home / "SOUL.md"
    target.write_text("v1 content\n", encoding="utf-8")

    write_file_cache(target, "v2 content\n")
    assert target.read_text(encoding="utf-8") == "v2 content\n"
    # No leftover temp files
    leftovers = [p for p in fake_hermes_home.iterdir() if p.name.startswith(".SOUL.md.")]
    assert leftovers == []


def test_writeback_creates_parent_directory(fake_hermes_home, fake_client):
    """Profile dirs may not exist yet on first write — creating them is fine."""
    from artifacts import write_file_cache

    nested = fake_hermes_home / "profiles" / "fresh" / "MEMORY.md"
    write_file_cache(nested, "fresh content")
    assert nested.read_text(encoding="utf-8") == "fresh content"


def test_writeback_no_change_skips_write(fake_hermes_home):
    """Idempotent — writing identical content is a no-op (preserves mtime)."""
    from artifacts import write_file_cache

    target = fake_hermes_home / "SOUL.md"
    target.write_text("identical\n", encoding="utf-8")
    mtime_before = target.stat().st_mtime_ns
    time.sleep(0.01)
    write_file_cache(target, "identical\n")
    mtime_after = target.stat().st_mtime_ns
    assert mtime_before == mtime_after


# ---------------------------------------------------------------------------
# C. Three new model-driven tools
# ---------------------------------------------------------------------------


def test_artifact_get_tool_in_schemas(provider):
    names = {s["name"] for s in provider.get_tool_schemas()}
    assert "mastra_artifact_get" in names
    assert "mastra_artifact_history" in names
    assert "mastra_artifact_revert" in names


def test_artifact_get_tool_calls_client(provider, fake_client):
    raw = provider.handle_tool_call("mastra_artifact_get", {"kind": "soul"})
    payload = json.loads(raw)
    assert payload["kind"] == "soul"
    assert "Hermes" in payload["content"]
    fake_client.get_artifact.assert_called_once()


def test_artifact_history_tool_returns_versions(provider, fake_client):
    raw = provider.handle_tool_call("mastra_artifact_history", {"kind": "memory"})
    payload = json.loads(raw)
    assert payload["count"] == 3
    versions = [v["version"] for v in payload["versions"]]
    assert versions == [3, 2, 1]


def test_artifact_revert_tool_calls_client(provider, fake_client):
    raw = provider.handle_tool_call("mastra_artifact_revert", {"kind": "memory", "version": 1})
    payload = json.loads(raw)
    assert payload["ok"] is True
    fake_client.revert_artifact.assert_called_once()


def test_artifact_get_validates_kind(provider):
    raw = provider.handle_tool_call("mastra_artifact_get", {"kind": "bogus"})
    payload = json.loads(raw)
    assert "error" in payload


def test_artifact_revert_validates_version(provider):
    raw = provider.handle_tool_call(
        "mastra_artifact_revert",
        {"kind": "soul"},  # missing version
    )
    payload = json.loads(raw)
    assert "error" in payload


# ---------------------------------------------------------------------------
# D. Non-blocking — artifact paths obey the same deadline contract
# ---------------------------------------------------------------------------


def test_artifact_writeback_does_not_block_on_memory_write(provider, fake_client):
    """on_memory_write must remain inside its 50 ms budget even when the
    subsequent artifact upsert would block (server slow / down).

    The mirror enqueues onto async_runner — the hook itself returns fast.
    """

    # Simulate a slow upsert
    def slow_upsert(*args, **kwargs):
        time.sleep(2.0)
        return True

    fake_client.upsert_artifact.side_effect = slow_upsert
    t0 = time.perf_counter()
    provider.on_memory_write("add", "memory", "new fact")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 50, (
        f"on_memory_write took {elapsed_ms:.1f} ms with a slow artifact upsert "
        f"— it must enqueue, not block."
    )
