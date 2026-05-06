"""Mastra Observational Memory provider — thin orchestrator class.

The real work lives in sibling modules (each ≤200 LOC, each construct ≤30 LOC):
  * ``provider_lifecycle`` — every MemoryProvider hook as a free function
  * ``provider_tools``     — config schema + tool-call dispatch
  * ``recall_cache``       — non-blocking cached observation snapshot
  * ``async_runner``       — bounded background work queue
  * ``client``             — thin httpx wrapper around the Bun server
  * ``server_manager``     — Bun server config / install / lifecycle
  * ``model_config``       — Observer + Reflector model selection
  * ``mastra_options``     — flexible Mastra ``MemoryOptions`` passthrough
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from . import async_runner
    from . import provider_lifecycle as L
    from . import provider_tools as T
    from .recall_cache import RecallCache
except ImportError:
    import async_runner  # type: ignore[no-redef]
    import provider_lifecycle as L  # type: ignore[no-redef]
    import provider_tools as T  # type: ignore[no-redef]
    from recall_cache import RecallCache  # type: ignore[no-redef]

try:
    from agent.memory_provider import MemoryProvider
except ImportError:  # pragma: no cover — pytest stub

    class MemoryProvider:  # type: ignore[no-redef]
        pass


logger = logging.getLogger(__name__)


class MastraMemoryProvider(MemoryProvider):
    """Thin shell — every method delegates to provider_lifecycle / provider_tools."""

    def __init__(self) -> None:
        self._client = None
        self._cfg: dict[str, Any] = {}
        self._profile = "default"
        self._thread = ""
        self._cron_skipped = False
        self._recall_cache = RecallCache()
        self._observation_count = 0
        self._observation_floor = 5
        self._last_user_message = ""

    @property
    def name(self) -> str:
        return "mastra"

    def is_available(self) -> bool:
        try:
            from .server_manager import find_bun, load_config  # type: ignore
        except ImportError:
            from server_manager import find_bun, load_config  # type: ignore[no-redef]
        try:
            load_config()
            return bool(find_bun())
        except Exception:
            return False

    def get_config_schema(self) -> list[dict[str, Any]]:
        return T.get_config_schema()

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        try:
            from .server_manager import save_config as _sc  # type: ignore
        except ImportError:
            from server_manager import save_config as _sc  # type: ignore[no-redef]
        _sc(T.coerce_config_values(values))

    def post_setup(self, hermes_home: str, config: dict) -> None:
        try:
            from .memory_rules import install_memory_rules  # type: ignore
            from .server_manager import install_dependencies, start_server  # type: ignore
        except ImportError:
            from memory_rules import install_memory_rules  # type: ignore[no-redef]
            from server_manager import install_dependencies, start_server  # type: ignore[no-redef]
        ok, msg = install_dependencies()
        logger.info("mastra: install_dependencies -> %s (%s)", ok, msg)
        ok, msg = start_server()
        logger.info("mastra: start_server -> %s (%s)", ok, msg)
        # Install the canonical routing rules into MEMORY.md / USER.md so
        # the agent learns to off-load durable facts to mastra instead
        # of growing the small built-in stores. Idempotent; safe on re-setup.
        try:
            changed = install_memory_rules()
            for name, was_changed in changed.items():
                logger.info(
                    "mastra: %s rule install → %s",
                    name,
                    "added" if was_changed else "already present",
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("mastra: failed to install memory rules: %s", exc)

    # --- lifecycle hooks: pure delegation ---

    def initialize(self, session_id: str, **kwargs) -> None:
        L.do_initialize(self, session_id, **kwargs)

    def system_prompt_block(self) -> str:
        if self._cron_skipped or self._client is None:
            return ""
        block = (
            "## Mastra Observational Memory\n"
            f"Active profile: `{self._profile}` · thread: `{self._thread}`\n"
            "Recent observations are injected below when available. "
            "Three recall surfaces are available — pick the right one:\n"
            "  - `mastra_recall` for THIS thread's distilled observation log\n"
            "  - `mastra_search` for keyword search across past observations "
            "in this profile\n"
            "  - `session_search` for raw past-session transcript search "
            "(complementary to Mastra)\n"
            "Use `mastra_observe` to persist a durable note."
        )
        hint = self._capacity_hint()
        if hint:
            block += "\n\n" + hint
        return block

    def _capacity_hint(self) -> str:
        """Suggest the right Mastra tool for capacity or recall pressure."""
        full = self._full_builtin_memory_labels()
        obs_count = int(getattr(self, "_observation_count", 0) or 0)
        floor = int(getattr(self, "_observation_floor", 5) or 5)
        if full and obs_count < floor:
            return (
                f"⚠ Built-in memory near capacity: {', '.join(full)}. "
                "Persist durable overflow with `mastra_observe`."
            )
        message = str(getattr(self, "_last_user_message", "") or "").casefold()
        wants_recall = any(verb in message for verb in ("remember", "last time", "we did"))
        if wants_recall and not self._recall_cache.get(self._profile, self._thread):
            return "Need prior context? Use `mastra_search` for profile-wide observations."
        return ""

    def _full_builtin_memory_labels(self) -> list[str]:
        labels: list[str] = []
        for attr, name in (("_memory_usage_pct", "MEMORY.md"), ("_user_usage_pct", "USER.md")):
            pct = getattr(self, attr, None)
            if isinstance(pct, (int, float)) and pct >= 0.50:
                labels.append(f"{name} ({int(pct * 100)}%)")
        return labels

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        return L.do_prefetch(self, query, session_id=session_id)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        L.do_queue_prefetch(self, query, session_id=session_id)

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        L.do_sync_turn(self, user_content, assistant_content, session_id=session_id)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        if self._cron_skipped:
            return []
        return T.tool_schemas()

    def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
        L.do_turn_start(self, turn_number, message, **kwargs)

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs) -> str:
        return T.handle_tool_call(self, tool_name, args)

    def on_session_switch(
        self, new_session_id: str, *, parent_session_id: str = "", reset: bool = False, **kwargs
    ) -> None:
        L.do_session_switch(self, new_session_id, parent_session_id=parent_session_id, reset=reset)

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        return L.do_pre_compress(self, messages)

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        L.do_session_end(self, messages)

    def on_memory_write(
        self, action: str, target: str, content: str, metadata: dict[str, Any] | None = None
    ) -> None:
        L.do_memory_write(self, action, target, content, metadata)

    def on_delegation(
        self, task: str, result: str, *, child_session_id: str = "", **kwargs
    ) -> None:
        L.do_delegation(self, task, result, child_session_id=child_session_id)

    def shutdown(self) -> None:
        try:
            async_runner.shutdown(wait=async_runner.SHUTDOWN_TIMEOUT)
        except Exception:  # pragma: no cover
            pass
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


def register(ctx) -> None:
    """Plugin entry point — registers the provider and wires it via the hook system."""
    provider = MastraMemoryProvider()
    ctx.register_memory_provider(provider)
    # Wire post_tool_call / on_session_reset / on_session_finalize so the
    # provider's observers fire automatically as the agent runs.
    try:
        try:
            from .hermes_wiring import activate_for  # type: ignore
        except ImportError:
            from hermes_wiring import activate_for  # type: ignore[no-redef]
        callbacks = activate_for(provider)
        for hook_name in (
            "pre_tool_call",
            "post_tool_call",
            "on_session_reset",
            "on_session_finalize",
        ):
            cb = callbacks.get(hook_name)
            if cb is not None and hasattr(ctx, "register_hook"):
                ctx.register_hook(hook_name, cb)
    except Exception as exc:  # pragma: no cover
        logger.warning("mastra: failed to wire plugin hooks: %s", exc)

    # Optionally install the Mastra-aware ContextEngine wrapper.
    # Wiring lives in engine_install.py to keep this file under budget.
    try:
        try:
            from .engine_install import install_engine  # type: ignore
        except ImportError:
            from engine_install import install_engine  # type: ignore[no-redef]
        install_engine(ctx, provider)
    except Exception as exc:  # pragma: no cover
        logger.warning("mastra: engine install failed: %s", exc)
