# Hermes Agent Plugin Contract

This document is the *operational* contract this plugin honours, derived
directly from the Hermes Agent source tree at
`~/.hermes/hermes-agent/`. Where Hermes documents a behaviour but the
source enforces a stricter version, we follow the source.

## 1. Plugin identity

* **Plugin name** — must match the directory name and the `name:` field
  in `plugin.yaml`. Our value: `mastra`.
* **Manifest version** — `manifest_version: 1`.
* **Plugin kind** — `kind: exclusive`. This routes us through the
  `plugins/memory/` discovery system; the general PluginManager skips
  exclusive plugins entirely (`hermes_cli/plugins.py:654`).
* **Category** — `category: memory` (informational; loader pins the
  category from filesystem location).
* **Aliasing rule** — a plugin must NOT advertise multiple names; the
  PluginContext.manifest.name is the only canonical identity used by
  the registry.

## 2. Plugin metadata

* `version` — semver string. We're at `0.1.0`.
* `author`, `homepage`, `license` — informational, surface in
  `hermes plugins list`.
* `runtime.platforms` — `[darwin, linux, win32]`.
* `pip_dependencies` — list of pip names, installed by the
  `hermes plugins install` flow into the active venv.
* `requires_env` — list of env var requirement objects (`name`,
  `description`, `url`, `secret`). Hermes emits a warning if a
  required env var is missing at load time; the plugin still loads.

## 3. Plugin registration

* Plugin directory must contain `plugin.yaml` AND `__init__.py`.
* `__init__.py` MUST define `def register(ctx)`. The function is
  called exactly once per process. For memory plugins the `ctx`
  exposes `register_memory_provider` (memory loader) plus
  `register_hook` (general PluginContext interface re-exposed).
* `register()` is permitted to raise on misconfiguration; the loader
  catches and records the error in `LoadedPlugin.error` without
  killing the host process.

## 4. Plugin configuration

* Config schema returned from `MemoryProvider.get_config_schema()`
  drives `hermes memory setup`. Each field: `key`, `description`,
  `secret`, `required`, optional `default`, `choices`, `url`,
  `env_var`.
* Plugin owns `~/.hermes/<profile>/data/mastra/mastra.json` for
  non-secret config. Secrets go to `~/.hermes/.env` under
  plugin-specific names (e.g. `VENICE_API_KEY`).
* `MemoryProvider.save_config(values, hermes_home)` is the canonical
  write path. Plugins MUST NOT write outside `hermes_home`.

## 5. Plugin dependencies

* Pip deps declared in `plugin.yaml:pip_dependencies` are validated
  via `pip check` in the active venv at load time.
* Bun deps live in `server/package.json`; `server/` is launched in a
  child Bun process, isolated from the agent's Python deps.
* Cross-plugin dependencies are **not supported** by the Hermes plugin
  runtime — plugins cannot import from each other.

## 6. Plugin lifecycle hooks

For memory plugins specifically (the union of `MemoryProvider` and
`hermes_wiring`):

| Phase           | Method / hook                                      | Required?  |
|-----------------|----------------------------------------------------|------------|
| Discovery       | manifest parse                                     | yes        |
| Registration    | `register(ctx)` → `ctx.register_memory_provider()`| yes        |
| Pre-flight      | `is_available()`                                   | yes        |
| Init            | `initialize(session_id, **kwargs)`                 | yes        |
| Each turn (in)  | `prefetch(query)`, `system_prompt_block()`,        | optional   |
|                 |   `on_turn_start(turn, msg, **kwargs)`             |            |
| Each turn (out) | `sync_turn(user, assistant)`,                      | optional   |
|                 |   `queue_prefetch(query)`                          |            |
| Tool dispatch   | `get_tool_schemas()`, `handle_tool_call()`         | yes if     |
|                 |                                                    | tools      |
| Session switch  | `on_session_switch(new, parent_session_id, reset)` | optional   |
| Compression     | `on_pre_compress(messages) -> str`                 | optional   |
| Session end     | `on_session_end(messages)`                         | optional   |
| Memory writes   | `on_memory_write(action, target, content, meta)`   | optional   |
| Delegations     | `on_delegation(task, result, ...)`                 | optional   |
| Shutdown        | `shutdown()`                                       | optional   |

Hooks declared via `register_hook` (general plugin runtime):

* `pre_tool_call` — observe / veto tool calls (we use it as observer
  via `hermes_wiring.activate_for`).
* `post_tool_call` — observe tool results.
* `on_session_reset`, `on_session_finalize` — session boundaries that
  feed the observer/reflector.

## 7. Plugin hook priority / ordering

Hermes does NOT define a priority system. Hooks fire in registration
order, which is plugin-load order. Our contract:

