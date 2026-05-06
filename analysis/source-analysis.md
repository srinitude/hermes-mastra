# Source Analysis — Hermes Agent + Mastra

> Generated 2026-05-05 as the BOOTSTRAP artifact for the
> `enhanced-mastra-memory-plugin-hermes-agent-prompt.md` execution.
> Every claim below is grounded in either (a) a path under
> `~/.hermes/hermes-agent/` (a current local checkout used as the source of
> truth for Hermes), (b) the Mastra source under
> `/Users/kiren/.opensrc/repos/github.com/mastra-ai/mastra/<version>/`, or
> (c) a file in this repo. Inferences are labelled.

## 1. Hermes Agent — primitives we integrate with

### 1.1 Plugin runtime (`hermes_cli/plugins.py`, ~1,332 LOC)

* **Discovery** — four sources, last-wins on name collision: bundled
  (`hermes-agent/plugins/<name>`), user (`~/.hermes/plugins/<name>`),
  project (`./.hermes/plugins/<name>` — opt-in), pip entry-points group
  `hermes_agent.plugins`.
* **Manifest** — `plugin.yaml` parsed into `PluginManifest`. Required
  fields: `name`, `manifest_version`. Optional: `version`, `description`,
  `author`, `requires_env`, `provides_tools`, `provides_hooks`, `kind`
  (one of `standalone | backend | exclusive | platform`, default
  `standalone`), `key`.
* **`kind: exclusive`** — used by memory and context_engine. The general
  PluginManager **skips** these (`skip_names={"memory","context_engine",
  "platforms"}` at `plugins.py:654`) and a separate registry
  (`plugins/memory/__init__.py`) discovers and selects exactly ONE
  external memory provider via the `memory.provider` config key.
* **`PluginContext`** (the object passed to `register(ctx)`) exposes:
  `register_tool`, `register_hook`, `register_command`,
  `register_cli_command`, `register_context_engine`,
  `register_image_gen_provider`, `register_platform`, `register_skill`,
  `dispatch_tool`, `inject_message`. `register_memory_provider` is
  **NOT** on the general PluginContext — it lives on the memory
  category's own context (`plugins/memory/__init__.py`). Memory plugins
  use it from inside `register(ctx)` because the memory loader passes a
  ctx that includes it.
* **Hook registry** — `VALID_HOOKS` set in `hermes_cli/plugins.py:78`
  contains: `pre_tool_call`, `post_tool_call`,
  `transform_terminal_output`, `transform_tool_result`, `pre_llm_call`,
  `post_llm_call`, `pre_api_request`, `post_api_request`,
  `on_session_start`, `on_session_end`, `on_session_finalize`,
  `on_session_reset`, `subagent_stop`, `pre_gateway_dispatch`,
  `pre_approval_request`, `post_approval_response`. Unknown hook names
  produce a warning but are still stored.
* **`invoke_hook(name, **kwargs)`** at `plugins.py:1055-1163` — executes
  every callback for `name`, collecting non-None returns into a list;
  exceptions in one callback are logged and **never propagate** to other
  callbacks. This is the *plugin-failure-isolation* primitive Hermes
  ships out of the box.

### 1.2 Memory provider contract (`agent/memory_provider.py`, 280 LOC)

* `MemoryProvider` is an ABC. Required: `name`, `is_available`,
  `initialize(session_id, **kwargs)`, `get_tool_schemas`. Optional:
  every other method has a default no-op implementation.
* **Documented `initialize` kwargs** — `hermes_home: str` (always),
  `platform: str` (always), and may include `agent_context`,
  `agent_identity`, `agent_workspace`, `parent_session_id`, `user_id`.
  This is the CONTRACT for profile/tenant isolation.
* `on_session_switch` — called for `/resume`, `/branch`, `/reset`,
  `/new`, gateway equivalents, and context compression. Must update
  cached per-session state in place, not tear the provider down.
* `on_pre_compress` — must return text fed into the compression summary
  prompt (NOT the post-compression history). This is the *durable
  takeaway* extraction point.
