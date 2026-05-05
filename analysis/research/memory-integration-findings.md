# Memory Integration Findings

## Current integration shape

The plugin sits on the Hermes side as `MastraMemoryProvider`
(`MemoryProvider`-ABC subclass) and on the Mastra side as a Bun + Hono
HTTP server backed by `@mastra/memory` + `@mastra/libsql`. The two
sides communicate over `127.0.0.1:4191` exclusively over plain JSON.
Everything Hermes-facing is in Python; everything Mastra-facing is
TypeScript. The boundary is exactly the HTTP layer.

## Why the boundary is HTTP, not in-process

Mastra is a TypeScript runtime. Hermes is Python. Spawning a Bun
subprocess that owns Mastra is the simplest way to keep both
ecosystems on `latest` without forcing one to embed the other. The
HTTP boundary also keeps the Bun process *outliving* the Hermes
process — useful for cron jobs and gateway sessions where multiple
Hermes processes share the same memory store.

## Where Hermes contracts force structure

* `MemoryProvider.is_available` MUST not do network — we only check
  config-on-disk + bun-on-PATH (`__init__.py:56-66`).
* `initialize` receives `hermes_home` — we capture it for storage
  decisions (`provider_lifecycle.py:67-69`).
* Hot-path hooks (`prefetch`, `sync_turn`, `on_session_switch`,
  `on_pre_compress`, `on_session_end`, `on_memory_write`,
  `on_delegation`) MUST return in < 100 ms — we implement them by
  enqueuing onto `async_runner` and reading from `RecallCache`
  (`provider_lifecycle.py:95-203`).
* `system_prompt_block` is called every turn — we keep it pure-data
  with a small capacity hint and three tool-recall instructions
  (`__init__.py:107-148`).

## Where Mastra contracts force structure

* `Memory.recall({resourceId})` filters at the DB layer — we always
  pass `resourceId = "hermes:<profile>"` (`server/src/config.ts:32`).
* `LibSQLStore({id, url})` namespaces all tables — we use
  `id="hermes-mastra"` (`server/src/resources.ts:19`).
* Working memory `scope:"resource"` makes user facts span sessions
  *inside* a profile (`server/src/resources.ts:43`).
* Observational memory `scope:"thread"` keeps session observations
  contained (`server/src/resources.ts:51`).
* Observer + Reflector are decoupled — high-frequency summary +
  low-frequency restructure (`server/src/resources.ts:21-31`).

## Where Hermes and Mastra disagree

* **Session ID rotation.** Hermes treats `session_id` as a
  rotation-friendly handle (`/branch`, compression, `/resume`).
  Mastra treats `threadId` as immutable inside a resource. We
  resolve this by mapping each new `session_id` to a *new*
  `threadId` and writing a "Session continues from prior thread …"
  observation when lineage is meaningful (`provider_lifecycle.py:189-203`).
* **Tenant model.** Hermes models tenants implicitly via profile
  paths; Mastra models them explicitly via `resourceId`. We map
  profile → resourceId 1:1 (`server/src/config.ts:32`).
* **Tool surface.** Mastra ships `recallTool` + `updateWorkingMemoryTool`
  inside `@mastra/memory`; Hermes wants tool schemas in OpenAI function-calling
  shape via `MemoryProvider.get_tool_schemas`. We expose three
  Hermes-side tools (`mastra_recall`, `mastra_search`,
  `mastra_observe`) that proxy to the appropriate Mastra-side
  endpoints (`provider_tools.py`).

## Findings that improve perceived speed

1. **Cached prefetch** is already in place (`recall_cache.py`) and
   serves synchronous reads. No change required.
2. **Background bring-up** is already in place
   (`do_initialize → _enqueue(_bring_up_server)`). No change
   required.
3. **Tool schema exposure is dynamic** — when `_cron_skipped` we
   return `[]`, sparing the model the schema bloat. Already in
   place.

## Findings that improve correctness

1. **Profile-switch resilience** is in place via `do_turn_start`
   synthesising the missing Hermes hook.
2. **`hermes_home` propagation** is verified by
   `tests/test_hermes_init_contract.py`.
3. The `on_memory_write` `metadata` runtime detection in Hermes'
   MemoryManager (`agent/memory_manager.py:459-484`) means we MUST
   keep our hook accepting `metadata=None` — already done.

## Findings that improve plugin correctness / non-interference

1. We need explicit regression tests proving:
   * No mutation of kwargs passed to hooks.
   * No monkey-patching of agent core modules.
   * No collision on env-var, tool-name, logger, port.
   * Stable behaviour under valid plugin load-order permutations.
   * Failure isolation in both directions (we fail safely; others'
     failures don't break us).
2. These tests do NOT require fixing real bugs; they enforce contract
   stability against future regressions.

## Confidence

| Conclusion                                              | Confidence |
|---------------------------------------------------------|------------|
| Hot-path budget held by current implementation          | high       |
| Tenant isolation enforced at DB layer                   | high       |
| Session lineage preserved across switches               | high       |
| Plugin namespace ownership covers all known resources   | high       |
| No collision with bundled Hermes plugins                | high       |
| Failure isolation across plugins                        | high (Hermes-enforced) |
| Performance under concurrent sessions                   | medium (one bench run, single profile) |
| Behaviour with unknown contract-valid plugin            | medium (test plugins simulate, not real) |
