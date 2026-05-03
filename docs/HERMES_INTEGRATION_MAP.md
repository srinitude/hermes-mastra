# Hermes-led integration map

> **Premise.** Mastra is a *backend* for memory primitives. Hermes is the
> agent loop that owns timing, prompt assembly, and tool dispatch. Every
> integration decision in this plugin is made from Hermes' point of view.
> If a Mastra primitive can't be made cheap enough for Hermes' hot path,
> we don't expose it on that hot path — we expose it as a tool the agent
> calls deliberately.

This document is the contract. When a future change tempts you to add
"just one more synchronous call" to a hook, re-read the budget column and
check the failure-mode column. If you can't satisfy both, route the call
to `async_runner` and serve from cache.

---

## 1. Latency budgets per hook (Hermes' POV)

| Hermes hook | Caller | Hermes' main thread? | Budget | Failure mode | Mastra primitive used |
|-------------|--------|---------------------|--------|--------------|----------------------|
| `is_available()` | agent init | yes | **5 ms** | return False, plugin disables itself | local fs probe (`find_bun`, `load_config`) |
| `initialize(session_id, **kw)` | agent init | yes | **20 ms** | log + run as no-op | enqueue Bun bring-up; do nothing inline |
| `system_prompt_block()` | system-prompt assembly | yes (cached) | **0 ms** | empty string | none — pure local string |
| `prefetch(query, *, session_id)` | every API call | yes | **2 ms** | return last cache snapshot | `RecallCache.get()` (in-memory dict) |
| `queue_prefetch(query, *, session_id)` | after every turn | yes | **2 ms** | drop the request | `async_runner.submit` → `client.recall` |
| `sync_turn(user, asst, *, session_id)` | after every turn | yes | **2 ms** | drop the turn | `async_runner.submit` → `POST /messages` |
| `on_pre_compress(messages)` | once per compaction | yes | **20 ms** | empty string + enqueue flush | cached observations (Mastra) |
| `on_session_switch(...)` | `/new`, `/branch`, `/resume`, compress | yes | **2 ms** | drop | clear local cache + enqueue background re-init |
| `on_session_end(messages)` | real session boundary | yes | **50 ms** | best-effort flush | enqueue `POST /flush` |
| `on_memory_write(action, target, content)` | every `memory` tool call | yes | **2 ms** | drop | enqueue `POST /working_memory` |
| `on_delegation(task, result, ...)` | parent agent | yes | **2 ms** | drop | enqueue `POST /observation` |
| `get_tool_schemas()` | tool registry assembly | yes (cached) | **0 ms** | `[]` | static dict |
| `handle_tool_call(name, args)` | when agent calls our tool | yes | **per-tool budget** | tool error JSON | direct httpx (this is the *only* hot-path Mastra HTTP) |
| `shutdown()` | process exit | yes | **200 ms** | force-close | drain queue + close httpx pool |

> Every hook above is verified by `tests/test_non_blocking_hooks.py`. If a
> change makes one of them slower than its budget, the test fails.

The single exception is **`handle_tool_call`** — when the agent voluntarily
calls `mastra_recall`, `mastra_search`, or `mastra_observe`, it
*expects* network I/O and accepts the latency in exchange for fresh
results. That's a deliberate, model-driven decision; the hot path it
isn't.

---

## 2. Hermes hook → Mastra primitive routing

This is the per-primitive map. **The Mastra primitive is the verb; the
Hermes hook is the trigger that fires it.** When a Mastra docs page lists
a primitive that has *no Hermes trigger*, we don't ship it — Hermes is
the boss.

### 2.1 Observational memory (`@mastra/memory` Observer + Reflector)