* `on_memory_write(action, target, content, metadata)` — fires on
  built-in MEMORY.md / USER.md edits. Metadata signature is detected at
  runtime via `inspect.signature` (see `MemoryManager._provider_memory_write_metadata_mode`)
  for backward-compat; we MUST keep our hook accepting `metadata=None`.

### 1.3 Memory manager (`agent/memory_manager.py`, 557 LOC)

* `add_provider` enforces "exactly one external provider" — second one
  is rejected with a warning (line 215-227). So our plugin and any
  other memory plugin are mutually exclusive at runtime; we don't have
  to defend against simultaneous external providers.
* `prefetch_all`, `sync_all`, `queue_prefetch_all`,
  `on_pre_compress`, `on_session_end`, `on_session_switch`,
  `on_memory_write` all wrap each provider call in `try/except` —
  **failures in one provider can never block others**. Confirmed at
  lines 287-457.
* **Tool name conflict detection** at line 232-244: a second provider
  registering an already-claimed tool name is dropped with a warning.
* `build_memory_context_block` wraps prefetch text in
  `<memory-context>...</memory-context>` fenced block with a system
  note. `StreamingContextScrubber` removes it from streamed assistant
  output to prevent leakage to the UI.

### 1.4 Performance-sensitive paths

| Hook                 | Budget    | Source                                   |
|----------------------|-----------|------------------------------------------|
| `prefetch`           | < 100 ms  | `AGENTS.md` (this repo) "every hot-path hook must return in < 100ms" |
| `sync_turn`          | < 100 ms  | same                                     |
| `on_session_switch`  | < 100 ms  | same                                     |
| `on_pre_compress`    | < 100 ms  | same                                     |
| `on_memory_write`    | < 100 ms  | same                                     |
| `system_prompt_block`| sync, ~ms | called every turn during prompt assembly |
| `initialize`         | < 1 s     | once per session                         |

Verified: every write-side hook in `provider_lifecycle.py` enqueues
work via `_safe_enqueue` (which uses the bounded `AsyncRunner`). The
hot-path budget is held by `tests/test_non_blocking_hooks.py`.

### 1.5 Profile / tenant model

* `hermes_constants.get_hermes_home()` returns the active profile's
  `~/.hermes/<profile>/` directory. Each profile has its own SOUL,
  MEMORY, USER, AGENTS files and now its own `data/mastra.db`.
* The plugin captures `kwargs["hermes_home"]` in `do_initialize`
  (`provider_lifecycle.py:67-69`) so storage decisions honour the
  caller-supplied profile path even when Hermes is invoked across
  profiles in the same process.
* **Resource ID** — `resourceFor(profile)` in `server/src/config.ts`
  returns `hermes:<profile>`. Every Mastra `saveMessages`,
  `recall`, `updateWorkingMemory`, `listThreads` call passes this
  `resourceId`. That is the **tenant-isolation primitive** — Mastra
  itself filters on `resourceId` at the storage layer.

## 2. Mastra — primitives we integrate with

### 2.1 `Memory` class (`@mastra/memory@1.17.5`)

Exported from `packages/memory/src/index.ts`. Constructor accepts
`{ storage, options }` where `options: SharedMemoryConfig` includes
`workingMemory`, `lastMessages`, `semanticRecall`, `observationalMemory`,
`generateTitle`. Methods we call:

* `saveMessages({ messages, memoryConfig })` — persist a batch.
* `recall({ threadId, resourceId, vectorSearchString?, threadConfig })`
  — retrieve `messages[]` and (when `observationalMemory: true`)
  `observations[]`.
* `updateWorkingMemory({ threadId, resourceId, workingMemory,
  memoryConfig })` — set or append working-memory state.
* `getWorkingMemory({ resourceId })` — current working-memory snapshot.
* `getThreadById({ threadId })` / `createThread({ threadId, resourceId,
  title })` — thread lifecycle.
* `listThreads({ filter: { resourceId } })` — enumerate threads in a
  resource (used by `semantic_search`).

### 2.2 Storage (`@mastra/libsql`)

`LibSQLStore({ id, url })` — local SQLite via libsql. The `id` is a
namespace inside the DB; we use `"hermes-mastra"` to keep our tables
under that prefix and free of collisions with other Mastra users
sharing the same file.

### 2.3 Observational memory

