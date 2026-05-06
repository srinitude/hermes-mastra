"""Build the env dict for the Bun server subprocess.

Read every relevant config field + env var, resolve API keys, and tack on
the flexible Mastra ``MemoryOptions`` JSON payload. Pulled out of
``server_process.py`` so the env-building rules are testable in isolation.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _resolve_key(env_var_name: str) -> str:
    return os.environ.get(env_var_name, "") if env_var_name else ""


def _base_env(cfg: dict) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "MASTRA_PORT": str(cfg["server_port"]),
            "MASTRA_HOST": cfg["server_host"],
            "MASTRA_DB_URL": f"file:{cfg['db_path']}",
            "MASTRA_MODEL_URL": cfg["model_url"],
            "MASTRA_MODEL_NAME": cfg["model_name"],
            "MASTRA_OBSERVER_URL": cfg.get("observer_url", cfg["model_url"]),
            "MASTRA_OBSERVER_NAME": cfg.get("observer_name", cfg["model_name"]),
            "MASTRA_REFLECTOR_URL": cfg.get("reflector_url", cfg["model_url"]),
            "MASTRA_REFLECTOR_NAME": cfg.get("reflector_name", cfg["model_name"]),
            "MASTRA_TEMPORAL": "true" if cfg["temporal_markers"] else "false",
            "MASTRA_SHARE_BUDGET": "true" if cfg["share_token_budget"] else "false",
            "MASTRA_RECALL_TOP_K": str(cfg["recall_top_k"]),
        }
    )
    return env


def _attach_api_keys(env: dict, cfg: dict) -> None:
    legacy_key = _resolve_key(cfg.get("model_api_key_env") or "")
    observer_key = _resolve_key(cfg.get("observer_api_key_env") or "") or legacy_key
    reflector_key = _resolve_key(cfg.get("reflector_api_key_env") or "") or legacy_key
    if legacy_key:
        env["MASTRA_MODEL_API_KEY"] = legacy_key
    if observer_key:
        env["MASTRA_OBSERVER_API_KEY"] = observer_key
    if reflector_key:
        env["MASTRA_REFLECTOR_API_KEY"] = reflector_key


def _attach_auth(env: dict, cfg: dict) -> None:
    auth_env = cfg.get("auth_token_env") or ""
    if auth_env and os.environ.get(auth_env):
        env["MASTRA_API_KEY"] = os.environ[auth_env]


def _attach_embedder(env: dict) -> None:
    if "MASTRA_EMBEDDER_MODEL" not in env:
        env["MASTRA_EMBEDDER_MODEL"] = (
            "openai/text-embedding-3-small"
            if os.environ.get("OPENAI_API_KEY")
            else "google/gemini-embedding-001"
        )
    google_key = (
        os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    )
    if google_key and "GOOGLE_GENERATIVE_AI_API_KEY" not in env:
        env["GOOGLE_GENERATIVE_AI_API_KEY"] = google_key


def _attach_options_payload(env: dict) -> None:
    try:
        try:
            from .mastra_options import options_env_payload  # type: ignore
        except ImportError:
            from mastra_options import options_env_payload  # type: ignore[no-redef]
        env["MASTRA_OPTIONS_JSON"] = options_env_payload()
    except Exception as exc:  # pragma: no cover
        logger.warning("mastra: failed to build options payload: %s", exc)


def build_server_env(cfg: dict) -> dict:
    """Return the full env dict used to spawn the Bun server."""
    env = _base_env(cfg)
    _attach_api_keys(env, cfg)
    _attach_auth(env, cfg)
    _attach_embedder(env)
    _attach_options_payload(env)
    return env
