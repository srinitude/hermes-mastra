"""Bun install + spawn + stop for the Mastra server.

Kept separate from ``server_config.py`` (pure helpers) and ``server_env.py``
(env-dict builder) so each file stays small and each function stays testable.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import signal
import subprocess
import time

try:  # package context (Hermes loader)
    from .server_config import (
        SERVER_DIR,
        clear_pid,
        is_port_open,
        load_config,
        log_file,
        read_pid,
        safe_log_file,
        write_pid,
    )
    from .server_env import build_server_env
except ImportError:  # pytest / direct sys.path import
    from server_config import (  # type: ignore[no-redef]
        SERVER_DIR,
        clear_pid,
        is_port_open,
        load_config,
        log_file,
        read_pid,
        safe_log_file,
        write_pid,
    )
    from server_env import build_server_env  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Windows compatibility guards
# ---------------------------------------------------------------------------
_IS_WINDOWS = platform.system() == "Windows"
# Windows has no SIGKILL; fall back to SIGTERM (which is the only reliable
# way to terminate a process on Windows via os.kill).
if _IS_WINDOWS:
    SIGKILL = signal.SIGTERM  # type: ignore[misc]
else:
    SIGKILL = signal.SIGKILL  # type: ignore[misc]

logger = logging.getLogger(__name__)


def find_bun() -> str | None:
    return shutil.which("bun")


def install_dependencies() -> tuple[bool, str]:
    bun = find_bun()
    if not bun:
        return False, "bun not found in PATH. Install from https://bun.com"
    try:
        result = subprocess.run(
            [bun, "install"],
            cwd=str(SERVER_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, "bun install timed out after 300s"
    except Exception as exc:
        return False, f"bun install failed: {exc}"
    if result.returncode != 0:
        return False, f"bun install failed: {result.stderr.strip() or result.stdout.strip()}"
    return True, "ok"


def is_running() -> bool:
    cfg = load_config()
    pid = read_pid()
    if not pid:
        return is_port_open(cfg["server_host"], int(cfg["server_port"]))
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return is_port_open(cfg["server_host"], int(cfg["server_port"]))


def _spawn_bun(cfg: dict, log_path) -> tuple[subprocess.Popen | None, str | None]:
    bun = find_bun()
    if not bun:
        return None, "bun not found in PATH. Install from https://bun.com"
    log_fh = open(log_path, "ab", buffering=0)
    # start_new_session is Unix-only (creates new process group for killpg).
    # On Windows, subprocess.Popen has no such parameter in some versions
    # and process groups work differently.
    popen_kwargs: dict = dict(
        cwd=str(SERVER_DIR),
        env=build_server_env(cfg),
        stdout=log_fh,
        stderr=log_fh,
        stdin=subprocess.DEVNULL,
    )
    if not _IS_WINDOWS:
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen([bun, "run", "start"], **popen_kwargs)
    except Exception as exc:
        log_fh.close()
        return None, f"spawn failed: {exc}"
    return proc, None


def _wait_for_ready(proc: subprocess.Popen, cfg: dict, deadline: float, log_path):
    while time.monotonic() < deadline:
        if is_port_open(cfg["server_host"], int(cfg["server_port"])):
            return True, f"started on {cfg['server_url']} (pid {proc.pid})"
        if proc.poll() is not None:
            clear_pid()
            return False, f"process exited prematurely (code {proc.returncode}); see {log_path}"
        time.sleep(0.25)
    return False, f"server did not respond before deadline; see {log_path}"


def start_server(wait_seconds: float = 6.0) -> tuple[bool, str]:
    cfg = load_config()
    if is_running():
        return True, f"already running on {cfg['server_url']}"
    if not (SERVER_DIR / "node_modules").exists():
        ok, msg = install_dependencies()
        if not ok:
            return False, f"install failed: {msg}"
    log_path = safe_log_file(log_file())
    if log_path is None:
        return False, "log file unavailable"
    proc, err = _spawn_bun(cfg, log_path)
    if proc is None:
        return False, err or "spawn failed"
    write_pid(proc.pid)
    return _wait_for_ready(proc, cfg, time.monotonic() + wait_seconds, log_path)


def _try_sigterm(pid: int) -> tuple[bool, str]:
    try:
        if _IS_WINDOWS:
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True, ""
    except ProcessLookupError:
        clear_pid()
        return False, "already gone"
    except Exception as exc:
        return False, f"SIGTERM failed: {exc}"


def stop_server(timeout: float = 5.0) -> tuple[bool, str]:
    pid = read_pid()
    if not pid:
        clear_pid()
        return True, "no pid file"
    ok, msg = _try_sigterm(pid)
    if not ok:
        return msg == "already gone", msg
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            clear_pid()
            return True, f"stopped (pid {pid})"
        time.sleep(0.25)
    try:
        if _IS_WINDOWS:
            os.kill(pid, SIGKILL)
        else:
            os.killpg(os.getpgid(pid), SIGKILL)
    except Exception:
        pass
    clear_pid()
    return True, f"force-killed (pid {pid})"


def ensure_running(auto_start: bool | None = None) -> tuple[bool, str]:
    if is_running():
        return True, "running"
    cfg = load_config()
    if auto_start is None:
        auto_start = bool(cfg.get("auto_start", True))
    if not auto_start or os.environ.get("MASTRA_DISABLE_AUTOSTART"):
        return False, "not running (auto_start disabled)"
    return start_server()
