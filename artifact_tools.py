"""Tool-call dispatch for the artifact tools (kept separate to satisfy
the 200-LOC / 30-LOC-per-construct policy enforced by tests/test_code_size_policy.py)."""

from __future__ import annotations

import json
from typing import Any

try:
    from .artifacts import VALID_KINDS  # type: ignore
except ImportError:
    from artifacts import VALID_KINDS  # type: ignore[no-redef]
try:
    from tools.registry import tool_error  # Hermes-provided
except ImportError:  # pragma: no cover — pytest stub

    def tool_error(msg: str) -> str:  # type: ignore[no-redef]
        return json.dumps({"error": msg})


def _validate_kind(args: dict[str, Any]) -> str | None:
    kind = (args.get("kind") or "").strip().lower()
    if kind not in VALID_KINDS:
        return None
    return kind


def do_artifact_get(p, args: dict[str, Any]) -> str:
    kind = _validate_kind(args)
    if not kind:
        return tool_error(f"missing or invalid 'kind' (must be one of: {', '.join(VALID_KINDS)})")
    try:
        result = p._client.get_artifact(kind=kind, profile=p._profile)
    except Exception as exc:
        return tool_error(f"artifact_get failed: {exc}")
    return json.dumps(
        {
            "profile": p._profile,
            "kind": kind,
            "exists": bool(result.get("exists")),
            "version": result.get("version"),
            "content": result.get("content") or "",
        }
    )


def do_artifact_history(p, args: dict[str, Any]) -> str:
    kind = _validate_kind(args)
    if not kind:
        return tool_error(f"missing or invalid 'kind' (must be one of: {', '.join(VALID_KINDS)})")
    limit = max(1, min(int(args.get("limit", 20)), 50))
    try:
        versions = p._client.list_artifact_versions(
            kind=kind,
            profile=p._profile,
            per_page=limit,
        )
    except Exception as exc:
        return tool_error(f"artifact_history failed: {exc}")
    versions = list(versions or [])
    return json.dumps(
        {
            "profile": p._profile,
            "kind": kind,
            "count": len(versions),
            "versions": versions,
        }
    )


def do_artifact_revert(p, args: dict[str, Any]) -> str:
    kind = _validate_kind(args)
    if not kind:
        return tool_error(f"missing or invalid 'kind' (must be one of: {', '.join(VALID_KINDS)})")
    version = args.get("version")
    if not isinstance(version, int) or version < 1:
        return tool_error("missing required parameter: version (positive integer)")
    try:
        ok = p._client.revert_artifact(kind=kind, version=version, profile=p._profile)
    except Exception as exc:
        return tool_error(f"artifact_revert failed: {exc}")
    return json.dumps(
        {
            "profile": p._profile,
            "kind": kind,
            "ok": bool(ok),
            "reverted_to": version,
        }
    )