* Plugins MUST be invariant to load order for any externally observable
  behaviour (this repo's `tests/test_plugin_load_order_permutations.py`
  is the regression).
* If two plugins register `pre_tool_call`, neither is allowed to mutate
  the kwargs object passed in; observers must treat it as read-only.

## 8. Plugin event bus

There is no separate event bus — `invoke_hook` IS the event bus. Hook
names ARE event names. Unknown hook names are stored but warn.

## 9. Plugin command registration

* `register_command(name, handler, description, args_hint)` for slash
  commands.
* The Hermes loader rejects names that match built-in commands
  (`hermes_cli/plugins.py:359-370`). Plugins MUST namespace their
  commands when ambiguity is possible.
* Our plugin currently registers ZERO slash commands.

## 10. Plugin capability registration

Memory provider tools registered via `MemoryProvider.get_tool_schemas`
are routed by `MemoryManager._tool_to_provider`. Tool name conflicts
between providers cause the second registration to be dropped with a
warning (`agent/memory_manager.py:236-244`). Our owned tool names:

* `mastra_recall`
* `mastra_search`
* `mastra_observe`

All are prefixed with `mastra_`, the same string as our plugin name.
This is the *capability namespace ownership invariant*.

## 11. Plugin state ownership

Persistent state owned by this plugin:

* `~/.hermes/<profile>/data/mastra/mastra.json` — config.
* `~/.hermes/<profile>/data/mastra.db` — LibSQL database (Mastra-side).
* `~/.hermes/<profile>/data/mastra/` — runtime state directory (logs,
  pid file, etc.).
* In-memory: `MastraMemoryProvider._client`, `_recall_cache`,
  `_profile`, `_thread`, `_cfg`, `_cron_skipped`. All are *instance*
  attributes — no module-level mutable state outside `async_runner`'s
  daemon thread pool, which is process-wide by design.

## 12. Plugin persistence ownership

* LibSQL DB id namespace: `hermes-mastra` (`server/src/resources.ts:19`).
* Mastra `resourceId` format: `hermes:<profile>` (`server/src/config.ts:32`).
* Working memory scope: `resource` (per-profile, NOT per-thread).
* Observational memory scope: `thread` (per-session, scoped inside
  the resource).
* Artifact IDs: `hermes:<kind>:<profile>` for SOUL/MEMORY/USER/AGENTS
  copies stored in Mastra (`server/src/config.ts:35`).

## 13. Plugin teardown

`MastraMemoryProvider.shutdown()` MUST:

1. Drain the async_runner queue with timeout `SHUTDOWN_TIMEOUT = 5.0 s`.
2. Close the HTTP `client` if non-None.
3. Be idempotent (safe under repeat invocations).

The plugin MUST NOT touch the Bun server process during `shutdown` —
the server outlives the agent process and is reused across sessions.

## 14. Plugin error boundaries

* Provider lifecycle methods MAY raise; `MemoryManager` catches and
  logs (`agent/memory_manager.py:285-457`).
* Hook callbacks registered via `register_hook` MAY raise;
  `invoke_hook` catches and logs (`hermes_cli/plugins.py:1078-1102`).
* `register()` MAY raise; loader catches and records.
* `is_available()` SHOULD NOT raise; if it does, treat as `False`.

## 15. Plugin observability

Logger names follow Python convention: `__name__` derived. Top-level
loggers we own:

* `provider_lifecycle`, `provider_tools`, `recall_cache`,
  `async_runner`, `client`, `server_manager`, `model_config`,
  `mastra_options`, `hermes_wiring`, `engine_install`,
  `agent_observers`, `tool_observers`, `agent_context_engine`,
  `artifact_tools`, `memory_rules`.

When loaded as `~/.hermes/hermes-agent/plugins/memory/mastra/<file>`
the names get the `plugins.memory.mastra.` prefix automatically.

## 16. Compatibility expectations for multiple plugins

* The memory category is exclusive — only one external provider runs.
  We do NOT have to coexist with another memory plugin at runtime.
* We DO have to coexist with non-memory plugins (kanban, achievements,
  observability, image_gen, prompt-enhancer, etc.). Coexistence is
  validated by `tests/test_plugin_non_interference.py`.

## 17. Explicitly unsupported behaviours

A plugin must NOT:

* Mutate another plugin's manifest, hooks, commands, or registered
  state.
* Monkey-patch agent core modules (`run_agent`, `cli`,
  `memory_manager`, `tools.registry`).
* Register hooks for hook names outside `VALID_HOOKS` and rely on them
  firing.
* Block on hot-path lifecycle hooks for more than 100 ms.
* Read another plugin's persistence directory (`<hermes_home>/data/<other>/`).
* Reuse another plugin's namespace prefix (`mastra_`, `honcho_`,
  `mem0_`, etc.).
