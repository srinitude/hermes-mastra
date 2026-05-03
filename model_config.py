"""Observer / Reflector model configuration — user-facing API.

Tiny module: just dispatch into ``model_presets`` (data) and
``server_manager`` (storage). Validation rules live here.
"""

from __future__ import annotations

import json
import re
from typing import Any

try:
    from .model_presets import (  # type: ignore
        DEFAULT_OBSERVER,
        DEFAULT_REFLECTOR,
        PRESETS,
        find_preset,
    )
    from .server_manager import config_path, save_config
except ImportError:
    from model_presets import (  # type: ignore[no-redef]
        DEFAULT_OBSERVER,
        DEFAULT_REFLECTOR,
        PRESETS,
        find_preset,
    )
    from server_manager import config_path, save_config  # type: ignore[no-redef]

ROLES = ("observer", "reflector")
_ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _load_user_raw() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role '{role}' (valid: {', '.join(ROLES)})")


def _check_name(name: str) -> None:
    if not name or not name.strip():
        raise ValueError("model name must be a non-empty string")


def _check_base_url(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"base_url must start with http:// or https:// (got '{url}')")


def _check_api_key_env(env_var: str) -> None:
    if env_var == "":
        return
    if not _ENV_VAR_RE.match(env_var):
        raise ValueError(
            f"api_key_env must be UPPER_SNAKE_CASE matching ^[A-Z][A-Z0-9_]*$ (got '{env_var}')"
        )


def _resolve_field(role: str, field: str, role_user: dict, legacy: dict, default: dict) -> str:
    for src in (role_user, legacy, default):
        v = src.get(field)
        if v:
            return v
    return ""


def get_model(role: str) -> dict[str, str]:
    """Return ``{name, base_url, api_key_env}`` for the requested role.

    Resolution: explicit ``<role>_*`` keys → (Observer only) legacy ``model_*``
    → built-in defaults.
    """
    _check_role(role)
    user_raw = _load_user_raw()
    role_user = {
        "name": user_raw.get(f"{role}_name"),
        "base_url": user_raw.get(f"{role}_url"),
        "api_key_env": user_raw.get(f"{role}_api_key_env"),
    }
    legacy = (
        {
            "name": user_raw.get("model_name"),
            "base_url": user_raw.get("model_url"),
            "api_key_env": user_raw.get("model_api_key_env"),
        }
        if role == "observer"
        else {}
    )
    default = DEFAULT_OBSERVER if role == "observer" else DEFAULT_REFLECTOR
    return {
        "name": _resolve_field(role, "name", role_user, legacy, default),
        "base_url": _resolve_field(role, "base_url", role_user, legacy, default),
        "api_key_env": _resolve_field(role, "api_key_env", role_user, legacy, default),
    }


def set_model(role: str, *, name: str, base_url: str, api_key_env: str) -> None:
    _check_role(role)
    _check_name(name)
    _check_base_url(base_url)
    _check_api_key_env(api_key_env)
    save_config(
        {
            f"{role}_name": name,
            f"{role}_url": base_url,
            f"{role}_api_key_env": api_key_env,
        }
    )


def list_presets() -> list[dict[str, Any]]:
    return [dict(p) for p in PRESETS]


def apply_preset(preset_id: str) -> dict[str, Any]:
    p = find_preset(preset_id)
    if not p:
        valid = ", ".join(x["id"] for x in PRESETS)
        raise ValueError(f"unknown preset '{preset_id}' (valid: {valid})")
    set_model("observer", **p["observer"])
    set_model("reflector", **p["reflector"])
    return p