* Two-model design: `observation` (high-frequency summarizer, e.g.
  Gemini Flash) and `reflection` (lower-frequency restructurer, e.g.
  Gemini Pro).
* `scope: "thread"` keeps observations per-thread within a resource.
* `temporalMarkers: true` injects "earlier today / last week" hints.
* `shareTokenBudget: false` — observations don't compete with primary
  agent budget. We default to `false` to keep the agent's effective
  context window predictable.

## 3. Performance-sensitive paths in this plugin

| File                        | Critical for                          |
|-----------------------------|---------------------------------------|
| `recall_cache.py`           | sub-100 ms `prefetch`                 |
| `async_runner.py`           | non-blocking write hooks              |
| `client.py`                 | every HTTP round-trip to the Bun side |
| `provider_lifecycle.py`     | every lifecycle hook                  |
| `server/src/routes-memory.ts` | server-side latency on `/recall`    |

## 4. Memory lifecycle (text diagram)

```
            ┌──────────────────────────────────────────────┐
            │  Hermes session start: AIAgent.__init__      │
            └───────────────┬──────────────────────────────┘
                            │ load plugins → memory loader
                            │ MemoryManager.add_provider(MastraMemoryProvider)
                            ▼
            ┌──────────────────────────────────────────────┐
            │  do_initialize(session_id, **kwargs)         │
            │  - capture hermes_home, profile              │
            │  - enqueue _bring_up_server (background)     │
            │  - return synchronously (<1 ms)              │
            └───────────────┬──────────────────────────────┘
                            │ background:
                            │  ensure_running() → http://127.0.0.1:4191
                            │  client.health()
                            │  enqueue_recall → /api/memory/recall
                            ▼
                    ┌─────────────────┐
                    │  RecallCache    │ ← refreshed via async_runner
                    └────────┬────────┘
                             │
turn N user msg ─────────────┴──────────► do_prefetch(query, session_id)
                                          1. if session_id changed: clear cache
                                          2. enqueue background recall
                                          3. RETURN cached snapshot synchronously

turn N assistant msg ────────────────────► do_sync_turn(user, assistant, ...)
                                          → enqueue client.save_turn (POST messages)

session-end / /reset / context-compression
        ──────────────────────────────────► do_session_end / do_session_switch
                                          → enqueue client.flush
                                            client.write_observation (lineage)
```

## 5. Risks and unknowns

* **Plugin-failure isolation** — Hermes' MemoryManager catches
  exceptions per provider call, but we have no tests proving our
  module's *import* failures don't break the loader. Fix: a contract
  test at the Hermes plugin runtime layer.
* **Cross-plugin storage collision** — we own `hermes-mastra` LibSQL
  namespace and `mastra:*` env vars; an unknown plugin reusing those
  prefixes would collide. Fix: documented namespace ownership +
  collision regression test.
* **Hook registration ordering** — `register_hook` does not enforce
  priority; the order plugins load determines hook execution order. If
  another plugin registers `post_tool_call` and mutates the call args
  before us, our observers see the mutated version. Fix: assert
  observable behaviour is invariant under load-order permutations.
* **`get_tool_schemas` collision** — MemoryManager logs a warning and
  drops conflicting tool names but does not raise. A namespaced prefix
  (we already use `mastra_*`) protects us, but we lack a test that
  proves no other category of plugin ever expects a `mastra_*` tool.

## 6. Disconfirming evidence

* The Hermes plugin runtime **already isolates plugin failures** via
  per-callback try/except in `invoke_hook`. So claims that "plugin A
  can take down plugin B" need to be qualified — we are testing the
  contract, not a current bug.
* `MemoryManager` **already enforces "one external provider"**. We
  cannot meaningfully test "two memory plugins loaded at once" because
  the second is rejected. Our compatibility matrix records this.
* Hermes' `register_command` already rejects collisions with built-in
  slash commands (`plugins.py:359-370`). Our plugin currently registers
  zero slash commands — we own zero command namespace risk.
* Many "potential" issues (logger collisions, env-var collisions) are
  trivially resolved by stable prefixes. The real risk is silent
  *behavioural* coupling, e.g. another plugin mutating tool args
  in-place.


## 7. 2026-05-06 resilience/performance execution source reality

