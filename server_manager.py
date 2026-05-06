"""Backwards-compatible re-export shim.

The plugin originally exposed everything as ``server_manager.<name>``.
We've split the module into focused pieces (``server_config``, ``server_env``,
``server_process``) so each fits the project size budget. This shim
preserves the old import surface for existing callers and tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING  # noqa: F401

try:  # package context (Hermes loader: plugins.memory.mastra.server_manager)
    from .server_config import (
        DEFAULT_HOST,
        DEFAULT_PORT,
        SERVER_DIR,
        clear_pid,
        config_path,
        is_port_open,
        load_config,
        log_file,
        pid_file,
        read_pid,
        safe_log_file,
        safe_save_config,
        safe_write_pid,
        save_config,
        write_pid,
    )
    from .server_env import build_server_env as server_env
    from .server_process import (
        ensure_running,
        find_bun,
        install_dependencies,
        is_running,
        start_server,
        stop_server,
    )
except ImportError:  # pytest / direct sys.path import
    from server_config import (  # type: ignore[no-redef]  # noqa: F401
        DEFAULT_HOST,
        DEFAULT_PORT,
        SERVER_DIR,
        clear_pid,
        config_path,
        is_port_open,
        load_config,
        log_file,
        pid_file,
        read_pid,
        safe_log_file,
        safe_save_config,
        safe_write_pid,
        save_config,
        write_pid,
    )
    from server_env import build_server_env as server_env  # type: ignore[no-redef]  # noqa: F401
    from server_process import (  # type: ignore[no-redef]  # noqa: F401
        ensure_running,
        find_bun,
        install_dependencies,
        is_running,
        start_server,
        stop_server,
    )
