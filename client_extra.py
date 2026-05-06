"""Less-hot MastraClient API surface split out for file-size policy."""

from __future__ import annotations

from typing import Any


class ClientExtraApi:
    def list_threads(self, profile: str) -> list[dict[str, Any]]:
        result = self._get("/api/memory/threads", {"profile": profile})
        return list((result or {}).get("threads") or [])

    def list_observations(self, thread: str, profile: str) -> list[dict[str, Any]]:
        result = self._get("/api/memory/observations", {"thread": thread, "profile": profile})
        return list((result or {}).get("observations") or [])

    def search_observations(self, query: str, profile: str, limit: int = 8) -> list[dict[str, Any]]:
        result = self._get(
            "/api/memory/search", {"query": query, "profile": profile, "limit": limit}
        )
        return list((result or {}).get("observations") or [])

    def semantic_search(self, query: str, profile: str, limit: int = 8) -> list[dict[str, Any]]:
        result = self._get(
            "/api/memory/semantic_search",
            {"query": query, "profile": profile, "limit": limit},
        )
        return list((result or {}).get("observations") or [])

    def get_working_memory(self, profile: str) -> str:
        result = self._get("/api/memory/working_memory", {"profile": profile})
        return ((result or {}).get("working_memory") or "").strip()

    def get_artifact(self, kind: str, profile: str = "default") -> dict[str, Any]:
        return self._get("/api/memory/artifact", {"kind": kind, "profile": profile}) or {}

    def upsert_artifact(
        self,
        kind: str,
        content: str,
        profile: str = "default",
        path: str = "",
        change_message: str = "",
    ) -> bool:
        payload: dict[str, Any] = {"kind": kind, "profile": profile, "content": content}
        if path:
            payload["path"] = path
        if change_message:
            payload["changeMessage"] = change_message
        return bool(self._post("/api/memory/artifact", payload))

    def list_artifact_versions(
        self, kind: str, profile: str = "default", per_page: int = 20
    ) -> list[dict[str, Any]]:
        result = self._get(
            "/api/memory/artifact/history",
            {"kind": kind, "profile": profile, "per_page": per_page},
        )
        return list((result or {}).get("versions") or [])

    def revert_artifact(self, kind: str, version: int, profile: str = "default") -> bool:
        return bool(
            self._post(
                "/api/memory/artifact/revert",
                {"kind": kind, "profile": profile, "version": version},
            )
        )

    def list_resources(self) -> list[str]:
        result = self._get("/api/memory/resources")
        return list((result or {}).get("resources") or [])

    def reset_profile(self, profile: str) -> int:
        result = self._post("/api/memory/reset", {"profile": profile})
        return int((result or {}).get("deleted") or 0)
