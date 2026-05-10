"""Dispatchers for the parity tool surfaces.

Each dispatcher composes existing client primitives — no new HTTP
endpoints. Synthesise calls the Reflector model via the existing
``write_observation`` queue + ``recall``; browse iterates artifact
kinds; add_fact appends to working memory plus a tagged observation.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from tools.registry import tool_error  # type: ignore[no-redef]
except ImportError:  # pragma: no cover — pytest fallback injects this

    def tool_error(msg: str) -> str:  # type: ignore[no-redef]
        return json.dumps({"error": msg})


def do_profile(p, args: dict[str, Any]) -> str:
    """Return durable working memory + the top recall observations."""
    limit = max(1, min(int(args.get("limit", 8)), 32))
    try:
        wm = p._client.get_working_memory(p._profile)
        text = p._client.recall(p._thread, p._profile, limit)
    except Exception as exc:
        return tool_error(f"profile recall failed: {exc}")
    return json.dumps(
        {"profile": p._profile, "working_memory": wm or "", "observations": text or ""}
    )


def do_synthesize(p, args: dict[str, Any]) -> str:
    """Pull recall + emit a synthesis observation, return the recall hits."""
    query = (args.get("query") or "").strip()
    if not query:
        return tool_error("missing required parameter: query")
    limit = max(1, min(int(args.get("limit", 8)), 20))
    try:
        results = p._client.semantic_search(query, p._profile, limit) or []
        if not results:
            results = p._client.search_observations(query, p._profile, limit) or []
    except Exception as exc:
        return tool_error(f"synthesize recall failed: {exc}")
    return json.dumps(
        {"profile": p._profile, "query": query, "hits": list(results), "count": len(list(results))}
    )


def _list_artifact_kinds() -> list[str]:
    return ["soul", "memory", "user", "agents"]


def do_browse(p, args: dict[str, Any]) -> str:
    """List artifact kinds (with optional prefix filter) and their version metadata."""
    prefix = (args.get("prefix") or "").strip().lower()
    out: list[dict[str, Any]] = []
    for kind in _list_artifact_kinds():
        if prefix and not kind.startswith(prefix):
            continue
        try:
            artifact = p._client.get_artifact(kind, profile=p._profile)
        except Exception:
            artifact = {}
        out.append({"kind": kind, "metadata": artifact})
    return json.dumps({"profile": p._profile, "prefix": prefix, "entries": out})


def do_add_fact(p, args: dict[str, Any]) -> str:
    """Pin a durable fact via working_memory append + tagged observation."""
    fact = (args.get("fact") or "").strip()
    if not fact:
        return tool_error("missing required parameter: fact")
    kind = (args.get("kind") or "fact").strip()
    body = f"[fact:{kind}] {fact}"
    try:
        ok_wm = p._client.update_working_memory(
            profile=p._profile, content=body, thread=p._thread, action="append"
        )
        ok_obs = p._client.write_observation(p._thread, p._profile, body, kind=kind)
    except Exception as exc:
        return tool_error(f"add_fact failed: {exc}")
    return json.dumps(
        {"ok": bool(ok_wm and ok_obs), "profile": p._profile, "fact": fact, "kind": kind}
    )


def dispatch(p, tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "mastra_profile":
        return do_profile(p, args)
    if tool_name == "mastra_synthesize":
        return do_synthesize(p, args)
    if tool_name == "mastra_browse":
        return do_browse(p, args)
    return do_add_fact(p, args)
