"""B03 — secret-redaction tests (R09)."""

from __future__ import annotations

import time

import pytest

from tests.helpers.red_phase import bring_up

GITHUB_PAT = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
OPENROUTER_KEY = "sk-or-v1-r9redactme9deadbeefcafe1234567890abcdef1234567890abcdef"
BEARER_TOKEN = "Bearer ey.r9redactme.eyJhbGciOiJIUzI1NiJ9.r9deadbeefdeadbeef"
PASSWORD_LINE = "pass" + "word=" + "hunter2-r9redactme"
SECRETS = (GITHUB_PAT, OPENROUTER_KEY, BEARER_TOKEN, PASSWORD_LINE)


def test_imports_secret_redaction_surface() -> None:
    """Sanity smoke — the modules R09 will exercise are importable."""
    import agent_observers
    import client
    import provider_lifecycle


def _secret_payload() -> str:
    return (
        f"github_pat={GITHUB_PAT}; openrouter={OPENROUTER_KEY}; "
        f"auth={BEARER_TOKEN}; {PASSWORD_LINE}"
    )


def _await_settle(client, profile: str, deadline_seconds: float) -> str:
    deadline = time.monotonic() + deadline_seconds
    last = ""
    while time.monotonic() < deadline:
        candidate = client.get_working_memory(profile)
        if candidate and candidate == last:
            return candidate
        last = candidate
        time.sleep(0.1)
    return last


def _assert_redacted(observed: str, profile: str) -> None:
    leaked = [s for s in SECRETS if s in observed]
    assert not leaked, (
        "raw secrets leaked into Mastra working memory via "
        f"on_memory_write: {leaked!r}; "
        f"working_memory(profile={profile!r})={observed!r}"
    )
    assert "[REDACTED]" in observed, (
        "redaction marker `[REDACTED]` not present in Mastra "
        f"working memory after secret-bearing on_memory_write; "
        f"got {observed!r}"
    )


@pytest.mark.integration
def test_red_secret_redaction_observations(mastra_client) -> None:
    """R09 — every Mastra write path must redact raw secrets.

    Contract from G3/G8: no observation, working-memory entry, or
    artifact may contain the raw value of a recognized secret pattern,
    and a ``[REDACTED]`` marker must be present where the secret was.

    Failure mode today: hermes-mastra has no redaction filter — secrets
    pass through ``do_memory_write`` / ``client.update_working_memory``
    unchanged into Mastra working memory.
    """
    provider = bring_up("r09-redaction")
    try:
        provider.on_memory_write(
            action="add",
            target="MEMORY.md",
            content=_secret_payload(),
            metadata={"r09": True},
        )
        observed = _await_settle(mastra_client, provider._profile, deadline_seconds=2.0)
        _assert_redacted(observed, provider._profile)
    finally:
        provider.shutdown()
