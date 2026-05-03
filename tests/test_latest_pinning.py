"""Policy: every Mastra/AI-SDK dep in server/package.json is pinned to "latest".

This plugin tracks upstream Mastra at HEAD on purpose — fixed semver caret
ranges silently rot the integration. The companion `mise run compat:mastra`
+ the upstream-compat tests are the safety net for this aggressive pin.

If you genuinely need a temporary pin (e.g. blocking on an upstream regression)
add the package to `ALLOWED_PIN_OVERRIDES` with a code-comment explaining why
and a tracking-issue link.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG_JSON = ROOT / "server" / "package.json"

# Packages that MUST be "latest" — these are the upstream contracts the
# plugin tracks at HEAD.
LATEST_REQUIRED = {
    "@mastra/core",
    "@mastra/libsql",
    "@mastra/memory",
    "@ai-sdk/openai-compatible",
    # Hono + zod are immediate transitive surfaces; bumping them with
    # Mastra avoids type drift across versions.
    "hono",
    "zod",
}

# Dev tooling can be pinned — but defaulting to latest keeps Biome / Bun
# types / TS in lockstep with whatever Bun ships.
LATEST_RECOMMENDED_DEV = {"@biomejs/biome", "@types/bun", "typescript"}

# If a package ever needs a temporary pin, add it here with a comment in
# package.json explaining why. Keep this set empty by default.
ALLOWED_PIN_OVERRIDES: set[str] = set()


def _pkg_json() -> dict:
    return json.loads(PKG_JSON.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(LATEST_REQUIRED))
def test_runtime_dep_is_latest(name: str) -> None:
    deps = _pkg_json().get("dependencies", {})
    assert name in deps, f"{name} missing from server/package.json dependencies"
    if name in ALLOWED_PIN_OVERRIDES:
        return
    assert deps[name] == "latest", (
        f"{name} is pinned to '{deps[name]}' — but this plugin tracks Mastra "
        "at HEAD. Either set it back to 'latest' or, if you have a real reason "
        "to pin, add it to ALLOWED_PIN_OVERRIDES with a tracking issue."
    )


@pytest.mark.parametrize("name", sorted(LATEST_RECOMMENDED_DEV))
def test_dev_dep_is_latest(name: str) -> None:
    dev = _pkg_json().get("devDependencies", {})
    assert name in dev, f"{name} missing from server/package.json devDependencies"
    if name in ALLOWED_PIN_OVERRIDES:
        return
    assert dev[name] == "latest", (
        f"dev-dep {name} pinned to '{dev[name]}'; default to 'latest' so "
        "we stay aligned with whatever Bun ships."
    )
