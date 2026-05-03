"""Built-in Observer/Reflector model presets — pure data tables."""

from __future__ import annotations

from typing import Any

DEFAULT_OBSERVER = {
    "name": "gemini-3-flash-preview",
    "base_url": "https://api.venice.ai/api/v1",
    "api_key_env": "VENICE_API_KEY",
}

DEFAULT_REFLECTOR = {
    "name": "gemini-3-1-pro-preview",
    "base_url": "https://api.venice.ai/api/v1",
    "api_key_env": "VENICE_API_KEY",
}

PRESETS: list[dict[str, Any]] = [
    {
        "id": "venice",
        "label": "Venice (default — Gemini 3 split)",
        "observer": DEFAULT_OBSERVER,
        "reflector": DEFAULT_REFLECTOR,
    },
    {
        "id": "openai",
        "label": "OpenAI (gpt-4o-mini → gpt-4o)",
        "observer": {
            "name": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
        "reflector": {
            "name": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
    },
    {
        "id": "openrouter",
        "label": "OpenRouter (Llama 3.1 8B → Claude 3.5 Sonnet)",
        "observer": {
            "name": "meta-llama/llama-3.1-8b-instruct",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
        },
        "reflector": {
            "name": "anthropic/claude-3.5-sonnet",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
        },
    },
    {
        "id": "anthropic-or",
        "label": "Anthropic via OpenRouter (Haiku → Sonnet)",
        "observer": {
            "name": "anthropic/claude-3.5-haiku",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
        },
        "reflector": {
            "name": "anthropic/claude-3.5-sonnet",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
        },
    },
    {
        "id": "hermes-local",
        "label": "Hermes API server (no extra keys — reuses your logged-in provider)",
        "observer": {
            "name": "openai/Hermes-4-405B",
            "base_url": "http://127.0.0.1:3140/v1",
            "api_key_env": "MASTRA_NO_KEY",
        },
        "reflector": {
            "name": "openai/Hermes-4-405B",
            "base_url": "http://127.0.0.1:3140/v1",
            "api_key_env": "MASTRA_NO_KEY",
        },
    },
]


def find_preset(preset_id: str) -> dict[str, Any] | None:
    for p in PRESETS:
        if p["id"] == preset_id:
            return p
    return None
