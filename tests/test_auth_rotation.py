"""R11 RED: auth-token rotation rebuilds the HTTP client on first 401."""

from __future__ import annotations

import httpx

from client import MastraClient


class _Transport:
    def __init__(self) -> None:
        self.closed = False
        self.statuses = [401, 200]
        self.headers: list[str] = []

    def get(self, url, params=None):
        self.headers.append(getattr(self, "auth", ""))
        status = self.statuses.pop(0)
        return httpx.Response(status, json={"ok": True}, request=httpx.Request("GET", url))

    def close(self) -> None:
        self.closed = True


def test_401_rebuilds_client_with_rotated_env_token(monkeypatch):
    old, new = _Transport(), _Transport()
    monkeypatch.setenv("MASTRA_API_KEY", "old-token")
    client = MastraClient("http://mastra.test", auth_token_env="MASTRA_API_KEY")
    client._http = old
    monkeypatch.setenv("MASTRA_API_KEY", "new-token")
    client._http_factory = lambda token: setattr(new, "auth", token) or new
    assert client.health() == {"ok": True}
    assert old.closed is True
    assert new.auth == "new-token"
