"""Config + path helpers for the Mastra server.

Everything here is pure: no subprocess spawning, no network. Splitting this
out keeps `server_process.py` (which DOES spawn) testable in isolation.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PORT = 4191
DEFAULT_HOST = "127.0.0.1"
SERVER_DIR = Path(__file__).parent / "server"


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def config_path() -> Path:
    return _hermes_home() / "mastra.json"


def pid_file() -> Path:
    return _hermes_home() / "mastra.pid"


def log_file() -> Path:
    return _hermes_home() / "logs" / "mastra.log"


def _builtin_defaults() -> dict:
    home = _hermes_home()
    return {
        "server_url": os.environ.get("MASTRA_URL") or f"http://{DEFAULT_HOST}:{DEFAULT_PORT}",
        "server_host": DEFAULT_HOST,
        "server_port": DEFAULT_PORT,
        "auto_start": True,
        "server_per_profile": False,
        "db_path": str(home / "mastra.db"),
        # Legacy single-model fallback used only when role-specific
        # observer_*/reflector_* keys are unset.
        "model_url": "https://api.venice.ai/api/v1",
        "model_name": "gemini-3-flash-preview",
        "model_api_key_env": "VENICE_API_KEY",
        # Split observer/reflector — see model_config.py.
        "observer_url": "https://api.venice.ai/api/v1",
        "observer_name": "gemini-3-flash-preview",
        "observer_api_key_env": "VENICE_API_KEY",
        "reflector_url": "https://api.venice.ai/api/v1",
        "reflector_name": "gemini-3-1-pro-preview",
        "reflector_api_key_env": "VENICE_API_KEY",
        "recall_top_k": 4,
        "recall_token_budget": 1500,
        "temporal_markers": True,
        "share_token_budget": False,
        "auth_token_env": "MASTRA_API_KEY",
        "breaker_threshold": 5,
        "breaker_cooldown_seconds": 5.0,
        "supervisor_max_restarts_per_minute": 3,
        "recall_cache_lru_size": 32,
        "dedup_lru_size": 512,
        "response_max_bytes": 1_000_000,
    }


def load_config() -> dict:
    """Built-in defaults overlaid with $HERMES_HOME/mastra.json + env."""
    cfg = _builtin_defaults()
    p = config_path()
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in user.items() if v not in (None, "")})
        except Exception as exc:  # pragma: no cover
            logger.warning("mastra: failed to parse %s: %s", p, exc)
    if os.environ.get("MASTRA_URL"):
        cfg["server_url"] = os.environ["MASTRA_URL"]
    return _validate_config(cfg)


def _validate_config(cfg: dict) -> dict:
    int_keys = (
        "server_port",
        "recall_top_k",
        "breaker_threshold",
        "supervisor_max_restarts_per_minute",
        "recall_cache_lru_size",
        "dedup_lru_size",
        "response_max_bytes",
    )
    for key in int_keys:
        cfg[key] = max(1, int(cfg[key]))
    cfg["breaker_cooldown_seconds"] = max(0.0, float(cfg["breaker_cooldown_seconds"]))
    return cfg


def save_config(values: dict) -> None:
    p = config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        existing = _read_existing_config(p)
        existing.update(values)
        safe_save_config(p, existing)
    except Exception as exc:
        logger.warning("mastra: config save failed at %s: %s", p, exc)


def _read_existing_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def read_pid() -> int | None:
    p = pid_file()
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_pid(pid: int) -> None:
    safe_write_pid(pid_file(), pid)


def safe_write_pid(path: Path, pid: int) -> bool:
    try:
        path.write_text(str(pid), encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("mastra: pid write failed at %s: %s", path, exc)
        return False


def safe_log_file(path: Path) -> Path | None:
    try:
        if not path.parent.parent.exists():
            raise FileNotFoundError(path.parent.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path
    except Exception as exc:
        logger.warning("mastra: log file unavailable at %s: %s", path, exc)
        return None


def safe_save_config(path: Path, values: dict) -> bool:
    try:
        if not path.parent.exists():
            raise FileNotFoundError(path.parent)
        path.write_text(json.dumps(values, indent=2), encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("mastra: config write failed at %s: %s", path, exc)
        return False


def clear_pid() -> None:
    p = pid_file()
    if p.exists():
        p.unlink(missing_ok=True)
