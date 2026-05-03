"""Tests for the user-facing model configuration API.

Users must be able to set their own Observer/Reflector models without
hand-editing JSON. This test file drives the design — it was written
BEFORE model_config.py existed (RED phase). Implementation follows.

Behaviors covered:
  - Get and set the Observer / Reflector model independently.
  - Three required fields per role: name, base_url, api_key_env.
  - Validation: rejects unknown roles, empty names, malformed URLs.
  - Presets: the plugin ships a few known-good combinations
    (venice, openrouter, openai, anthropic-via-or, hermes-local) and
    `apply_preset` writes both roles in one shot.
  - Round-trip: set → reload → get returns the same values.
  - Backwards-compat: legacy `model_*` fields still load if present.
"""

from __future__ import annotations

import pytest

# ---- get / set roundtrip ---------------------------------------------------


def test_get_returns_defaults_when_unset(fake_hermes_home):
    import model_config as mc

    obs = mc.get_model("observer")
    assert obs["name"], "Observer must have a default name"
    assert obs["base_url"].startswith("https://"), "Observer base_url must default to a real URL"
    assert obs["api_key_env"], "Observer must declare which env var holds its key"


def test_set_observer_persists_to_disk(fake_hermes_home):
    import model_config as mc

    mc.set_model(
        "observer",
        name="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    )
    # New process / fresh import must see the change
    import importlib

    importlib.reload(mc)
    obs = mc.get_model("observer")
    assert obs["name"] == "gpt-4o-mini"
    assert obs["base_url"] == "https://api.openai.com/v1"
    assert obs["api_key_env"] == "OPENAI_API_KEY"


def test_set_reflector_independent_of_observer(fake_hermes_home):
    import model_config as mc

    mc.set_model("observer", name="cheap-model", base_url="https://x/v1", api_key_env="X")
    mc.set_model("reflector", name="strong-model", base_url="https://y/v1", api_key_env="Y")

    assert mc.get_model("observer")["name"] == "cheap-model"
    assert mc.get_model("reflector")["name"] == "strong-model"


# ---- validation ------------------------------------------------------------


def test_set_rejects_unknown_role(fake_hermes_home):
    import model_config as mc

    with pytest.raises(ValueError, match="role"):
        mc.set_model("planner", name="x", base_url="https://x/v1", api_key_env="X")


def test_set_rejects_empty_name(fake_hermes_home):
    import model_config as mc

    with pytest.raises(ValueError, match="name"):
        mc.set_model("observer", name="", base_url="https://x/v1", api_key_env="X")


def test_set_rejects_non_http_url(fake_hermes_home):
    import model_config as mc

    with pytest.raises(ValueError, match="base_url"):
        mc.set_model("observer", name="x", base_url="ftp://nope", api_key_env="X")


def test_set_rejects_lowercase_env_var(fake_hermes_home):
    """API key env vars are conventionally UPPER_SNAKE_CASE — catch typos."""
    import model_config as mc

    with pytest.raises(ValueError, match="api_key_env"):
        mc.set_model("observer", name="x", base_url="https://x/v1", api_key_env="my_key")


# ---- presets ---------------------------------------------------------------


def test_list_presets_returns_known_providers(fake_hermes_home):
    import model_config as mc

    names = {p["id"] for p in mc.list_presets()}
    # The minimum baseline the plugin ships with. Adding more is fine;
    # removing any of these breaks user expectations and this test.
    assert {"venice", "openrouter", "openai", "anthropic-or", "hermes-local"} <= names


def test_apply_preset_writes_both_roles(fake_hermes_home):
    import model_config as mc

    mc.apply_preset("openai")
    obs = mc.get_model("observer")
    refl = mc.get_model("reflector")
    assert obs["base_url"] == "https://api.openai.com/v1"
    assert refl["base_url"] == "https://api.openai.com/v1"
    # Observer is the cheap one; reflector is stronger. They MUST differ
    # within a preset — that's the whole point of split models.
    assert obs["name"] != refl["name"]
    assert obs["api_key_env"] == "OPENAI_API_KEY"
    assert refl["api_key_env"] == "OPENAI_API_KEY"


def test_apply_preset_unknown_raises(fake_hermes_home):
    import model_config as mc

    with pytest.raises(ValueError, match="preset"):
        mc.apply_preset("not-a-real-provider")


def test_hermes_local_preset_points_at_hermes_api_server(fake_hermes_home):
    """The 'hermes-local' preset reuses the user's logged-in Hermes API server,
    so they don't need any extra API keys at all."""
    import model_config as mc

    mc.apply_preset("hermes-local")
    obs = mc.get_model("observer")
    assert "127.0.0.1" in obs["base_url"] or "localhost" in obs["base_url"]
    # No key required; we set api_key_env to a sentinel the server treats as "none"
    assert obs["api_key_env"] in ("", "MASTRA_NO_KEY")


# ---- backwards compatibility ----------------------------------------------


def test_legacy_model_fields_still_load(fake_hermes_home):
    """Older configs only had `model_url` / `model_name` / `model_api_key_env`.
    They must still resolve as the Observer's defaults."""
    import json

    cfg_path = fake_hermes_home / "mastra.json"
    cfg_path.write_text(
        json.dumps(
            {
                "model_url": "https://legacy/v1",
                "model_name": "legacy-model",
                "model_api_key_env": "LEGACY_KEY",
            }
        ),
        encoding="utf-8",
    )

    import importlib

    import model_config as mc

    importlib.reload(mc)
    obs = mc.get_model("observer")
    assert obs["name"] == "legacy-model"
    assert obs["base_url"] == "https://legacy/v1"
    assert obs["api_key_env"] == "LEGACY_KEY"
