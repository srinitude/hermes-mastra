#!/usr/bin/env python3
"""Verify our MemoryProvider implementation matches Hermes upstream.

For every hook the plugin overrides, confirm it's still defined on
``MemoryProvider`` in the live ``NousResearch/hermes-agent`` source tree
fetched via ``opensrc``. Fails fast with a remediation message if a hook
disappeared upstream — that means our plugin would silently break.

Run via:  mise run compat:hermes
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REQUIRED_HOOKS = (
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


def fetch_hermes_root() -> Path:
    out = subprocess.check_output(
        ["opensrc", "path", "NousResearch/hermes-agent"], text=True
    ).strip()
    return Path(out)


def hooks_in_provider(src: str) -> set[str]:
    return set(re.findall(r"^\s+def\s+(\w+)\s*\(", src, re.MULTILINE))


def main() -> int:
    root = fetch_hermes_root()
    abc = root / "agent" / "memory_provider.py"
    if not abc.exists():
        print(f"✖ MemoryProvider ABC not found at {abc}", file=sys.stderr)
        return 2
    upstream_hooks = hooks_in_provider(abc.read_text(encoding="utf-8"))
    missing = sorted(set(REQUIRED_HOOKS) - upstream_hooks)
    if missing:
        print("✖ The following hooks are missing in upstream MemoryProvider:", file=sys.stderr)
        for h in missing:
            print(f"    - {h}", file=sys.stderr)
        print("Update REQUIRED_HOOKS or refactor the plugin.", file=sys.stderr)
        return 1
    print(f"✓ all {len(REQUIRED_HOOKS)} required hooks present in upstream MemoryProvider ({abc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
