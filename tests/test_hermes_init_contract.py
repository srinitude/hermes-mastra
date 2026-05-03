"""Tests for the doc-contracted Hermes init kwargs the plugin must honor.

Per https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin
``initialize(session_id, **kwargs)`` is documented to ALWAYS receive
``hermes_home: str`` — the active HERMES_HOME path. Storage paths must
respect it instead of going through the global hermes_constants lookup,
otherwise profile isolation breaks when Hermes is invoked across profiles.

Additionally Hermes has historically passed the active profile name under
several keys (`agent_identity`, `profile`, sometimes nested in
`agent_context`). The plugin should accept all three for resilience.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def slow_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    return c


@pytest.fixture
def provider(fake_hermes_home, slow_client):
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    yield p
    p.shutdown()


# ---- profile name resolution ---------------------------------------------


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({}, "default"),
        ({"agent_identity": "venice"}, "venice"),
        ({"profile": "krysum"}, "krysum"),
        # agent_identity beats profile when both present
        ({"agent_identity": "alpha", "profile": "beta"}, "alpha"),
        # whitespace stripped
        ({"agent_identity": "  trimmed  "}, "trimmed"),
        # explicit empty string falls back to default
        ({"agent_identity": "", "profile": ""}, "default"),
    ],
)
def test_profile_resolution(provider, kwargs, expected):
    from provider_lifecycle import do_initialize

    do_initialize(provider, "sess-1", **kwargs)
    assert provider._profile == expected


# ---- hermes_home contract -------------------------------------------------


def test_hermes_home_kwarg_overrides_global(tmp_path, fake_hermes_home, slow_client, monkeypatch):
    """When Hermes passes hermes_home in kwargs, the plugin must use that path
    for any subsequent storage decisions instead of falling back to the
    process-wide HERMES_HOME / hermes_constants lookup."""
    from provider_lifecycle import do_initialize
    from tests.helpers import make_provider

    # Hermes-supplied profile-specific home
    profile_home = tmp_path / "profile-isolated"
    profile_home.mkdir()

    p = make_provider(slow_client)
    do_initialize(p, "sess", agent_identity="profile-x", hermes_home=str(profile_home))

    # The provider should record the override so downstream paths use it.
    assert getattr(p, "_hermes_home", None) == str(profile_home), (
        "do_initialize must capture kwargs['hermes_home'] onto the provider "
        "so storage decisions honor Hermes' profile isolation contract."
    )
    p.shutdown()
