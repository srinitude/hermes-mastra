"""argparse wiring for ``hermes mastra``.

Implementations live in ``cli_commands``; this file only does
declarations + dispatch so it stays well under the 200-LOC budget.
"""

from __future__ import annotations

import argparse
import sys

try:
    from .cli_commands import (
        cmd_logs,
        cmd_observations,
        cmd_reset,
        cmd_resources,
        cmd_server,
        cmd_setup,
        cmd_status,
        cmd_threads,
    )
except ImportError:
    from cli_commands import (  # type: ignore[no-redef]
        cmd_logs,
        cmd_observations,
        cmd_reset,
        cmd_resources,
        cmd_server,
        cmd_setup,
        cmd_status,
        cmd_threads,
    )


def _add_server_subparser(parent) -> None:
    server = parent.add_parser("server", help="Lifecycle for the bundled Bun server")
    sp = server.add_subparsers(dest="server_command", required=True)
    sp.add_parser("start", help="Start the server")
    sp.add_parser("stop", help="Stop the server")
    sp.add_parser("restart", help="Restart the server")
    sp.add_parser("install", help="Run `bun install` for the server")


def _add_observation_subparsers(parent) -> None:
    parent.add_parser("resources", help="List Mastra resourceIds (profiles) seen so far")
    threads = parent.add_parser("threads", help="List threads for a profile")
    threads.add_argument("--profile", default="default")
    obs = parent.add_parser("observations", help="Dump observations for a thread")
    obs.add_argument("thread")
    obs.add_argument("--profile", default="default")
    reset = parent.add_parser("reset", help="Wipe a profile's threads + observations")
    reset.add_argument("--profile", required=True)
    reset.add_argument("--yes", action="store_true", help="Skip confirmation")


def register_cli(subparsers) -> None:
    """Plug into Hermes argparse as ``hermes mastra ...``."""
    p = subparsers.add_parser("mastra", help="Manage Mastra Observational Memory plugin")
    sp = p.add_subparsers(dest="mastra_command", required=True)
    sp.add_parser("setup", help="Configure and start the Mastra server")
    sp.add_parser("status", help="Show health, pid, port, recent log lines")
    _add_server_subparser(sp)
    logs = sp.add_parser("logs", help="Tail the server log")
    logs.add_argument("-n", "--lines", type=int, default=80)
    _add_observation_subparsers(sp)


_DISPATCH = {
    "setup": lambda args: cmd_setup(),
    "status": lambda args: cmd_status(),
    "server": lambda args: cmd_server(args.server_command),
    "logs": lambda args: cmd_logs(args.lines),
    "resources": lambda args: cmd_resources(),
    "threads": lambda args: cmd_threads(args.profile),
    "observations": lambda args: cmd_observations(args.thread, args.profile),
    "reset": lambda args: cmd_reset(args.profile, args.yes),
}


def mastra_command(args: argparse.Namespace) -> int:
    handler = _DISPATCH.get(getattr(args, "mastra_command", None) or "")
    if handler is None:
        print("unknown mastra command", file=sys.stderr)
        return 2
    return handler(args)
