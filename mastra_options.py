"""Flexible Mastra Memory option passthrough.

The plugin is a *dumb JSON courier* for Mastra's `MemoryOptions`. Anything
documented at https://mastra.ai/reference/memory/Memory can be set by the
user via dotted keys without the Python plugin needing to know the schema:

    import mastra_options as mo
    mo.set_option("workingMemory.scope", "thread")
    mo.set_option("observationalMemory.observation.messageTokens", 4000)
    mo.set_option("semanticRecall", False)

The merged options dict is serialised to JSON and exposed to the Bun server
via the ``MASTRA_OPTIONS_JSON`` env var. The TS server deep-merges the
user payload over its built-in defaults before constructing
``new Memory({ options })``.

Storage: ``$HERMES_HOME/mastra.json`` under the top-level ``"mastra"`` key.
Built-in defaults live in this module (``DEFAULTS``) — they're returned by
``resolve_options()`` only when the user hasn't overridden them.

Backwards compatibility: legacy snake_case fields like ``temporal_markers``
and ``share_token_budget`` continue to resolve to their Mastra equivalents
under ``observationalMemory.{temporalMarkers,shareTokenBudget}``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def derive_resource_id(hermes_home: str, agent_identity: str | None = None) -> str:
    """A06 contract: ``f"hermes:{agent_identity or 'default'}@{home_basename}"``.

    Centralised so every Mastra surface (client.observe / recall / search /
    semantic_search / working_memory / artifacts / agent_observers /
    tool_observers) routes through ONE derivation rule. Profile isolation
    (G5) requires both the per-profile ``agent_identity`` and the per-home
    ``Path(hermes_home).name`` to be folded into the resourceId so two
    Hermes installations never cross-pollinate via a default resourceId.
    """
    home_basename = Path(hermes_home).name if hermes_home else ""
    identity = (agent_identity or "").strip() or "default"
    if not home_basename:
        raise ValueError(
            f"derive_resource_id requires a non-empty hermes_home; got hermes_home={hermes_home!r}"
        )
    return f"hermes:{identity}@{home_basename}"


RESILIENCE_KNOBS: dict[str, type[int] | type[float]] = {
    "breaker_threshold": int,
    "breaker_cooldown_seconds": float,
    "supervisor_max_restarts_per_minute": int,
    "recall_cache_lru_size": int,
    "dedup_lru_size": int,
    "response_max_bytes": int,
}


def _load_raw() -> dict:
    try:
        from .server_manager import load_config  # type: ignore[no-redef]
    except ImportError:
        from server_manager import load_config  # type: ignore[no-redef]
    return load_config()


def _save_raw(values: dict) -> None:
    try:
        from .server_manager import save_config  # type: ignore[no-redef]
    except ImportError:
        from server_manager import save_config  # type: ignore[no-redef]
    save_config(values)


# ---------------------------------------------------------------------------
# Built-in defaults — anything Mastra's `Memory({ options })` accepts.
# Users may override any of these via set_option(); deletions via unset_option().
# ---------------------------------------------------------------------------

WORKING_MEMORY_TEMPLATE = """# Hermes Working Memory

## Current User / Resource
- Stable preferences:
- Durable profile facts:
- Active constraints:

## Current Task State
- Goal:
- Important files, URLs, or IDs:
- Open questions:

