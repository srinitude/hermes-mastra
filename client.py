"""Thin httpx wrapper for the Mastra HTTP server."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(connect=2.0, read=15.0, write=15.0, pool=2.0)


class MastraClient:
    def __init__(self, base_url: str, auth_token: str = "") -> None:
        self._base = base_url.rstrip("/")
        self._headers: dict[str, str] = {"content-type": "application/json"}
        if auth_token:
            self._headers["authorization"] = f"Bearer {auth_token}"
        # Reuse a single client for connection pooling. We close it on shutdown.
        self._http = httpx.Client(timeout=DEFAULT_TIMEOUT, headers=self._headers)

    # -------- low-level --------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            r = self._http.post(f"{self._base}{path}", json=payload)
            r.raise_for_status()
            return r.json() if r.content else {}
        except httpx.HTTPError as exc:
            logger.warning("mastra POST %s failed: %s", path, exc)
            return None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            r = self._http.get(f"{self._base}{path}", params=params or {})
            r.raise_for_status()
            return r.json() if r.content else {}
        except httpx.HTTPError as exc:
            logger.warning("mastra GET %s failed: %s", path, exc)
            return None

    # -------- high-level --------

    def health(self) -> dict[str, Any] | None:
        return self._get("/health")

    def save_turn(
        self,
        thread: str,
        profile: str,
        user: str = "",
        assistant: str = "",
        system: str = "",
    ) -> bool:
        payload: dict[str, Any] = {"thread": thread, "profile": profile}
        if user:
            payload["user"] = user
        if assistant:
            payload["assistant"] = assistant
        if system:
            payload["system"] = system
        return bool(self._post("/api/memory/messages", payload))

    def recall(self, thread: str, profile: str, limit: int = 4) -> str:
        result = self._get(
            "/api/memory/recall",
            {"thread": thread, "profile": profile, "limit": limit},
        )
        if not result:
            return ""
        return (result.get("text") or "").strip()

    def write_observation(self, thread: str, profile: str, text: str, kind: str = "") -> bool:
        return bool(
            self._post(
                "/api/memory/observation",
                {"thread": thread, "profile": profile, "text": text, "kind": kind},
            )
        )

    def update_working_memory(
        self,
        profile: str,
        content: str,
        thread: str = "",
        action: str = "set",
    ) -> bool:
        payload = {"profile": profile, "content": content, "action": action}
        if thread:
            payload["thread"] = thread
        return bool(self._post("/api/memory/working_memory", payload))

    def flush(self, thread: str, profile: str) -> bool:
        return bool(
            self._post(
                "/api/memory/flush",
                {"thread": thread, "profile": profile},
            )
        )

    def list_threads(self, profile: str) -> list[dict[str, Any]]:
        result = self._get("/api/memory/threads", {"profile": profile})
        return list((result or {}).get("threads") or [])

    def list_observations(self, thread: str, profile: str) -> list[dict[str, Any]]:
        result = self._get(
            "/api/memory/observations",
            {"thread": thread, "profile": profile},
        )
        return list((result or {}).get("observations") or [])

    def search_observations(
        self,
        query: str,
        profile: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Keyword search across all observations in this profile.

        Parallel to Hermes' `session_search` tool but operates on the
        Mastra observation log rather than raw conversation transcripts.
        Each result includes the `thread` field so callers can correlate
        with `session_search` results from the same session.
        """
        result = self._get(
            "/api/memory/search",
            {"query": query, "profile": profile, "limit": limit},
        )
        return list((result or {}).get("observations") or [])

    def semantic_search(
        self,
        query: str,
        profile: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Vector / semantic search via Mastra's `vectorSearchString`.

        Off the hot path — invoked only when the model deliberately calls
        the `mastra_semantic_search` tool. Falls back to empty list if
        the server's vector store is not configured.
        """
        result = self._get(
            "/api/memory/semantic_search",
            {"query": query, "profile": profile, "limit": limit},
        )
        return list((result or {}).get("observations") or [])

    def get_working_memory(self, profile: str) -> str:
        """Read the working-memory mirror back as plain text.

        Off the hot path — exposed only via the `mastra_working_memory`
        tool. Returns empty string if no working memory has been stored
        for this profile yet.
        """
        result = self._get(
            "/api/memory/working_memory",
            {"profile": profile},
        )
        return ((result or {}).get("working_memory") or "").strip()

    # -- artifact API (SOUL.md / MEMORY.md / USER.md / AGENTS.md as
    #    versioned Mastra prompt-blocks; see HERMES_INTEGRATION_MAP §2.6)

    def get_artifact(self, kind: str, profile: str = "default") -> dict[str, Any]:
        """Return the latest version of a Hermes artifact (kind ∈ soul/memory/user/agents)."""
        return self._get("/api/memory/artifact", {"kind": kind, "profile": profile}) or {}

    def upsert_artifact(
        self,
        kind: str,
        content: str,
        profile: str = "default",
        path: str = "",
        change_message: str = "",
    ) -> bool:
        """Create or version-bump an artifact. Idempotent — content equality
        with the active version is detected server-side via prompt-blocks."""
        payload: dict[str, Any] = {"kind": kind, "profile": profile, "content": content}
        if path:
            payload["path"] = path
        if change_message:
            payload["changeMessage"] = change_message
        return bool(self._post("/api/memory/artifact", payload))

    def list_artifact_versions(
        self,
        kind: str,
        profile: str = "default",
        per_page: int = 20,
    ) -> list[dict[str, Any]]:
        """Return version history (newest first) for an artifact."""
        result = self._get(
            "/api/memory/artifact/history",
            {"kind": kind, "profile": profile, "per_page": per_page},
        )
        return list((result or {}).get("versions") or [])

    def revert_artifact(
        self,
        kind: str,
        version: int,
        profile: str = "default",
    ) -> bool:
        """Append a NEW version with the content of an older one — preserves history."""
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

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:  # pragma: no cover
            pass


def client_from_env() -> MastraClient:
    """Convenience constructor used by the plugin and CLI."""
    try:
        from .server_manager import load_config  # type: ignore[no-redef]
    except ImportError:
        from server_manager import load_config  # type: ignore[no-redef]

    cfg = load_config()
    auth_env = cfg.get("auth_token_env") or "MASTRA_API_KEY"
    auth = os.environ.get(auth_env, "")
    return MastraClient(cfg["server_url"], auth_token=auth)
