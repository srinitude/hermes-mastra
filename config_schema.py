"""Static config schema for `hermes memory setup` — pure data table."""

from __future__ import annotations

from typing import Any


def get_config_schema() -> list[dict[str, Any]]:
    return _SCHEMA


_SCHEMA: list[dict[str, Any]] = [
    {
        "key": "server_url",
        "description": "Mastra server base URL",
        "default": "http://127.0.0.1:4191",
    },
    {"key": "server_port", "description": "Port for the Bun server", "default": "4191"},
    {
        "key": "auto_start",
        "description": "Auto-start Bun server on first use",
        "default": "true",
        "choices": ["true", "false"],
    },
    {
        "key": "observer_url",
        "description": "Observer model URL (OpenAI-compatible)",
        "default": "https://api.venice.ai/api/v1",
    },
    {
        "key": "observer_name",
        "description": "Observer model name",
        "default": "gemini-3-flash-preview",
    },
    {
        "key": "observer_api_key_env",
        "description": "Env var holding Observer API key",
        "default": "VENICE_API_KEY",
    },
    {
        "key": "reflector_url",
        "description": "Reflector model URL (OpenAI-compatible)",
        "default": "https://api.venice.ai/api/v1",
    },
    {
        "key": "reflector_name",
        "description": "Reflector model name",
        "default": "gemini-3-1-pro-preview",
    },
    {
        "key": "reflector_api_key_env",
        "description": "Env var holding Reflector API key",
        "default": "VENICE_API_KEY",
    },
    {"key": "recall_top_k", "description": "Observations injected per turn", "default": "4"},
    {
        "key": "breaker_threshold",
        "description": "Failures before Mastra HTTP breaker opens",
        "default": "5",
    },
    {
        "key": "breaker_cooldown_seconds",
        "description": "Breaker cooldown before half-open probe",
        "default": "5.0",
    },
    {
        "key": "supervisor_max_restarts_per_minute",
        "description": "Maximum bounded Bun restarts per minute",
        "default": "3",
    },
    {
        "key": "recall_cache_lru_size",
        "description": "Profile/thread recall-cache LRU entries",
        "default": "32",
    },
    {"key": "dedup_lru_size", "description": "Observation dedup LRU entries", "default": "512"},
    {
        "key": "response_max_bytes",
        "description": "Maximum Mastra HTTP response bytes",
        "default": "1000000",
    },
    {
        "key": "temporal_markers",
        "description": "Insert temporal-gap markers",
        "default": "true",
        "choices": ["true", "false"],
    },
    {
        "key": "auth_token",
        "description": "Optional bearer token guarding the server",
        "secret": True,
        "env_var": "MASTRA_API_KEY",
    },
    {
        "key": "context_engine_wrapper",
        "description": (
            "Wrap the active context engine to inject Mastra observations "
            "into messages right before compression and bump recall_top_k "
            "under memory pressure"
        ),
        "default": "true",
        "choices": ["true", "false"],
    },
    {
        "key": "context_engine_pressure_fraction",
        "description": (
            "Fraction of the compressor's threshold at which to boost recall_top_k (0.0-1.0)"
        ),
        "default": "0.50",
    },
    {
        "key": "context_engine_boosted_top_k",
        "description": "recall_top_k value while under memory pressure",
        "default": "8",
    },
]