## Update Rules
- Keep this concise and current.
- Preserve useful durable facts; remove stale task details when they stop mattering."""

SEMANTIC_RECALL_DEFAULTS: dict[str, Any] = {
    "topK": 5,
    "messageRange": {"before": 2, "after": 2},
    "scope": "resource",
    "threshold": 0.65,
}

DEFAULTS: dict[str, Any] = {
    "readOnly": False,
    "lastMessages": 20,
    "generateTitle": False,
    "filterIncompleteToolCalls": True,
    "semanticRecall": SEMANTIC_RECALL_DEFAULTS,
    "workingMemory": {
        "enabled": True,
        "scope": "resource",
        "template": WORKING_MEMORY_TEMPLATE,
    },
    "observationalMemory": {
        "enabled": True,
        "scope": "thread",
        "temporalMarkers": True,
        "shareTokenBudget": False,
        "retrieval": {"vector": True, "scope": "resource"},
        "activateAfterIdle": "5m",
        "activateOnProviderChange": True,
        "observation": {
            "messageTokens": 60_000,
            "modelSettings": {"temperature": 0.3, "maxOutputTokens": 100_000},
            "maxTokensPerBatch": 40_000,
            "bufferTokens": 0.2,
            "bufferActivation": 0.8,
            "blockAfter": 1.2,
            "previousObserverTokens": 10_000,
            "threadTitle": True,
        },
        "reflection": {
            "observationTokens": 80_000,
            "modelSettings": {"temperature": 0, "maxOutputTokens": 100_000},
            "bufferActivation": 0.5,
            "blockAfter": 1.2,
        },
    },
}

# Map from old snake_case keys to dotted Mastra paths (for legacy configs).
_LEGACY_FIELD_MAP: dict[str, str] = {
    "temporal_markers": "observationalMemory.temporalMarkers",
    "share_token_budget": "observationalMemory.shareTokenBudget",
}


# ---------------------------------------------------------------------------
# dotted-key helpers
# ---------------------------------------------------------------------------


def _split_key(key: str) -> list[str]:
    if not key or not isinstance(key, str):
        raise ValueError("key must be a non-empty string")
    parts = key.split(".")
    if any(not p for p in parts):
        raise ValueError(f"key '{key}' has empty segment (no '..' or trailing '.')")
    return parts


def _set_in(d: dict, parts: list[str], value: Any) -> None:
    cursor = d
    for i, part in enumerate(parts[:-1]):
        existing = cursor.get(part)
        if existing is None:
            cursor[part] = {}
        elif not isinstance(existing, dict):
            path = ".".join(parts[: i + 1])
            raise ValueError(
                f"cannot descend into '{path}': existing value is a scalar "
                f"({type(existing).__name__}). Unset it first."
            )
        cursor = cursor[part]
    cursor[parts[-1]] = value


def _unset_in(d: dict, parts: list[str]) -> bool:
    cursor = d
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            return False
        cursor = nxt
    return cursor.pop(parts[-1], None) is not None


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursive merge — overlay wins on scalar conflicts, dicts merge."""
    out = copy.deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_user_overrides() -> dict[str, Any]:
    """Return the raw user-supplied mastra options (no defaults merged)."""
    raw = _load_raw()
    user = raw.get("mastra")
    return copy.deepcopy(user) if isinstance(user, dict) else {}


def resolve_options() -> dict[str, Any]:
    """Return the fully-merged Mastra MemoryOptions: defaults + legacy + user."""
    cfg = _load_raw()
    merged = copy.deepcopy(DEFAULTS)

    # Translate legacy snake_case top-level fields into dotted Mastra paths.
    for legacy_key, dotted in _LEGACY_FIELD_MAP.items():
        if legacy_key in cfg and cfg[legacy_key] not in (None, ""):
            _set_in(merged, _split_key(dotted), cfg[legacy_key])

    # Apply user "mastra" overlay last so it wins on conflicts.
    user = cfg.get("mastra")
    if isinstance(user, dict):
        merged = _deep_merge(merged, user)
    return merged


def set_option(key: str, value: Any) -> None:
    """Persist a single dotted-key option to the user mastra overlay."""
    parts = _split_key(key)
    raw = _load_raw()
    user = raw.get("mastra")
    if not isinstance(user, dict):
        user = {}
    _set_in(user, parts, value)  # raises ValueError on scalar collision
    _save_raw({"mastra": user})


def unset_option(key: str) -> bool:
    """Remove a single dotted-key option. Returns True if it was present."""
    parts = _split_key(key)
    raw = _load_raw()
    user = raw.get("mastra")
    if not isinstance(user, dict):
        return False
    removed = _unset_in(user, parts)
    _save_raw({"mastra": user})
    return removed


def reset_options() -> None:
    """Delete ALL user mastra overrides (keep legacy + role config)."""
    _save_raw({"mastra": {}})


def options_env_payload() -> str:
    """JSON-encoded merged options ready for ``MASTRA_OPTIONS_JSON``."""
    return json.dumps(resolve_options(), separators=(",", ":"))
