#!/usr/bin/env python3
"""Verify our TS server uses Mastra Memory APIs that still exist upstream.

We grep for the exact method names our `server/src/` modules call in the
live ``mastra-ai/mastra`` source tree fetched via ``opensrc``. If any
disappear or change shape, the plugin would break at runtime — fail
loudly here so CI catches it.

Run via:  mise run compat:mastra
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REQUIRED_METHODS = (
    # Method name : minimum number of source matches we expect to find
    ("createThread", 1),
    ("getThreadById", 1),
    ("saveMessages", 1),
    ("recall", 1),
    ("listThreads", 1),
    ("deleteThread", 1),
    ("updateWorkingMemory", 1),
    ("observationalMemory", 1),
)


def fetch_mastra_root() -> Path:
    out = subprocess.check_output(["opensrc", "path", "mastra-ai/mastra"], text=True).strip()
    return Path(out) / "packages" / "memory" / "src"


def count_matches(root: Path, name: str) -> int:
    pat = re.compile(rf"\b{re.escape(name)}\b")
    n = 0
    for p in root.rglob("*.ts"):
        try:
            n += sum(1 for _ in pat.finditer(p.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return n


def main() -> int:
    root = fetch_mastra_root()
    if not root.exists():
        print(f"✖ Mastra memory package not at {root}", file=sys.stderr)
        return 2
    missing: list[str] = []
    for name, minimum in REQUIRED_METHODS:
        n = count_matches(root, name)
        if n < minimum:
            missing.append(f"  - {name}: found {n} matches (expected ≥{minimum})")
    if missing:
        print("✖ Mastra Memory API drift detected:", file=sys.stderr)
        print("\n".join(missing), file=sys.stderr)
        print("Investigate upstream changes before shipping.", file=sys.stderr)
        return 1
    print(f"✓ all {len(REQUIRED_METHODS)} Mastra Memory APIs present in {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
