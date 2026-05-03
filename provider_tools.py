"""Config schema + tool-call dispatch — small enough to keep in one file."""

from __future__ import annotations

import json
from typing import Any

try:
    from .config_schema import get_config_schema  # type: ignore[no-redef]
    from .tool_schemas import (
        ARTIFACT_GET_SCHEMA,
        ARTIFACT_HISTORY_SCHEMA,
        ARTIFACT_REVERT_SCHEMA,
        OBSERVE_SCHEMA,
        RECALL_SCHEMA,
        SEARCH_SCHEMA,
        SEMANTIC_SEARCH_SCHEMA,
        WORKING_MEMORY_GET_SCHEMA,
    )
except ImportError:
    from config_schema import get_config_schema  # type: ignore[no-redef]  # noqa: F401
    from tool_schemas import (  # type: ignore[no-redef]
        ARTIFACT_GET_SCHEMA,
        ARTIFACT_HISTORY_SCHEMA,
        ARTIFACT_REVERT_SCHEMA,
        OBSERVE_SCHEMA,
        RECALL_SCHEMA,
        SEARCH_SCHEMA,
        SEMANTIC_SEARCH_SCHEMA,
        WORKING_MEMORY_GET_SCHEMA,
    )
try:
    from tools.registry import tool_error  # Hermes-provided
except ImportError:  # pragma: no cover — pytest stub injects this

    def tool_error(msg: str) -> str:  # type: ignore[no-redef]
        return json.dumps({"error": msg})


def coerce_config_values(values: dict[str, Any]) -> dict[str, Any]:
    """Normalise string-form CLI input into typed config values."""
    out: dict[str, Any] = {}
    for k, v in values.items():
        out[k] = _coerce_one(k, v)
    return out


def _coerce_one(key: str, value: Any) -> Any:
    if key in {"auto_start", "temporal_markers", "context_engine_wrapper"} and isinstance(
        value, str
    ):
        return value.lower() == "true"
    if key in {"server_port", "recall_top_k", "context_engine_boosted_top_k"} and isinstance(
        value, str
    ):
        try:
            return int(value)
        except ValueError:
            return value
    if key == "context_engine_pressure_fraction" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def handle_tool_call(p, tool_name: str, args: dict[str, Any]) -> str:  # noqa: PLR0911
    if not p._client:
        return tool_error("mastra server is not running")
    if tool_name == "mastra_recall":
        return _do_recall(p, args)
    if tool_name == "mastra_observe":
        return _do_observe(p, args)
    if tool_name == "mastra_search":
        return _do_search(p, args)
    if tool_name == "mastra_semantic_search":
        return _do_semantic_search(p, args)
    if tool_name == "mastra_working_memory":
        return _do_working_memory_get(p, args)
    if tool_name in {"mastra_artifact_get", "mastra_artifact_history", "mastra_artifact_revert"}:
        return _dispatch_artifact(p, tool_name, args)
    return tool_error(f"unknown tool: {tool_name}")


def _dispatch_artifact(p, tool_name: str, args: dict[str, Any]) -> str:
    try:
        from .artifact_tools import (  # type: ignore
            do_artifact_get,
            do_artifact_history,
            do_artifact_revert,
        )
    except ImportError:
        from artifact_tools import (  # type: ignore[no-redef]
            do_artifact_get,
            do_artifact_history,
            do_artifact_revert,
        )
    if tool_name == "mastra_artifact_get":
        return do_artifact_get(p, args)
    if tool_name == "mastra_artifact_history":
        return do_artifact_history(p, args)
    return do_artifact_revert(p, args)


def _do_recall(p, args: dict[str, Any]) -> str:
    limit = max(1, min(int(args.get("limit", 8)), 32))
    try:
        text = p._client.recall(p._thread, p._profile, limit)
    except Exception as exc:
        return tool_error(f"recall failed: {exc}")
    return json.dumps(
        {"profile": p._profile, "thread": p._thread, "observations": text or "(none yet)"}
    )


def _do_observe(p, args: dict[str, Any]) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return tool_error("missing required parameter: text")
    kind = (args.get("kind") or "").strip()
    try:
        ok = p._client.write_observation(p._thread, p._profile, text, kind=kind)
    except Exception as exc:
        return tool_error(f"observe failed: {exc}")
    return json.dumps({"ok": bool(ok), "profile": p._profile, "thread": p._thread})


def _do_search(p, args: dict[str, Any]) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return tool_error("missing required parameter: query")
    limit = max(1, min(int(args.get("limit", 8)), 20))
    try:
        results = p._client.search_observations(query, p._profile, limit)
    except Exception as exc:
        return tool_error(f"search failed: {exc}")
    results = list(results or [])
    payload: dict[str, Any] = {
        "profile": p._profile,
        "query": query,
        "count": len(results),
        "observations": results,
    }
    if not results:
        payload["message"] = (
            "no matches in this profile's observations — try `session_search` "
            "for raw transcript matches across all sessions"
        )
    return json.dumps(payload)


def tool_schemas() -> list[dict[str, Any]]:
    return [
        RECALL_SCHEMA,
        OBSERVE_SCHEMA,
        SEARCH_SCHEMA,
        SEMANTIC_SEARCH_SCHEMA,
        WORKING_MEMORY_GET_SCHEMA,
        ARTIFACT_GET_SCHEMA,
        ARTIFACT_HISTORY_SCHEMA,
        ARTIFACT_REVERT_SCHEMA,
    ]


def _do_semantic_search(p, args: dict[str, Any]) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return tool_error("missing required parameter: query")
    limit = max(1, min(int(args.get("limit", 8)), 20))
    try:
        results = p._client.semantic_search(query=query, profile=p._profile, limit=limit)
    except Exception as exc:
        return tool_error(f"semantic_search failed: {exc}")
    results = list(results or [])
    payload: dict[str, Any] = {
        "profile": p._profile,
        "query": query,
        "count": len(results),
        "observations": results,
    }
    if not results:
        payload["message"] = (
            "no semantic matches — vector store may be unconfigured; "
            "fall back to `mastra_search` for keyword search"
        )
    return json.dumps(payload)


def _do_working_memory_get(p, args: dict[str, Any]) -> str:
    try:
        text = p._client.get_working_memory(profile=p._profile)
    except Exception as exc:
        return tool_error(f"working_memory read failed: {exc}")
    payload: dict[str, Any] = {
        "profile": p._profile,
        "working_memory": text or "",
    }
    if not text:
        payload["message"] = (
            "working memory empty — built-in MEMORY.md / USER.md is the canonical store"
        )
    return json.dumps(payload)
