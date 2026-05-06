"""Tests verifying the Bun server receives flexible model + options config."""

from __future__ import annotations

import json


def test_server_env_includes_observer_and_reflector_keys(fake_hermes_home, monkeypatch):
    import model_config as mc
    import server_manager as sm

    monkeypatch.setenv("OPENAI_API_KEY", "sk-observer-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic-key")

    mc.set_model(
        "observer",
        name="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    )
    mc.set_model(
        "reflector",
        name="claude-3-5-sonnet",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
    )

    cfg = sm.load_config()
    env = sm.server_env(cfg)

    assert env["MASTRA_OBSERVER_NAME"] == "gpt-4o-mini"
    assert env["MASTRA_OBSERVER_URL"] == "https://api.openai.com/v1"
    assert env["MASTRA_OBSERVER_API_KEY"] == "sk-observer-key"
    assert env["MASTRA_REFLECTOR_NAME"] == "claude-3-5-sonnet"
    assert env["MASTRA_REFLECTOR_URL"] == "https://api.anthropic.com/v1"
    assert env["MASTRA_REFLECTOR_API_KEY"] == "sk-anthropic-key"


def test_server_env_includes_options_json_payload(fake_hermes_home):
    import mastra_options as mo
    import server_manager as sm

    mo.set_option("workingMemory.scope", "thread")
    mo.set_option("observationalMemory.observation.messageTokens", 4096)

    cfg = sm.load_config()
    env = sm.server_env(cfg)
    assert "MASTRA_OPTIONS_JSON" in env
    parsed = json.loads(env["MASTRA_OPTIONS_JSON"])
    assert parsed["workingMemory"]["scope"] == "thread"
    assert parsed["observationalMemory"]["observation"]["messageTokens"] == 4096


def test_server_env_options_payload_is_present_even_with_defaults(fake_hermes_home):
    """Even with zero user overrides, the env var ships defaults so the TS
    server gets a single source of truth for options."""
    import server_manager as sm

    cfg = sm.load_config()
    env = sm.server_env(cfg)
    parsed = json.loads(env["MASTRA_OPTIONS_JSON"])
    assert parsed["observationalMemory"]["scope"] == "thread"
    assert parsed["workingMemory"]["enabled"] is True


def test_server_env_maps_gemini_key_for_default_embedder(fake_hermes_home, monkeypatch):
    import server_manager as sm

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "***")

    env = sm.server_env(sm.load_config())

    assert env["MASTRA_EMBEDDER_MODEL"] == "google/gemini-embedding-001"
    assert env["GOOGLE_GENERATIVE_AI_API_KEY"] == "***"
