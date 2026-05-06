"""Thin httpx wrapper for the Mastra HTTP server."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import httpx

try:
    from .circuit_breaker import CircuitBreaker
    from .client_extra import ClientExtraApi
    from .observation_dedup import ObservationDeduper
    from .response_guard import MastraResponseError, validate_response
except ImportError:
    from circuit_breaker import CircuitBreaker  # type: ignore[no-redef]
    from client_extra import ClientExtraApi  # type: ignore[no-redef]
    from observation_dedup import ObservationDeduper  # type: ignore[no-redef]
    from response_guard import MastraResponseError, validate_response  # type: ignore[no-redef]

logger = logging.getLogger(__name__)
DEFAULT_TIMEOUT = httpx.Timeout(connect=2.0, read=15.0, write=15.0, pool=2.0)
DEFAULT_RESPONSE_MAX_BYTES = 1_000_000


class MastraClient(ClientExtraApi):
    def __init__(
        self,
        base_url: str,
        auth_token: str = "",
        auth_token_env: str = "",
        response_max_bytes: int = DEFAULT_RESPONSE_MAX_BYTES,
        breaker_threshold: int = 5,
        breaker_cooldown_seconds: float = 5.0,
        dedup_lru_size: int = 512,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._auth_token_env = auth_token_env
        self._response_max_bytes = int(response_max_bytes)
        self._http_factory: Callable[[str], Any] = self._default_http_factory
        self._http = self._http_factory(auth_token or self._current_auth_token())
        self._breaker = CircuitBreaker(breaker_threshold, breaker_cooldown_seconds)
        self._dedup = ObservationDeduper(dedup_lru_size)

    def _default_http_factory(self, token: str):
        headers: dict[str, str] = {"content-type": "application/json"}
        if token:
            headers["authorization"] = f"Bearer {token}"
        return httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers)

    def _current_auth_token(self) -> str:
        return os.environ.get(self._auth_token_env, "") if self._auth_token_env else ""

    def _replace_http(self) -> None:
        old = self._http
        self._http = self._http_factory(self._current_auth_token())
        try:
            old.close()
        except Exception:
            pass

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        for attempt in range(3):
            try:
                request = getattr(self._http, method)
                r = request(f"{self._base}{path}", **self._request_kwargs(method, payload))
                if r.status_code == 401 and attempt < 2:
                    self._replace_http()
                    continue
                r.raise_for_status()
                return (
                    validate_response(method, path, r.content, self._response_max_bytes)
                    if r.content
                    else {}
                )
            except (httpx.HTTPError, MastraResponseError) as exc:
                logger.warning("mastra %s %s failed: %s", method.upper(), path, exc)
                return None
        return None

    @staticmethod
    def _request_kwargs(method: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        return {"json": payload or {}} if method == "post" else {"params": payload or {}}

    def _guarded_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        def _call() -> dict[str, Any]:
            result = self._request(method, path, payload)
            if result is None:
                raise RuntimeError("mastra request failed")
            return result

        return self._breaker.call(_call, fallback=None)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._guarded_request("post", path, payload)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self._guarded_request("get", path, params)

    def health(self) -> dict[str, Any] | None:
        return self._get("/health")

    def save_turn(
        self, thread: str, profile: str, user: str = "", assistant: str = "", system: str = ""
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
            "/api/memory/recall", {"thread": thread, "profile": profile, "limit": limit}
        )
        return ((result or {}).get("text") or "").strip()

    def write_observation(self, thread: str, profile: str, text: str, kind: str = "") -> bool:
        if not self._dedup.should_write(thread, profile, kind, text):
            return True
        payload = {"thread": thread, "profile": profile, "text": text, "kind": kind}
        return bool(self._post("/api/memory/observation", payload))

    def update_working_memory(
        self, profile: str, content: str, thread: str = "", action: str = "set"
    ) -> bool:
        payload = {"profile": profile, "content": content, "action": action}
        if thread:
            payload["thread"] = thread
        return bool(self._post("/api/memory/working_memory", payload))

    def flush(self, thread: str, profile: str) -> bool:
        return bool(self._post("/api/memory/flush", {"thread": thread, "profile": profile}))

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass


def _cfg_int(cfg: dict[str, Any], key: str, default: int) -> int:
    return int(cfg.get(key, default) or default)


def _cfg_float(cfg: dict[str, Any], key: str, default: float) -> float:
    return float(cfg.get(key, default) or default)


def client_from_env() -> MastraClient:
    try:
        from .server_manager import load_config  # type: ignore[no-redef]
    except ImportError:
        from server_manager import load_config  # type: ignore[no-redef]

    cfg = load_config()
    auth_env = cfg.get("auth_token_env") or "MASTRA_API_KEY"
    return MastraClient(
        cfg["server_url"],
        auth_token=os.environ.get(auth_env, ""),
        auth_token_env=auth_env,
        response_max_bytes=_cfg_int(cfg, "response_max_bytes", DEFAULT_RESPONSE_MAX_BYTES),
        breaker_threshold=_cfg_int(cfg, "breaker_threshold", 5),
        breaker_cooldown_seconds=_cfg_float(cfg, "breaker_cooldown_seconds", 5.0),
        dedup_lru_size=_cfg_int(cfg, "dedup_lru_size", 512),
    )
