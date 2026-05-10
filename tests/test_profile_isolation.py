"""B03 — profile-isolation tests (R08)."""

from __future__ import annotations

import os
import time

import pytest

from tests.helpers.red_phase import bring_up


def test_imports_profile_isolation_surface() -> None:
    """Sanity smoke — the modules R08 / G02 will exercise are importable."""
    import client
    import mastra_options
    import provider_lifecycle


def _make_two_homes(tmp_path):
    home_a = tmp_path / "hermes_home_A"
    home_a.mkdir()
    home_b = tmp_path / "hermes_home_B"
    home_b.mkdir()
    return home_a, home_b


def _await_b_pollution(provider_b, token_a: str) -> str:
    deadline = time.monotonic() + 2.0
    wm_b = ""
    while time.monotonic() < deadline:
        wm_b = provider_b._client.get_working_memory(provider_b._profile)
        if wm_b:
            break
        time.sleep(0.05)
    return wm_b


def _assert_no_cross_pollination(wm_b: str, token_a: str, profile_b: str) -> None:
    assert token_a not in wm_b, (
        "Profile B saw Profile A's memory_write payload — "
        f"profile={profile_b!r} working_memory={wm_b!r} "
        f"contains the home-A-only token {token_a!r}; the resource "
        "id is not derived from per-home agent_identity"
    )


@pytest.mark.integration
def test_red_profile_isolation_full(mastra_server, tmp_path) -> None:
    """R08 — Profile A and Profile B must NOT share working memory.

    Failure mode today: client.update_working_memory keys by raw
    ``profile`` only; two providers with different HERMES_HOME dirs
    but the same profile share ``hermes:default`` and cross-pollinate.
    """
    home_a, home_b = _make_two_homes(tmp_path)
    saved_home = os.environ.get("HERMES_HOME")
    try:
        os.environ["HERMES_HOME"] = str(mastra_server["home"])
        provider_a = bring_up("r08-isolation-A", str(home_a))
        provider_b = bring_up("r08-isolation-B", str(home_b))
        try:
            token_a = "r08_alpha_token_should_stay_in_A"
            provider_a.on_memory_write("add", "MEMORY.md", token_a, {})
            wm_b = _await_b_pollution(provider_b, token_a)
            _assert_no_cross_pollination(wm_b, token_a, provider_b._profile)
        finally:
            provider_a.shutdown()
            provider_b.shutdown()
    finally:
        if saved_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = saved_home
