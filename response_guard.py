"""Boundary validators for Mastra HTTP responses."""

from __future__ import annotations

import json
from typing import Any


class MastraResponseError(ValueError):
    """Structured response-boundary failure consumed by safe_call."""

    def __init__(self, cause: dict[str, Any]) -> None:
        self.cause = cause
        super().__init__(f"mastra response error: {cause['category']}")


def _decode(payload: bytes, max_bytes: int, operation: str) -> dict[str, Any]:
    if len(payload) > max_bytes:
        raise MastraResponseError({"category": "oversized", "operation": operation})
    try:
        data = json.loads(payload.decode("utf-8")) if payload else {}
    except Exception as exc:
        raise MastraResponseError({"category": "non_json", "operation": operation}) from exc
    if not isinstance(data, dict):
        raise MastraResponseError({"category": "schema", "operation": operation})
    return data


def _require(data: dict[str, Any], keys: set[str], operation: str) -> dict[str, Any]:
    if not keys.issubset(data):
        raise MastraResponseError({"category": "schema", "operation": operation})
    return data


def validate_recall_response(payload: bytes, max_bytes: int = 1_000_000) -> dict[str, Any]:
    return _require(_decode(payload, max_bytes, "recall"), {"text"}, "recall")


def validate_search_response(payload: bytes, max_bytes: int = 1_000_000) -> dict[str, Any]:
    return _require(_decode(payload, max_bytes, "search"), {"observations"}, "search")


def validate_working_memory_response(payload: bytes, max_bytes: int = 1_000_000) -> dict[str, Any]:
    return _require(
        _decode(payload, max_bytes, "working_memory"), {"working_memory"}, "working_memory"
    )


def validate_json_response(payload: bytes, max_bytes: int = 1_000_000) -> dict[str, Any]:
    return _decode(payload, max_bytes, "generic")


def validate_response(
    method: str, path: str, payload: bytes, max_bytes: int = 1_000_000
) -> dict[str, Any]:
    if method == "get" and path.endswith("/api/memory/recall"):
        return validate_recall_response(payload, max_bytes)
    if method == "get" and path.endswith("/api/memory/working_memory"):
        return validate_working_memory_response(payload, max_bytes)
    if method == "get" and _is_observation_path(path):
        return validate_search_response(payload, max_bytes)
    return validate_json_response(payload, max_bytes)


def _is_observation_path(path: str) -> bool:
    return path.endswith(
        ("/api/memory/search", "/api/memory/semantic_search", "/api/memory/observations")
    )
