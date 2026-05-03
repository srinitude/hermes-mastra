"""Upstream compatibility tests — run as part of the regular pytest suite.

These tests guarantee the plugin's contract with the two repos it depends
on (`NousResearch/hermes-agent`, `mastra-ai/mastra`) hasn't drifted. They
shell out to ``opensrc`` to fetch / cache the source tarballs, then grep
for the symbols the plugin uses.

If ``opensrc`` is unavailable in the test environment (e.g. minimal CI
image), the tests skip with a clear reason so they never fail spuriously.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

OPENSRC = shutil.which("opensrc")
pytestmark = pytest.mark.skipif(
    OPENSRC is None,
    reason="opensrc CLI not installed — install from https://opensrc.dev to enable",
)


def _opensrc_path(spec: str) -> Path:
    try:
        out = subprocess.check_output(
            [OPENSRC, "path", spec], text=True, stderr=subprocess.PIPE
        ).strip()
    except subprocess.CalledProcessError as exc:
        # Common cases: GitHub rate limit, no network, repo gone. Skip
        # rather than fail — these tests are advisory, not gating.
        pytest.skip(f"opensrc could not fetch {spec}: {exc.stderr.strip() or exc}")
    return Path(out)


# ---- Hermes side ----------------------------------------------------------

REQUIRED_HERMES_HOOKS = (
    "is_available",
    "initialize",
    "system_prompt_block",
    "prefetch",
    "queue_prefetch",
    "sync_turn",
    "get_tool_schemas",
    "handle_tool_call",
    "shutdown",
    "on_session_end",
    "on_session_switch",
    "on_pre_compress",
    "on_delegation",
    "get_config_schema",
    "save_config",
    "on_memory_write",
)


@pytest.mark.parametrize("hook", REQUIRED_HERMES_HOOKS)
def test_hermes_memory_provider_hook_exists(hook: str) -> None:
    root = _opensrc_path("NousResearch/hermes-agent")
    abc = root / "agent" / "memory_provider.py"
    assert abc.exists(), f"MemoryProvider ABC not at {abc}"
    src = abc.read_text(encoding="utf-8")
    assert f"def {hook}(" in src, (
        f"hook '{hook}' missing in upstream MemoryProvider ABC at {abc}. "
        "Either drop it from the plugin or update REQUIRED_HERMES_HOOKS."
    )


# ---- Mastra side ----------------------------------------------------------

REQUIRED_MASTRA_SYMBOLS = (
    "createThread",
    "getThreadById",
    "saveMessages",
    "recall",
    "listThreads",
    "deleteThread",
    "updateWorkingMemory",
    "observationalMemory",
)


@pytest.mark.parametrize("symbol", REQUIRED_MASTRA_SYMBOLS)
def test_mastra_memory_symbol_exists(symbol: str) -> None:
    root = _opensrc_path("mastra-ai/mastra") / "packages" / "memory" / "src"
    assert root.exists(), f"Mastra memory package not at {root}"
    seen = False
    for p in root.rglob("*.ts"):
        try:
            if symbol in p.read_text(encoding="utf-8", errors="ignore"):
                seen = True
                break
        except OSError:
            continue
    assert seen, (
        f"Mastra symbol '{symbol}' not found anywhere under {root}. "
        "The plugin's TS server uses this — update or refactor."
    )