### 7.1 Hermes plugin contract via opensrc

`opensrc --version` reported `opensrc 0.7.2`; `opensrc path NousResearch/hermes-agent` resolved to `/Users/kiren/.opensrc/repos/github.com/NousResearch/hermes-agent/main`. The inventory matched the goal contract: `agent/memory_provider.py` is 280 lines, `agent/memory_manager.py` is 557 lines, and `hermes_cli/plugins.py` exposes `PluginContext`, `register_hook`, `_load_plugin`, and `invoke_hook`. The observed `MemoryProvider` hook surface is: `name`, `is_available`, `initialize`, `system_prompt_block`, `prefetch`, `queue_prefetch`, `sync_turn`, `get_tool_schemas`, `handle_tool_call`, `shutdown`, `on_turn_start`, `on_session_end`, `on_session_switch`, `on_pre_compress`, `on_delegation`, `get_config_schema`, `save_config`, and `on_memory_write`. No Hermes core files were edited.

### 7.2 Mastra Memory and LibSQL source reality

`opensrc path mastra-ai/mastra` resolved to `/Users/kiren/.opensrc/repos/github.com/mastra-ai/mastra/main`; `opensrc path tursodatabase/libsql-client-ts` resolved to `/Users/kiren/.opensrc/repos/github.com/tursodatabase/libsql-client-ts/main`. `packages/memory/src/index.ts` exports `Memory` and contains `recall`, `listThreads`, `deleteThread`, `updateWorkingMemory`, `saveMessages`, and `getWorkingMemory`; the libSQL memory and prompt-block domains exist under `stores/libsql/src/storage/domains/`. The observed package versions were `@mastra/memory` `1.15.1-alpha.0` and `@libsql/client` `0.17.3`.

### 7.3 Baseline resilience surface and gaps

Existing coverage includes plugin failure isolation for provider/hook callbacks (`tests/test_plugin_failure_isolation.py`) and non-blocking budgets for `is_available`, `system_prompt_block`, `prefetch`, `queue_prefetch`, `sync_turn`, `on_pre_compress`, `on_session_switch`, `on_memory_write`, `on_delegation`, `get_tool_schemas`, and `on_session_end` (`tests/test_non_blocking_hooks.py`). `async_runner.py` already uses a bounded queue with drop-oldest overflow and a `dropped` counter; `recall_cache.py` is thread-safe but pre-goal state was single-snapshot rather than per `(profile, thread)` LRU; `provider_lifecycle.py` already enqueues write-side work off the hot path and clears cache on session/profile changes.

Uncovered gaps before RED: circuit breaker, server supervisor restart policy, observation deduplication, response-shape validation, profile-flip leakage under concurrent recall, filesystem failure no-op behavior, malformed/oversized responses, auth-token rotation, partial-init no-op recovery, lineage prefetch from parent session, smarter capacity hint routing, and queue-saturation burst logging.

### 7.4 Bootstrap baseline evidence

`mise run setup`, `mise run install`, and `.venv/bin/python -m pytest --collect-only -q` completed; collect-only reported 560 tests before new RED files. The first `mise run quality` exposed a stale active Hermes plugin directory at `~/.hermes/hermes-agent/plugins/memory/mastra` containing only `server/`; `mise run sync` restored the active plugin copy and the loader smoke then passed. The rerun `mise run quality` passed with 554 passed and 6 upstream-compat skips caused by a transient GitHub API rate-limit in opensrc fetch. `mise run bench` wrote the performance floor to `references/last-benchmark.json` with hot-path p99 under 0.05 ms under the 500 ms slow-client injection.

### 7.5 Firecrawl availability note

`FIRECRAWL_NO_TELEMETRY=1 firecrawl --status` exited 0 with CLI version `1.16.0` but reported `Not authenticated`, and `FIRECRAWL_API_KEY` was absent from the execution environment. Cached maps under `analysis/research/url-maps/` were present and fresh for this goal run (`mastra=204`, `hermes=317`, `bun=317`, `hono=84`, `libsql=253`, `mise=219` links). No live Firecrawl scrape or map refresh was claimed during execution; the cached artifacts remain the evidence source until credentials are supplied.
