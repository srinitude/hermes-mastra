"""Less-hot tool dispatchers split out so provider_tools.py fits the LOC budget."""

from __future__ import annotations

import json
from typing import Any

try:
    from tools.registry import tool_error  # type: ignore[no-redef]
except ImportError:  # pragma: no cover

    def tool_error(msg: str) -> str:  # type: ignore[no-redef]
        return json.dumps({"error": msg})


def do_semantic_search(p, args: dict[str, Any]) -> str:
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


def do_working_memory_get(p, args: dict[str, Any]) -> str:
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
            "working memory empty — Mastra has no working-memory entry yet; "
            "MEMORY.md / USER.md remain the cold-start disk cache"
        )
    return json.dumps(payload)
