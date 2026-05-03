"""Implementations of every ``hermes mastra <subcommand>``.

Kept separate from ``cli.py`` (parser + dispatch) so each function is a
clean unit and the main file stays under the 200-LOC budget.
"""

from __future__ import annotations

import json
import sys

try:
    from .client import client_from_env
    from .server_manager import (
        config_path,
        ensure_running,
        install_dependencies,
        is_running,
        load_config,
        log_file,
        save_config,
        start_server,
        stop_server,
    )
except ImportError:
    from client import client_from_env  # type: ignore[no-redef]
    from server_manager import (  # type: ignore[no-redef]
        config_path,
        ensure_running,
        install_dependencies,
        is_running,
        load_config,
        log_file,
        save_config,
        start_server,
        stop_server,
    )


def _print_setup_summary(cfg: dict) -> None:
    print("Mastra Observational Memory — setup")
    print(f"  config: {config_path()}")
    print(f"  current server URL: {cfg['server_url']}")
    print(f"  current model:      {cfg['model_name']} via {cfg['model_url']}")
    print()


def _prompt_setup(cfg: dict) -> dict:
    new_url = input(f"Server URL [{cfg['server_url']}]: ").strip() or cfg["server_url"]
    new_port = input(f"Port [{cfg['server_port']}]: ").strip() or str(cfg["server_port"])
    new_model = input(f"Observer model [{cfg['model_name']}]: ").strip() or cfg["model_name"]
    new_url2 = input(f"Observer model URL [{cfg['model_url']}]: ").strip() or cfg["model_url"]
    return {
        "server_url": new_url,
        "server_port": int(new_port),
        "model_name": new_model,
        "model_url": new_url2,
    }


def cmd_setup() -> int:
    cfg = load_config()
    _print_setup_summary(cfg)
    save_config(_prompt_setup(cfg))
    print("→ wrote config")
    print("→ installing Bun dependencies...")
    ok, msg = install_dependencies()
    print(f"  {'OK' if ok else 'FAIL'}: {msg}")
    if not ok:
        return 1
    print("→ starting server...")
    ok, msg = start_server()
    print(f"  {'OK' if ok else 'FAIL'}: {msg}")
    return 0 if ok else 1


def _maybe_print_health(cfg: dict) -> None:
    if not is_running():
        return
    try:
        client = client_from_env()
        print(f"health:        {json.dumps(client.health(), indent=2)}")
        client.close()
    except Exception as exc:
        print(f"health probe failed: {exc}")


def _maybe_print_log() -> None:
    log_p = log_file()
    if not log_p.exists():
        return
    print(f"\n--- last 10 lines of {log_p} ---")
    try:
        tail = log_p.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
        print("\n".join(tail))
    except Exception as exc:
        print(f"(could not read log: {exc})")


def cmd_status() -> int:
    cfg = load_config()
    print(f"server_url:    {cfg['server_url']}")
    print(f"db_path:       {cfg['db_path']}")
    print(f"model:         {cfg['model_name']} via {cfg['model_url']}")
    print(f"running:       {is_running()}")
    _maybe_print_health(cfg)
    _maybe_print_log()
    return 0


def _restart_server() -> tuple[bool, str]:
    _stop_ok, stop_msg = stop_server()
    ok, msg = start_server()
    return ok, f"stop: {stop_msg}; start: {msg}"


_SERVER_SUBS = {
    "start": start_server,
    "stop": stop_server,
    "restart": _restart_server,
    "install": install_dependencies,
}


def cmd_server(server_command: str) -> int:
    handler = _SERVER_SUBS.get(server_command)
    if handler is None:
        print("unknown server command", file=sys.stderr)
        return 2
    ok, msg = handler()
    print(msg)
    return 0 if ok else 1


def cmd_logs(lines: int) -> int:
    p = log_file()
    if not p.exists():
        print("(no log yet)")
        return 0
    text = p.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(text[-lines:]))
    return 0


def _with_running_client(fn):
    ok, msg = ensure_running(auto_start=False)
    if not ok:
        print(f"server not running: {msg}", file=sys.stderr)
        return 1
    client = client_from_env()
    try:
        return fn(client)
    finally:
        client.close()


def cmd_resources() -> int:
    def _go(client):
        for r in client.list_resources():
            print(r)
        return 0

    return _with_running_client(_go)


def cmd_threads(profile: str) -> int:
    def _go(client):
        for t in client.list_threads(profile):
            tid = t.get("id") or t.get("threadId") or "?"
            print(f"{tid}\t{t.get('title') or ''}")
        return 0

    return _with_running_client(_go)


def cmd_observations(thread: str, profile: str) -> int:
    def _go(client):
        print(json.dumps(client.list_observations(thread, profile), indent=2, default=str))
        return 0

    return _with_running_client(_go)


def cmd_reset(profile: str, yes: bool) -> int:
    if not yes:
        confirm = input(f"Wipe ALL Mastra data for profile '{profile}'? [y/N] ").strip().lower()
        if confirm != "y":
            print("cancelled")
            return 1

    def _go(client):
        deleted = client.reset_profile(profile)
        print(f"deleted {deleted} threads for profile '{profile}'")
        return 0

    return _with_running_client(_go)