| Hermes trigger | Mastra primitive | Why this and not something else |
|----------------|------------------|---------------------------------|
| `prefetch()` | `memory.recall({observationalMemory: true})` via cache | Observer's dense log is the most context-efficient surface for inline injection |
| `on_pre_compress()` | inject cached observations as protected system message | Hermes' compressor protects head messages — the observations ride through |
| `on_session_end()` | `POST /flush` | Forces Observer to drain before the session record closes |
| `on_session_switch(reset=True)` | clear cache, no flush | New conversation = empty slate |

### 2.2 Working memory (`@mastra/memory` workingMemory, scope: resource)

| Hermes trigger | Mastra primitive | Why this and not something else |
|----------------|------------------|---------------------------------|
| `on_memory_write(action, target='memory'\|'user', content)` | `POST /working_memory` (mirror) | MEMORY.md / USER.md is Hermes' authoritative store; Mastra is a mirror, not a competing source of truth |
| `system_prompt_block()` | none | Hermes already injects MEMORY.md at layer 5 of prompt assembly — duplicating it would burn cache and tokens for zero new info |

> **Design choice.** We do **not** read working memory back into Hermes'
> system prompt. Hermes' `BuiltinMemoryProvider` already owns that slot.
> The Mastra side exists only so that other Mastra-aware processes
> (Studio, future Mastra agents) see Hermes' edits.

> **Built-in file format.** `MEMORY.md` and `USER.md` use a single line
> containing only `§` (U+00A7, the section sign) as the entry
> delimiter. The plugin's `memory_rules.py` defines
> `SECTION_SEPARATOR = "\n§\n"` and relies on it to install / uninstall
> the canonical `[mastra-rule]` anchor without disturbing other
> entries. The mirror endpoint stores Hermes' raw markdown text as-is —
> the `§` boundaries are preserved in the working-memory document so
> reads via `mastra_working_memory` round-trip cleanly.

### 2.3 Semantic recall (`@mastra/memory` semanticRecall + vector store)

| Hermes trigger | Mastra primitive | Why this and not something else |
|----------------|------------------|---------------------------------|
| `mastra_search` tool call | `/api/memory/search` (substring match) | Cheap, always-available; default for "find observations matching X" |
| `mastra_semantic_search` tool call | `memory.recall({vectorSearchString})` | Vector search by **meaning** — agent uses when keyword would miss synonyms / paraphrases |
| `prefetch()` | **not used** | At ~50 ms for a libSQL vector query, this would blow the 2 ms budget |

> The Mastra `semanticRecall` flag stays *off* in `Memory` config so it
> doesn't auto-fire on every save. We route both keyword and semantic
> paths through model-driven tools so Hermes' agent loop owns when to
> pay the latency, and the model picks the right tool by reading the
> schema descriptions.

### 2.4 Working memory READ-back (model-driven inspection)

| Hermes trigger | Mastra primitive | Why this and not something else |
|----------------|------------------|---------------------------------|
| `mastra_working_memory` tool call | `memory.getWorkingMemory({resourceId})` | Available on demand when the agent wants to inspect what was mirrored |
| `system_prompt_block()` | none | Hermes already injects MEMORY.md/USER.md at layer 5 — duplication burns cache and tokens |

> Built-in MEMORY.md / USER.md remains the canonical store. The tool
> description tells the model: "this is a mirror, prefer the system-
> prompt blocks for routine recall". Used only when divergence
> investigation is warranted.

### 2.5 Message history (`@mastra/memory` messageHistory + LibSQLStore)

| Hermes trigger | Mastra primitive | Why this and not something else |
|----------------|------------------|---------------------------------|
| `sync_turn()` | `POST /messages` (background) | Hermes already persists the canonical transcript to `~/.hermes/state.db` — Mastra's copy is the *substrate* the Observer reads from |
| `mastra_recall` tool | `memory.recall({lastMessages})` | Available to the model; not on hot path |
| `session_search` tool | **bypass Mastra** | Hermes' FTS5 over `state.db` is already optimal for transcript search; layering Mastra would only add latency |

### 2.5 Memory processors (`@mastra/memory` processors)

