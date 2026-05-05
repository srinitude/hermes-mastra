# Plugin Clash Analysis — `mastra` vs other Hermes plugins

This is the resource-by-resource collision matrix for the Mastra
Observational Memory plugin. Every resource the plugin can register,
read, write, or own appears once with explicit ownership, namespacing,
and the regression test that locks it.

## Method

1. Source-walked the plugin (`__init__.py`, `provider_lifecycle.py`,
   `provider_tools.py`, `tool_schemas.py`, `tool_observers.py`,
   `agent_observers.py`, `hermes_wiring.py`, `engine_install.py`,
   `memory_rules.py`, `server/src/`, `mastra_options.py`,
   `model_config.py`, `model_presets.py`, `provider_lifecycle.py`,
   `client.py`, `server_manager.py`, `cli_commands.py`,
   `cli.py`, `memory_rules.py`, `artifact_tools.py`).
2. Source-walked Hermes plugin runtime (`hermes_cli/plugins.py`,
   `agent/memory_manager.py`, `agent/memory_provider.py`).
3. For each plugin-touched resource, recorded: type, owner,
   namespace, collision-risk classification, conflict prevention
   strategy, regression test.

## Resource matrix

```yaml
- resource: plugin_id
  type: identity
  owner: this plugin
  namespace: "mastra"
  collision_risk: none
  possible_conflict_with: any plugin claiming the same name
  conflict_prevention_strategy: directory-scoped registration; loader rejects duplicates
  test_coverage: tests/test_plugin_clash.py::test_canonical_plugin_id_stable
  remaining_risk: none

- resource: memory_provider_name
  type: capability
  owner: this plugin
  namespace: "mastra"
  collision_risk: none
  possible_conflict_with: another memory.MemoryProvider implementation
  conflict_prevention_strategy: MemoryManager rejects a 2nd external provider
  test_coverage: tests/test_plugin_clash.py::test_provider_name_is_mastra
  remaining_risk: none — Hermes enforces single-external-provider

- resource: tool_names
  type: capability
  owner: this plugin
  namespace: "mastra_*"  (mastra_recall, mastra_search, mastra_observe)
  collision_risk: low
  possible_conflict_with: future plugins that register mastra_ tools
  conflict_prevention_strategy: every tool name is prefixed; MemoryManager
    drops conflicting registrations with a warning
  test_coverage: tests/test_plugin_clash.py::test_all_tool_names_are_namespaced
  remaining_risk: none — namespace ownership documented

- resource: hook_callbacks
  type: lifecycle
  owner: this plugin
  namespace: bound to this provider via hermes_wiring.activate_for
  hooks_registered: [pre_tool_call, post_tool_call, on_session_reset, on_session_finalize]
  collision_risk: none (Hermes invokes ALL callbacks per hook; we don't
    veto / mutate, we observe)
  possible_conflict_with: other plugins registering same hooks
  conflict_prevention_strategy: read-only observers; never mutate kwargs
  test_coverage: tests/test_plugin_clash.py::test_hook_callbacks_are_observers_only
  remaining_risk: a future plugin that does mutate kwargs — our test
    asserts WE don't, can't speak for others

- resource: cli_commands
  type: capability
  owner: this plugin
  namespace: not used (we register zero CLI subcommands)
  collision_risk: none
  test_coverage: tests/test_plugin_clash.py::test_no_cli_command_registration
  remaining_risk: none

- resource: slash_commands
  type: capability
  owner: this plugin
  namespace: not used
  collision_risk: none
  test_coverage: tests/test_plugin_clash.py::test_no_slash_command_registration
  remaining_risk: none

- resource: env_vars
  type: configuration
  owner: this plugin
  namespace: "MASTRA_*" + reuses VENICE_API_KEY
  vars_owned: [MASTRA_PORT, MASTRA_HOST, MASTRA_DB_URL, MASTRA_API_KEY,
               MASTRA_MODEL_URL, MASTRA_MODEL_NAME, MASTRA_MODEL_API_KEY,
               MASTRA_OBSERVER_URL, MASTRA_OBSERVER_NAME, MASTRA_OBSERVER_API_KEY,
               MASTRA_REFLECTOR_URL, MASTRA_REFLECTOR_NAME, MASTRA_REFLECTOR_API_KEY,
               MASTRA_TEMPORAL, MASTRA_SHARE_BUDGET, MASTRA_RECALL_TOP_K,
               MASTRA_PROXY_NAME]
  vars_consumed_shared: [VENICE_API_KEY]  # documented in plugin.yaml
  collision_risk: low
  possible_conflict_with: any plugin reading MASTRA_*
  conflict_prevention_strategy: stable prefix; all reads in server/src/config.ts
    or model_config.py; no writes in normal flow
  test_coverage: tests/test_plugin_clash.py::test_env_var_namespace_ownership
  remaining_risk: none

- resource: storage_database
  type: persistence
  owner: this plugin
  namespace: hermes-mastra (LibSQL store id)
  path: <hermes_home>/data/mastra.db
  collision_risk: none
  possible_conflict_with: another plugin sharing the same DB file
  conflict_prevention_strategy: profile-scoped path; LibSQL store id
    "hermes-mastra"; resourceId prefix "hermes:<profile>"
  test_coverage: tests/test_plugin_clash.py::test_storage_namespace_is_hermes_mastra
  remaining_risk: none

- resource: mastra_resource_ids
  type: persistence
  owner: this plugin
  namespace: "hermes:<profile>" (resourceFor() in server/src/config.ts)
  collision_risk: none
  possible_conflict_with: any other Mastra user sharing the DB
  conflict_prevention_strategy: every saveMessages/recall/updateWorkingMemory
    is parameterised by resourceId; tests prove leakage between profiles
    is impossible
  test_coverage: tests/test_profile_switch.py + tests/test_plugin_clash.py
  remaining_risk: none

- resource: mastra_thread_ids
  type: persistence
  owner: this plugin
  namespace: arbitrary (Hermes session_id) — scoped inside resourceId
  collision_risk: none
  test_coverage: tests/test_profile_switch.py
  remaining_risk: none

- resource: artifact_ids
  type: persistence
  owner: this plugin
  namespace: "hermes:<kind>:<profile>" where kind in {soul,memory,user,agents}
  collision_risk: none
  test_coverage: tests/test_artifacts.py
  remaining_risk: none

- resource: working_memory_ids
  type: persistence
  owner: this plugin
  namespace: scope=resource (one per profile)
  collision_risk: none
  test_coverage: tests/test_profile_switch.py
  remaining_risk: none

- resource: cache_keys
  type: in-process state
  owner: this plugin
  namespace: instance-scoped on MastraMemoryProvider._recall_cache
  collision_risk: none
  test_coverage: tests/test_plugin_clash.py::test_recall_cache_is_instance_scoped
  remaining_risk: none

- resource: async_runner_singleton
  type: in-process state
  owner: this plugin
  namespace: process-wide (mastra-runner-N daemon threads)
  collision_risk: none — daemon threads named "mastra-runner-*"
  test_coverage: tests/test_plugin_clash.py::test_async_runner_thread_names_namespaced
  remaining_risk: low — if another plugin imports async_runner directly,
    they'd share our pool. Mitigation: not exported from a stable name.

- resource: bun_http_server
  type: out-of-process service
  owner: this plugin
  port: 4191 default; configurable via MASTRA_PORT
  collision_risk: low
  possible_conflict_with: anything else binding 4191 (rare)
  conflict_prevention_strategy: configurable port; localhost-only;
    server_manager.find_running_pid handles already-running case
  test_coverage: tests/test_server_env.py
  remaining_risk: another plugin reusing the configured port —
    documented in README

- resource: log_loggers
  type: observability
  owner: this plugin
  namespace: module-name derived (under "plugins.memory.mastra." once loaded)
  collision_risk: none
  test_coverage: tests/test_plugin_clash.py::test_logger_names_are_module_scoped
  remaining_risk: none

- resource: metrics
  type: observability
  owner: this plugin
  namespace: not currently emitted; future "mastra.*" prefix
  collision_risk: none (zero-cost: nothing emitted)
  test_coverage: n/a until metrics added
  remaining_risk: none

- resource: traces / spans
  type: observability
  owner: this plugin
  namespace: not currently emitted
  collision_risk: none
  test_coverage: n/a until tracing added
  remaining_risk: none

- resource: skill_registrations
  type: capability
  owner: this plugin
  namespace: "mastra:" (qualified by Hermes plugin runtime)
  collision_risk: none — Hermes auto-namespaces with plugin name
  test_coverage: tests/test_plugin_clash.py::test_no_skill_registration
  remaining_risk: none

- resource: context_engine_registration
  type: capability
  owner: this plugin
  namespace: name="mastra_aware" (engine_install.py)
  collision_risk: low — Hermes allows ONE context engine plugin
  conflict_prevention_strategy: register_context_engine warns + drops on 2nd
  test_coverage: tests/test_context_engine_register.py
  remaining_risk: none — Hermes runtime enforces

- resource: image_gen_provider_registration
  type: capability
  owner: this plugin
  namespace: not used
  collision_risk: none
  test_coverage: tests/test_plugin_clash.py::test_no_image_gen_registration
  remaining_risk: none

- resource: platform_registration
  type: capability
  owner: this plugin
  namespace: not used
  collision_risk: none
  test_coverage: tests/test_plugin_clash.py::test_no_platform_registration
  remaining_risk: none

- resource: process_environment_mutation
  type: side-effect
  owner: this plugin
  scope: os.environ["HERMES_HOME"] — set in _bring_up_server when override
    supplied via initialize kwargs
  collision_risk: medium — process-wide
  conflict_prevention_strategy: only applied when caller-supplied; never
    overwrites unrelated keys
  test_coverage: tests/test_plugin_clash.py::test_environment_mutation_scope
  remaining_risk: another plugin reading HERMES_HOME after our override
    sees the override, which is correct — it's HERMES' own profile path

- resource: monkey_patches
  type: side-effect
  owner: this plugin
  scope: NONE
  collision_risk: none
  conflict_prevention_strategy: zero monkey-patching policy
  test_coverage: tests/test_plugin_clash.py::test_no_monkey_patching
  remaining_risk: none
```

## Risk summary

| Risk level | Count |
|------------|-------|
| `none`     | 19    |
| `low`      | 4     |
| `medium`   | 1     |
| `high`     | 0     |

The single `medium`-risk resource is process-wide environment mutation
(`HERMES_HOME`), which is intentional and contractual: Hermes' own
profile contract documents passing `hermes_home` in init kwargs and
the plugin merely propagates it. Tests assert the override is gated
on caller intent and never overwrites unrelated keys.