The Mastra side runs `MessageHistory`, `WorkingMemory`, `SemanticRecall`
as input/output processors. **We do not surface them on Hermes' side.**
Hermes has its own equivalent layers (prompt assembly + context engine
+ tools registry). Layering Mastra processors on top of Hermes' would
duplicate work and break Anthropic prompt-cache hashing.

### 2.6 Threads & resources

| Mastra concept | Hermes mapping | Notes |
|----------------|----------------|-------|
| `resourceId` | `hermes:<profile>` | Profile = user-visible Hermes profile name. Provides cross-thread persistence per user. |
| `threadId` | Hermes `session_id` | 1:1 mapping. Lineage via `parent_session_id` works because Mastra threads are flat. |
| `metadata.title` | first 12 chars of session_id | Stable, deterministic. |

### 2.7 Artifacts (`@mastra/memory` storage `prompt-blocks` domain)

The plugin treats Hermes' file-system identity stores — `SOUL.md`,
`MEMORY.md`, `USER.md`, and per-project `AGENTS.md` snapshots — as
**versioned Mastra prompt-blocks**.  This is the
[`PromptBlocksStorage` domain](https://github.com/mastra-ai/mastra/blob/main/packages/core/src/storage/domains/prompt-blocks/base.ts)
already exposed by `LibSQLStore`; we don't invent a custom table.

| Mastra concept | Hermes mapping | Notes |
|----------------|----------------|-------|
| prompt-block `id` | `hermes:<kind>:<profile>` | `kind ∈ {soul, memory, user, agents}`; profile defaults to `default`. AGENTS.md snapshots key on `sha256(absolute_path)` instead of profile so each repo gets its own row. |
| prompt-block `metadata.hermes` | `{kind, profile, path}` | Round-trip information so a future write-back knows which file to refresh. |
| `versionNumber` | Edit history | Every `update` bumps the version automatically. Reverts append a NEW version with the old content — no rewinds. |
| `activeVersionNumber` | The version Hermes' system prompt sees | What the file-cache writes back to disk. |

**Source-of-truth direction.** Mastra is canonical; the on-disk file is
a *cache*.

* **Read path:** Hermes' system prompt assembly reads the file from disk
  as it always has. The file always exists with the latest content
  because the plugin keeps it fresh atomically (temp + `os.replace`).
  This means **the system prompt keeps working when the Bun server is
  unreachable** — the non-blocking contract from §1 still holds.
* **Write path:** `on_memory_write` (and the `mastra_artifact_revert`
  tool) enqueue an `upsert_artifact` to the prompt-blocks store via
  `async_runner` (off the hot path), and on success refresh the file
  cache via `artifacts.write_file_cache`. The hook itself returns inside
  its 50 ms budget.
* **Seed path:** On first activation per profile, `seed_artifacts_from_files`
  uploads the existing on-disk content as version 1 of each block.
  Idempotent: if the block already exists, the server's prompt-blocks
  domain detects content equality and skips the version bump.

> **Why prompt-blocks and not custom tables?** They're a sanctioned,
> versioned, schema-validated storage domain in `@mastra/core` — exactly
> the primitive we need. Inventing custom tables would bypass Mastra's
> migration story, lose version history, and force us to maintain a
> parallel schema. Hermes-led design: lean on the framework when it
> already has the answer.

> **Why AGENTS.md is a snapshot, not a managed file.** Hermes loads
> `AGENTS.md` from the working directory, and there are N of them, one
> per repo (Hermes recently *removed* the recursive walk in PR #3110).
> The plugin observes them via `do_context_files_loaded` — when Hermes
> tells us an AGENTS.md was loaded, we upsert a snapshot keyed on the
> file's path hash. The agent can read individual snapshots via
> `mastra_artifact_get kind=agents` and browse history via
> `mastra_artifact_history kind=agents`, but we don't write back to
> the file (it's the user's project, not ours).

### 2.8 What we explicitly do NOT integrate

- **Mastra agents (`Agent`)** — we already have one (Hermes); spawning a Mastra `Agent` per turn would add startup tax and an extra LLM call.
- **Mastra workflows (`createWorkflow`)** — Hermes has its own loop; a workflow on top is a duplicate orchestrator.
- **Mastra storage adapters other than libSQL** — libSQL covers single-user local; multi-user Postgres can be a future flag, but it's not needed now.
- **Mastra tools API (`createTool`)** — Hermes has its own `tools/registry.py`. We register schemas via `MemoryProvider.get_tool_schemas()` and let Hermes dispatch.
- **Mastra eval scorers** — orthogonal to memory; out of scope for this plugin.
- **Mastra Studio** — UI, not a runtime integration. Users can point Studio at the same `mastra.db` separately.

---

## 3. Optimizations per Hermes layer

These are the wins that fall out of Hermes' actual architecture, in the
order the agent loop visits them.

### 3.1 Prompt assembly (cached system prompt — layers 1-10)

* **Constant text only.** `system_prompt_block()` returns a string that
  never changes within a session. Profile name, thread ID, recall-tool
  hints — all stable. This keeps Anthropic prompt-cache breakpoints
  intact and saves roughly 95% of tokens on every turn.
* **No `_capacity_hint()` drift.** The "MEMORY.md is 50% full" suggestion
  is computed against locally-cached values that the `on_memory_write`
  observer updates *after* the turn ends — never mid-turn. So the system
  prompt stays bytewise-identical between turns when nothing changed.

### 3.2 Pre-API-call (prefetch)

* **Cache-only reads.** `prefetch` reads the last-known observation block
  from `RecallCache` (a `threading.Lock`-guarded string) and never
  performs HTTP. Worst case: empty string, model proceeds without recall
  — same UX as if the plugin weren't installed.
* **Background refresh is coalesced.** Multiple prefetch calls in the
  same turn dedupe via `RecallCache._in_flight`. The Bun server sees
  exactly one recall request per turn, regardless of how many
  retries Hermes does internally.
* **Token-aware top_k boost** (`MastraContextEngine`). When prompt
  tokens cross 60% of the compressor's threshold, `recall_top_k` bumps
  to 8 so the next prefetch returns denser context — and resets when
  pressure clears. The decision lives in the engine because only the
  engine sees token usage; the provider has no token state.

### 3.3 Post-API-call (sync_turn + queue_prefetch)

* **Both fire-and-forget.** `sync_turn` enqueues a single `POST /messages`
  payload onto `async_runner` and returns. `queue_prefetch` schedules a
  recall refresh, also via `async_runner`. Bun does Observer/Reflector
  work in its own process — Hermes never waits.
* **Bounded queue.** `async_runner` is a single-thread executor with
  `MAX_QUEUE_DEPTH` (default 64) and drop-oldest semantics. A
  60-second Mastra outage doesn't grow Hermes' RSS unboundedly.

### 3.4 Compression (`on_pre_compress`)

* **Synchronous injection lives in the engine, not the provider.** The
  provider's `on_pre_compress` return is *discarded* by Hermes' compressor
  (this is documented in the Hermes source). So we put the recall block
  on the **message list** via `MastraContextEngine.compress` instead —
  Hermes' compressor protects head/tail messages and the observation
  block lands inside the protected zone, surviving compression.
* **Synchronous read, but only against cache.** No HTTP. If the cache
  is empty, the engine skips injection rather than blocking on a recall.
* **Failure-isolated.** A broken Bun server raises in the fetch
  callable; the engine swallows it and the underlying compressor still
  runs. Compression never fails because of Mastra.

### 3.5 Tools registry (`get_tool_schemas`, `handle_tool_call`)

* **Three tools, one schema each, no dynamic generation.** Schemas are
  static dicts; no I/O at registry-assembly time. Cache breakpoint after
  the schema list is unaffected by Mastra's state.
* **Idempotent dispatch.** `handle_tool_call` is the only hot-path
  Mastra HTTP. Each call is short (single recall / observe / search).
  No retries inside the plugin — Hermes' tool loop handles that.

### 3.6 Session lifecycle

* **`/new` and `/reset` clear the cache.** Without this, the new session
  would briefly see the previous session's observations until the first
  background refresh lands. Cleared synchronously; refresh enqueued.
* **`/branch` keeps the cache.** Branch lineage continues the
  conversation, so the previous observations remain valid until
  Mastra's Reflector decides otherwise on the next turn.
* **Real session-end flushes.** `on_session_end` enqueues `POST /flush`
  so the Observer drains its buffer before the Bun server idles.
  We don't wait for the response — Hermes' shutdown timeout caps it.

### 3.7 Process exit (`shutdown`)

* **Bounded drain.** `async_runner.shutdown(wait=SHUTDOWN_TIMEOUT)`
  drains pending writes for at most 2 seconds, then forces close.
  Hermes' own shutdown timeline isn't extended.
* **Bun stays running** between Hermes invocations. CLI start/stop
  doesn't restart the Mastra server — `ensure_running()` is idempotent
  and reuses the existing PID. Saves ~600 ms of Bun cold start.

### 3.8 Context engine wrapper

* **Wraps any engine, default `compressor`.** Users keep their existing
  engine (LCM or otherwise) and gain Mastra-aware injection on top.
* **Token-state mirroring.** The wrapper mirrors `last_prompt_tokens`,
  `threshold_tokens`, `context_length` from the delegate so
  `run_agent.py`'s display/logging path is byte-identical to using the
  delegate directly.
* **Engine tools pass through.** If the underlying engine exposes
  `lcm_grep`, `lcm_describe`, etc., the wrapper forwards them. The
  Mastra-specific recall tools are `MemoryProvider` tools, not
  engine tools — separation of concerns.

---

## 4. Non-blocking guarantees

The plugin's correctness depends on **none of its public methods ever
blocking on Mastra**. The contract:

1. Every provider hook listed in §1 has a budget < 50 ms.
2. The budgets hold even when:
   - the Bun server is unreachable,
   - the libSQL DB is locked,
   - the upstream Observer/Reflector model API is rate-limited,
   - the network is offline.
3. Failure mode is silent: log at DEBUG, return empty/None, let Hermes
   continue.
4. Tests in `tests/test_non_blocking_hooks.py` enforce this with a
   "fake-broken-client" fixture that introduces a 5-second delay on
   every HTTP call. Each hook must still return within budget.

When you add a new hook, write the deadline test first.

---

## 5. Configuration surface

The plugin exposes one config knob per dimension users actually need:

| Key | Default | Purpose |
|-----|---------|---------|
| `server_url` | `http://127.0.0.1:4191` | Bun server location |
| `server_port` | `4191` | Listen port |
| `auto_start` | `true` | Auto-start Bun on first use |
| `observer_url` / `observer_name` / `observer_api_key_env` | Venice/Gemini Flash | Observer model |
| `reflector_url` / `reflector_name` / `reflector_api_key_env` | Venice/Gemini Pro | Reflector model |
| `recall_top_k` | `4` | Observations injected per turn |
| `temporal_markers` | `true` | Insert temporal-gap markers |
| `auth_token` | (none) | Optional bearer token guarding the server |
| `context_engine_wrapper` | `true` | Install the Mastra-aware ContextEngine wrapper |
| `context_engine_pressure_fraction` | `0.50` | Fraction of threshold at which to bump recall_top_k |
| `context_engine_boosted_top_k` | `8` | recall_top_k under memory pressure |

We deliberately don't expose: `vector` config, `embedder` model, `scope`
(workingMemory always resource-scoped), `processors` (Hermes owns the
pipeline), `lastMessages` (recall API takes per-call limit). Each absent
knob is a deliberate "Hermes is the boss" decision.
