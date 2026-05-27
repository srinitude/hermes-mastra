# hermes-mastra

[![skills.sh](https://skills.sh/b/srinitude/hermes-mastra)](https://skills.sh/s/srinitude/hermes-mastra)
[![Quality](https://github.com/srinitude/hermes-mastra/actions/workflows/quality.yml/badge.svg)](https://github.com/srinitude/hermes-mastra/actions/workflows/quality.yml)
[![Upstream Watch](https://github.com/srinitude/hermes-mastra/actions/workflows/upstream-watch.yml/badge.svg)](https://github.com/srinitude/hermes-mastra/actions/workflows/upstream-watch.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Mastra memory provider for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

The full power of [`@mastra/memory`](https://mastra.ai/docs/memory/overview) plugged into Hermes through one shared local server. Each Hermes profile becomes a Mastra `resourceId`; each session becomes a thread; every Hermes hook routes to the Mastra primitive that naturally fits — and nothing on Hermes' main thread ever blocks on Mastra's network.

```
                       ┌────────────────────────────────────────────────────────┐
   Hermes default  ────┤                                                        │
                       │   Bun + Hono server      ───▶  libSQL DB                │
   Hermes profile a ───┤   localhost:4191                ~/.hermes/mastra.db    │
                       │                                                        │
   Hermes profile b ───┤   @mastra/memory (Memory + Observer + Reflector)       │
                       │   @mastra/libsql (Storage + PromptBlocks domain)       │
                       └────────────────────────────────────────────────────────┘
```

---

## What you get

**Eight model-driven memory tools** alongside Hermes' built-in `memory` and `session_search`:

| Tool | What it does | Cost |
|------|--------------|------|
| `mastra_recall` | Latest observation log for the current session | ⚡ cheap (cache-served) |
| `mastra_search` | Keyword search across observations in this profile | ⚡ cheap |
| `mastra_semantic_search` | Vector / semantic search across observations | 💸 pays for vector query |
| `mastra_observe` | Persist a manual observation | ⚡ cheap |
| `mastra_working_memory` | Read the resource-scoped working-memory mirror | ⚡ cheap |
| `mastra_artifact_get` | Read the canonical version of `SOUL.md` / `MEMORY.md` / `USER.md` / `AGENTS.md` | ⚡ cheap |
| `mastra_artifact_history` | Show edit history (versioned via Mastra prompt-blocks) | ⚡ cheap |
| `mastra_artifact_revert` | Append a new version with old content (history preserved, no rewinds) | ⚡ cheap |

**One opt-in `ContextEngine` wrapper** that injects cached observations as a protected system message right before compression and bumps `recall_top_k` when prompt tokens cross 50% of the compressor's threshold. Enable per profile with `hermes config set context.engine mastra`.

**Per-profile isolation, one shared server.** A single Bun process at `localhost:4191` serves every Hermes profile. Each profile = one Mastra `resourceId = hermes:<profile>`. Zero cross-profile leakage, by design.

**Background Observer + Reflector** (per [Mastra's reference docs](https://mastra.ai/reference/memory/observational-memory)). The Observer watches conversations and creates new observations from raw turns and tool results; the Reflector restructures the log by combining related items, surfacing overarching patterns, and condensing where possible. Together they replace raw message history with a dense observation log.

**Versioned identity files** (NEW). `SOUL.md`, `MEMORY.md`, `USER.md`, and per-project `AGENTS.md` snapshots are stored as Mastra `prompt-blocks` — sanctioned, schema-validated, versioned storage from `@mastra/core`. The on-disk file becomes an atomic *cache* of the active version; Mastra is the source of truth. Every edit creates a new version with a change-message and timestamp. The system prompt keeps working when the server is unreachable because the file always exists.

**Non-blocking by contract.** Every public hook returns within a documented latency budget (typically 2–50 ms) **even when the underlying Mastra HTTP call hangs for 5 full seconds**. Verified by [`tests/test_non_blocking_hooks.py`](tests/test_non_blocking_hooks.py) — the test fixture forces a 5-second hang on every HTTP call and asserts each hook still returns under budget.

**Hermes-led design.** Every Mastra primitive is mapped to the Hermes hook that naturally triggers it. Read [`docs/HERMES_INTEGRATION_MAP.md`](docs/HERMES_INTEGRATION_MAP.md) for the per-hook contract — what fires when, what's deliberately not integrated, and why.

---

## Resilience guarantees

Grounded against the cached Hermes, Mastra, Bun, and Hono source/doc evidence in [`analysis/research/`](analysis/research/) and enforced by the RED resilience suite:

- **No hook raises into Hermes.** Hot-path work crosses `safe_call` / `async_runner`; chaos tests fault the client and assert the provider still returns.
- **No hot-path blocking.** `prefetch`, `sync_turn`, `on_pre_compress`, `on_session_end`, `on_memory_write`, and `on_delegation` enqueue I/O and stay below the 100 ms p99 budget under 500 ms client latency.
- **Fail-closed upstream calls.** `MastraClient` validates response size/JSON/schema at the boundary and runs HTTP through a circuit breaker that opens after repeated failures, half-opens after cooldown, and returns cached/no-op results while open.
- **No profile leakage.** `RecallCache` is keyed by `(profile, thread)`, bounded by LRU, and cleared synchronously on profile/session switches before a new recall can be served.
- **Idempotent observations.** Manual and mirrored observation writes deduplicate on `(thread, profile, kind, normalized_text)` through a bounded LRU.
- **Bounded saturation.** The async runner drops oldest queued work under pathological bursts, increments diagnostics, and emits one `queue_saturation` log per burst without blocking producers.
- **Server hard-fail boundary.** The Bun listener declares `idleTimeout` and an `error` response path that returns structured 503 JSON instead of wedging requests.
- **Cron/partial-init safety.** Cron contexts skip server bring-up and tool exposure; partially initialized providers stay deterministic no-ops until the next successful initialize.

Current resilience benchmark (2026-05-06, plugin v0.2.2): fault-injected hot-path p99 **0.03 ms**, 0 escaped hook failures, chaos loop green 10/10; raw numbers in [`references/last-benchmark.json`](references/last-benchmark.json) and [`references/last-benchmark.md`](references/last-benchmark.md). Reproduce with `mise run bench:resilience` and `mise run chaos`.

---

## Quick install

```bash
# 1. Install the plugin into Hermes
hermes plugins install srinitude/hermes-mastra
hermes config set memory.provider mastra

# 2. Optional: also wire the context-engine wrapper (Mastra-aware compression)
hermes config set context.engine mastra

# 3. One-time setup: install Bun deps + start the local server
hermes mastra setup

# 4. Verify
hermes mastra status
hermes memory status        # should show: "Provider: mastra ← active"

# 5. Use Hermes normally — observations start flowing after a few turns
hermes
```

Requires **Python ≥ 3.10** and **[Bun](https://bun.sh)** (`mise use -g bun@latest` or `curl -fsSL https://bun.sh/install | bash`).

---

## How Hermes hooks map to Mastra primitives

Full table in [`docs/HERMES_INTEGRATION_MAP.md`](docs/HERMES_INTEGRATION_MAP.md). Highlights:

| Hermes hook | Budget | Mastra primitive | What we do |
|-------------|--------|------------------|------------|
| `system_prompt_block()` | 0 ms | none | Stable text only — keeps Anthropic prompt-cache intact |
| `prefetch(query)` | ≤ 5 ms | observation cache | Read last cached snapshot; refresh in background |
| `sync_turn(user, asst)` | ≤ 5 ms | `POST /messages` | Fire-and-forget enqueue |
| `on_pre_compress(messages)` | ≤ 50 ms | observation injection (via engine wrapper) | Cached observations land inside the compressor's protected zone |
| `on_memory_write(action, target, content)` | ≤ 5 ms | working memory + artifact mirror | Both targets enqueued; file cache updated atomically |
| `on_session_end(messages)` | ≤ 50 ms | `POST /flush` | Best-effort drain |
| `handle_tool_call(name, args)` | per-tool | direct HTTP | Only deliberately-blocking surface — model asked for it |

---

## Tools the agent gets

The plugin exposes **8 tools** to the model, all prefixed `mastra_`. Each tool has a single, well-defined responsibility — there's no overlap, and the schema descriptions cross-reference siblings so the model picks the right one. Tool names, parameters, and limits below are the authoritative spec, taken directly from [`tool_schemas.py`](tool_schemas.py).

> **All tools are model-driven.** None of these run automatically on Hermes' hot path — they fire only when the agent decides to call them. The hot-path side (the cached observation block injected into every system prompt) is separate; see [`docs/HERMES_INTEGRATION_MAP.md`](docs/HERMES_INTEGRATION_MAP.md) §2 for the per-hook contract.

### At a glance

| Tool | Purpose | Required params | Optional params | Cost |
|------|---------|-----------------|------------------|------|
| `mastra_recall` | Read THIS thread's distilled observation log | — | `limit` (1–32, default 8) | ⚡ cache-served |
| `mastra_search` | Keyword search across all observations in this profile | `query` | `limit` (1–20, default 8) | ⚡ cheap (substring match) |
| `mastra_semantic_search` | Vector / meaning-based search across observations | `query` | `limit` (1–20, default 8) | 💸 vector query + re-rank |
| `mastra_observe` | Persist a manual observation (correction, decision, preference) | `text` | `kind` (free-form tag) | ⚡ cheap |
| `mastra_working_memory` | Read the resource-scoped working-memory mirror | — | — | ⚡ cheap |
| `mastra_artifact_get` | Read the canonical version of an identity file | `kind` | — | ⚡ cheap |
| `mastra_artifact_history` | List version history of an identity file | `kind` | `limit` (1–50, default 20) | ⚡ cheap |
| `mastra_artifact_revert` | Restore an old version (history preserved, new version appended) | `kind`, `version` | — | ⚡ cheap (one upsert) |

`kind` ∈ {`soul`, `memory`, `user`, `agents`} for artifact tools. See [Versioned artifacts](#versioned-artifacts-mastra-prompt-blocks) below for what each kind maps to.

### Detailed specs

#### `mastra_recall` — current thread's observation log

```
mastra_recall(limit?: 1..32 = 8) → { profile, thread, observations: string }
```

**What it does.** Returns the dense observation log the Observer + Reflector have produced for the *current* thread, formatted as numbered bullet points. The observation log is what gets injected into every Hermes system prompt's recall block — this tool just exposes it on demand at higher fidelity.

**How it works.** Hits `GET /api/memory/recall?thread=<sid>&profile=<p>&limit=<n>`. The Bun server reads the latest cached observation set for the active session from libSQL; no LLM call is made.

**When to use.** Every turn where you want fresher detail than the (cache-served) system-prompt block already shows. The system prompt's recall is intentionally tiny (default 4 observations); this tool can pull up to 32.

**Pitfalls.**
- The Observer fires on token thresholds, not per-message. A handful of test pings won't produce observations — wait for real conversation volume.
- This is the *current thread* only. For cross-thread search, use `mastra_search` or `mastra_semantic_search`.

---

#### `mastra_search` — keyword search across observations

```
mastra_search(query: string, limit?: 1..20 = 8) → { count, observations: [{thread, text, kind}] }
```

**What it does.** Substring-match search across all observations in *every* thread under the active profile. Each result includes the originating `thread` ID so you can correlate hits with `session_search` matches.

**How it works.** Hits `GET /api/memory/search?query=<q>&profile=<p>&limit=<n>`. The server iterates threads, scans each thread's observations, returns matches in document order. No vector search; pure case-insensitive substring.

**When to use.**
- "What was decided about X?" — keyword finds it cheaply
- "Have I ever discussed Y?" — quick existence check
- Prefer this over `mastra_semantic_search` whenever exact keywords would work — it's 10× cheaper.

**Pitfalls.**
- Substring match. "deadlines" won't match "deadline" — sign-off on the keyword you choose.
- For synonym / paraphrase / conceptual matches, escalate to `mastra_semantic_search`.

---

#### `mastra_semantic_search` — vector search by meaning

```
mastra_semantic_search(query: string, limit?: 1..20 = 8)
  → { count, observations: [{thread, text, score}] }
```

**What it does.** Vector / semantic search across observations using Mastra's `vectorSearchString` recall path. Returns the same shape as `mastra_search` plus a relevance `score` per hit.

**How it works.** Hits `GET /api/memory/semantic_search?query=<q>&profile=<p>&limit=<n>`. The server picks an anchor thread under the active resource, calls `memory.recall({ vectorSearchString, threadConfig: { semanticRecall: { topK } } })` from `@mastra/memory`. The vector store + embedder need to be configured (default off — falls back to empty results otherwise).

**When to use.**
- Keyword search returned nothing useful but you suspect the concept exists under different wording.
- "Anything related to deadline pressure?" (would match "tight schedule" / "Q3 crunch" / "shipping anxiety")

**Pitfalls.**
- Costs more than `mastra_search` (vector query + re-rank, ~50 ms vs <5 ms).
- Falls back to **empty results** when the vector store is unconfigured — the schema description tells the model so it knows to retry with `mastra_search`.
- Disabled by default in `Memory` config to avoid auto-firing on every save — only fires when this tool is called.

---

#### `mastra_observe` — persist a manual observation

```
mastra_observe(text: string, kind?: string) → { ok, profile, thread }
```

**What it does.** Writes a synthetic system-message tagged `[OBSERVATION:<kind>]` into the active thread's history. The Observer ingests it on its next pass and folds it into the dense observation log.

**How it works.** Hits `POST /api/memory/observation` with the text + optional `kind` tag. The server saves it as a `system` role message under the thread; the Observer later picks it up.

**When to use.**
- The user **corrects** you ("no, we use Postgres, not MySQL") — `kind="correction"`
- The user makes a **decision** ("we're going with TanStack Query") — `kind="decision"`
- The user states a durable **preference** ("always commit, never push") — `kind="preference"`
- A **delegation result** worth remembering — `kind="delegation"`

**Pitfalls.**
- **Don't observe routine commentary.** The Observer auto-distills raw turns. This tool is for facts you want **guaranteed** to land — not for narrating what just happened.
- Larger / session-specific facts go here. Smaller / always-relevant facts (≤2200 chars total) belong in Hermes' built-in `memory` tool, which is frozen into the system prompt at session start.

---

#### `mastra_working_memory` — read working-memory mirror

```
mastra_working_memory() → { profile, working_memory: string }
```

**What it does.** Reads the resource-scoped working-memory document Mastra keeps in sync with the agent's `MEMORY.md` / `USER.md` edits.

**How it works.** Hits `GET /api/memory/working_memory?profile=<p>`. The server calls `memory.getWorkingMemory({ resourceId })` and returns the markdown text.

**When to use.**
- The agent suspects the on-disk MEMORY.md / USER.md and the Mastra mirror diverged.
- The agent wants to inspect what was mirrored before deciding whether to write more.
- Audit / debugging.

**Pitfalls.**
- **Built-in `MEMORY.md` / `USER.md` is canonical** — already injected into the system prompt at layer 5. Don't loop the agent through this tool for routine recall; the system prompt already has the relevant content.
- Working memory is **resource-scoped** (per profile, across threads), unlike observations which are thread-scoped.

---

#### `mastra_artifact_get` — read a versioned identity file

```
mastra_artifact_get(kind: 'soul' | 'memory' | 'user' | 'agents')
  → { profile, kind, exists, version, content }
```

**What it does.** Returns the *canonical* current version of a Hermes identity file, sourced from Mastra's `prompt-blocks` storage domain. The on-disk file (`~/.hermes/SOUL.md`, `~/.hermes/memories/MEMORY.md`, etc.) is just a *cache* of this version, kept fresh atomically.

**How it works.** Hits `GET /api/memory/artifact?kind=<k>&profile=<p>`. The server calls `promptBlocks.getById('hermes:<kind>:<profile>')` from `@mastra/libsql`. Returns the resolved content of the active version.

**When to use.**
- Verify the on-disk file matches the database (especially after another process edited the mirror).
- Read the canonical text when the file may be stale.
- Diff against a previous version (chain with `mastra_artifact_history`).

**Pitfalls.**
- The on-disk file is **always the source the system prompt reads** — this tool just exposes the canonical version. They should normally agree.
- For per-project AGENTS.md, the artifact is keyed by `sha256(absolute_cwd_path)`, not profile name. The plugin captures snapshots automatically when Hermes loads an `AGENTS.md`; you don't address them by `kind=agents` from a different working directory.

---

#### `mastra_artifact_history` — list version history

```
mastra_artifact_history(kind: 'soul' | 'memory' | 'user' | 'agents', limit?: 1..50 = 20)
  → { profile, kind, count, versions: [{version, created_at, change_message, content}] }
```

**What it does.** Returns the version history (newest first) for a Hermes identity file. Each version row includes its content, change message, and timestamp.

**How it works.** Hits `GET /api/memory/artifact/history?kind=<k>&profile=<p>&per_page=<n>`. The server calls `promptBlocks.listVersions({ blockId: 'hermes:<kind>:<profile>', orderBy: 'versionNumber', direction: 'DESC' })`.

**When to use.**
- Audit changes ("what did MEMORY.md look like yesterday?").
- Diff revisions before a revert.
- Debug "who/what overwrote this?" — change messages tell you.

**Pitfalls.**
- Versions are append-only. Even reverts create a *new* version (never rewinds) — see `mastra_artifact_revert`.
- `limit` caps at 50 per call. For older versions, paginate by adjusting `limit` and re-querying (pagination params not yet exposed; planned).

---

#### `mastra_artifact_revert` — restore a prior version

```
mastra_artifact_revert(kind: 'soul' | 'memory' | 'user' | 'agents', version: integer ≥ 1)
  → { ok, profile, kind, reverted_to }
```

**What it does.** Appends a **new version** of the artifact whose content matches version `N` (the `version` param). History is preserved — the older version stays in place, and a fresh version-bump records the revert with `change_message: "Reverted to vN"`. The on-disk file cache is refreshed atomically right after.

**How it works.** Hits `POST /api/memory/artifact/revert` with `{ kind, profile, version }`. The server lists versions, finds the target by version number, then calls `promptBlocks.update({ id, content: target.content, changeMessage })` — which Mastra's prompt-blocks domain implements as a version bump, not a destructive overwrite.

**When to use.**
- The agent or user just made a bad edit to MEMORY.md / USER.md / SOUL.md and wants the previous text back.
- A/B-comparing identity tweaks.
- Recovering from a corruption cascade.

**Pitfalls.**
- Returns 404 if `version` doesn't exist in history. Always pair with `mastra_artifact_history` first.
- The newly-appended version becomes `version + 1` of the latest, *not* the old `version` itself. The history-with-content trail keeps both.

---

### Decision matrix — which tool for which question

| Question | Best tool | Why |
|----------|-----------|-----|
| "What's already in this thread's summary?" | `mastra_recall` | Cheapest, current-thread only, no query |
| "What was decided about X (exact word)?" | `mastra_search` | Substring match, fastest cross-thread search |
| "Anything related to <concept>, even paraphrased?" | `mastra_semantic_search` | Vector match, catches synonyms keyword would miss |
| "What were the exact spoken words?" | `session_search` *(Hermes built-in)* | Raw transcript FTS5, complementary to observations |
| "Persist this fact for future sessions" | `mastra_observe` | If big or session-specific |
| "Persist this fact for *every* session" | `memory` *(Hermes built-in)* | If small + always relevant; goes into MEMORY.md / USER.md and frozen into system prompt |
| "Is the MEMORY.md mirror up to date?" | `mastra_working_memory` | Reads the resource-scoped mirror |
| "What did SOUL.md look like 3 versions ago?" | `mastra_artifact_history kind=soul` | Lists every version with content |
| "Restore that old MEMORY.md" | `mastra_artifact_revert kind=memory version=N` | Appends a new version with the old content |
| "Is the on-disk file canonical right now?" | `mastra_artifact_get kind=<k>` | Returns the active version from the database |

### Cross-references

- **Recall hierarchy.** Observations (Mastra, distilled) live above transcripts (`session_search`, raw). Reach for `mastra_*` first when you want **what was decided**; reach for `session_search` when you want **what was said**.
- **Persistence hierarchy.** Built-in `memory` (small, prompt-frozen) → `mastra_observe` (large, surface via recall/search) → `mastra_artifact_*` (versioned, structured identity files).
- **Cost hierarchy.** All ⚡ tools are <5 ms in normal operation. `mastra_semantic_search` is the only 💸 tool — use it when keyword fails.

---

## Built-in memory complement

The plugin doesn't replace Hermes' built-in memory — it complements it.

| Surface | Authority | Size | Persistence |
|---------|-----------|------|-------------|
| Built-in `memory` tool → `MEMORY.md` / `USER.md` | **canonical** for tiny core facts | 2,200 / 1,375 chars | Frozen into system prompt at session start |
| `mastra_observe` → observation log | overflow + session-specific | unlimited | Surfaces via recall/search next turn |
| Mastra prompt-blocks → SOUL/MEMORY/USER/AGENTS | **canonical** with full version history | unlimited | On-disk file is the cache; full edit history queryable |

**Built-in memory file format.** Entries in `MEMORY.md` and `USER.md` are delimited by a single line containing only the section sign **`§`** (U+00A7). This is what makes `memory(action="remove", old_text="...")` work — each `§`-delimited block is one independently-addressable entry. Don't substitute `---` / `===` / blank lines — the parser only recognises `§`.

**Capacity-aware hint.** When MEMORY.md or USER.md crosses **50%** of its cap, the system-prompt block adds a hint pointing the agent at `mastra_observe` for overflow. Half-full is the early-warning point — waiting until 80% leaves only a few turns of headroom.

**Off-load anchor.** On first activation, the plugin appends a single `[mastra-rule]` entry to both files telling the agent which surface to use for what. The rule is anchor-detected so re-installs are idempotent and uninstalls are clean.

---

## Versioned artifacts (Mastra prompt-blocks)

`SOUL.md`, `MEMORY.md`, `USER.md`, and per-project `AGENTS.md` snapshots are stored as **versioned Mastra `prompt-blocks`** — the [`PromptBlocksStorage` domain](https://github.com/mastra-ai/mastra/blob/main/packages/core/src/storage/domains/prompt-blocks/base.ts) already exposed by `LibSQLStore`. We don't invent a custom table.

**Source-of-truth direction.** Mastra is canonical; the on-disk file is a *cache*.

* **Read path:** Hermes' system prompt assembly reads the file from disk as it always has. The file always exists with the latest content because the plugin keeps it fresh atomically (temp + `os.replace`). The system prompt keeps working **even when the Bun server is unreachable** — the non-blocking contract holds.
* **Write path:** `on_memory_write` (and `mastra_artifact_revert`) enqueue an `upsert_artifact` to the prompt-blocks store via the bounded background queue, then refresh the file cache atomically.
* **Seed path:** On first activation per profile, existing on-disk content is uploaded as version 1 of each block. Idempotent — content equality is detected server-side.

**Per-block identity:**

```
hermes:soul:<profile>      ← was SOUL.md
hermes:memory:<profile>    ← was MEMORY.md
hermes:user:<profile>      ← was USER.md
hermes:agents:<sha256(cwd)> ← per-project AGENTS.md snapshots
```

AGENTS.md is project-scoped (one per repo), so snapshots are keyed on `sha256(absolute_path)`. The plugin observes them via `do_context_files_loaded` — when Hermes loads an `AGENTS.md`, we upsert a snapshot. We don't write back to the project file (it's the user's, not ours).

---

## Configuration

All config lives in `~/.hermes/mastra.json`. Edit by re-running `hermes mastra setup` or hand-editing the JSON.

### Defaults

| Key | Default | Purpose |
|-----|---------|---------|
| `server_url` | `http://127.0.0.1:4191` | Where the Mastra server listens |
| `server_port` | `4191` | Port for the Bun server |
| `auto_start` | `true` | Start Bun on first use if not running |
| `observer_url` / `observer_name` / `observer_api_key_env` | Venice / Gemini Flash | Observer model |
| `reflector_url` / `reflector_name` / `reflector_api_key_env` | Venice / Gemini Pro | Reflector model |
| `recall_top_k` | `4` | Observations injected per turn |
| `temporal_markers` | `true` | Insert temporal-gap markers (10+ min idle) |
| `auth_token` | (none) | Optional bearer token via `MASTRA_API_KEY` |
| `context_engine_wrapper` | `true` | Install the ContextEngine wrapper. Active only when `context.engine: mastra`. |
| `context_engine_pressure_fraction` | `0.50` | Boost `recall_top_k` once prompt tokens cross this fraction of the compressor's threshold |
| `context_engine_boosted_top_k` | `8` | Value to boost `recall_top_k` to under pressure |

### Resilience knobs (new in 0.2.2)

These knobs tune the fail-closed client boundary, the server supervisor, the bounded observation dedup cache, the partitioned recall cache, and the response guard. All are optional — defaults are chosen to be safe on every shipped hook and are enforced by [`tests/test_resilience_hot_path.py`](tests/test_resilience_hot_path.py) and the chaos suite.

| Key | Default | Purpose |
|-----|--------:|---------|
| `breaker_threshold` | `5` | Consecutive `MastraClient` HTTP failures before the breaker opens |
| `breaker_cooldown_seconds` | `5.0` | Cooldown before the breaker auto-half-opens for a probe call |
| `supervisor_max_restarts_per_minute` | `3` | Cap on Bun auto-restarts per rolling minute (exponential backoff within the cap) |
| `recall_cache_lru_size` | `32` | Entries the `(profile, thread)`-keyed `RecallCache` retains before LRU eviction |
| `dedup_lru_size` | `512` | Idempotency-key slots for `(thread, profile, kind, normalized_text)` deduplication |
| `response_max_bytes` | `1_000_000` | Hard cap on a single Mastra HTTP response body before the guard rejects it |
| `auth_token_env` | `MASTRA_API_KEY` | Environment variable the client reads for its bearer token; rotated lazily on a 401 |

Each value is validated at load time by `server_config._coerce_types`; a malformed value falls back to the default and logs a single warning (no secret ever lands in the log). Config keys also flow through the Hermes memory-setup wizard — see [`config_schema.py`](config_schema.py).

### Verify & tune resilience

```bash
mise run chaos                 # fault-inject every hot path; asserts no raise into host
mise run bench:resilience      # hot-path p99 budget under chaos mode; persists numbers
mise run bench                 # baseline hot-path + queue + cache freshness
```

### Choose your Observer & Reflector models

Two roles, configured independently. The Observer runs frequently and should be cheap; the Reflector runs less often and should be stronger.

```bash
# Apply a known-good preset
hermes mastra models preset venice          # default: gemini-3-flash-preview → gemini-3-1-pro-preview
hermes mastra models preset openai          # gpt-4o-mini → gpt-4o
hermes mastra models preset openrouter      # llama-3.1-8b → claude-3.5-sonnet
hermes mastra models preset anthropic-or    # haiku → sonnet (via OpenRouter)
hermes mastra models preset hermes-local    # reuse Hermes's own logged-in provider

# Or set each role manually
hermes mastra models set observer \
    --name gpt-4o-mini \
    --base-url https://api.openai.com/v1 \
    --api-key-env OPENAI_API_KEY

hermes mastra models set reflector \
    --name claude-3-5-sonnet-latest \
    --base-url https://api.anthropic.com/v1 \
    --api-key-env ANTHROPIC_API_KEY

hermes mastra models                        # show current
hermes mastra models presets                # list all built-in presets
```

### Flexible Mastra `MemoryOptions` passthrough

Anything documented at [mastra.ai/reference/memory/Memory](https://mastra.ai/reference/memory/Memory) can be set via dotted-key config — the plugin is a JSON courier. The TS server deep-merges your overrides over its built-in defaults before constructing `new Memory({ options })`.

```python
import mastra_options as mo

mo.set_option("lastMessages", 50)
mo.set_option("workingMemory.scope", "thread")
mo.set_option("observationalMemory.observation.messageTokens", 4000)
mo.set_option("observationalMemory.reflection.observationTokens", 12000)

mo.resolve_options()    # see resolved options shipped to the Bun server
mo.reset_options()      # wipe overrides (defaults remain)
```

---

## CLI reference (`hermes mastra`)

```bash
# Server lifecycle
hermes mastra setup                          # interactive: write config, install bun deps, start server
hermes mastra status                         # health probe + pid + recent log lines
hermes mastra server start                   # / stop / restart / install
hermes mastra logs [-n 80]                   # tail $HERMES_HOME/logs/mastra.log

# Inspect
hermes mastra resources                      # list resourceIds (one per profile)
hermes mastra threads --profile <name>       # threads for a profile
hermes mastra observations <thread_id>       # dump observations for a thread

# Destructive (with confirmation)
hermes mastra reset --profile <name>         # wipe all threads/observations for a profile
hermes mastra reset --profile <name> --yes   # skip confirmation
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Hermes Agent (Python)                            │
│                                                                            │
│   MemoryManager ──→ MastraMemoryProvider                                  │
│                       ├── tool_schemas.py        (8 tool JSON schemas)    │
│                       ├── provider_lifecycle.py  (every hook as a fn)     │
│                       ├── tool_observers.py      (todo / skill / snapshot)│
│                       ├── lifecycle_helpers.py   (alive / profile / safe) │
│                       ├── lifecycle_observer_reexports.py (compat shim)   │
│                       ├── recall_cache.py        (cached snapshot)        │
│                       ├── async_runner.py        (bounded work queue)     │
│                       ├── client.py              (httpx wrapper)          │
│                       ├── server_config.py       (paths + config)         │
│                       ├── server_env.py          (env builder)            │
│                       ├── server_process.py      (Bun spawn / stop)       │
│                       ├── model_config.py        (Observer / Reflector)   │
│                       ├── model_presets.py       (Venice / OpenAI / etc)  │
│                       ├── mastra_options.py      (flexible passthrough)   │
│                       ├── memory_rules.py        ([mastra-rule] anchor)   │
│                       ├── artifacts.py           (seed + file-cache write)│
│                       ├── artifact_tools.py      (artifact tool dispatch) │
│                       ├── cli.py + cli_commands.py  (hermes mastra)       │
│                       └── config_schema.py       (memory setup wizard)    │
│                                                                            │
│   ContextEngineManager ──→ MastraContextEngine *(opt-in wrapper)*         │
│                       ├── agent_context_engine.py (engine wrapper class)  │
│                       └── engine_install.py       (register-time wiring)  │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ HTTP (httpx, bounded async work queue)
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                  Bun + Hono server (server/src/)                  │
│                                                                            │
│   Routes:                                                                  │
│     GET  /health                                                           │
│     GET  /api/memory/healthz            (richer probe data: pid, uptime)   │
│     POST /api/memory/messages           (turn ingestion)                   │
│     GET  /api/memory/recall             (current thread's observations)    │
│     GET  /api/memory/search             (keyword search)                   │
│     GET  /api/memory/semantic_search    (vector / semantic search)         │
│     POST /api/memory/working_memory     (mirror MEMORY.md / USER.md write) │
│     GET  /api/memory/working_memory     (read working-memory mirror)       │
│     POST /api/memory/observation        (manual observe + lineage + snaps) │
│     POST /api/memory/flush              (force Observer drain)             │
│     GET  /api/memory/resources          (list profiles seen)               │
│     GET  /api/memory/threads            (list threads for a profile)       │
│     GET  /api/memory/observations       (raw observation log dump)         │
│     POST /api/memory/reset              (wipe a profile's memory)          │
│     GET  /api/memory/artifact           (read canonical artifact)          │
│     POST /api/memory/artifact           (upsert artifact, version-bumps)   │
│     GET  /api/memory/artifact/history   (list versions)                    │
│     POST /api/memory/artifact/revert    (append new version with old text) │
│                                                                            │
│   @mastra/memory     → Memory{ workingMemory, observationalMemory, ... }  │
│   @mastra/memory     → Observer + Reflector agents                        │
│   @mastra/libsql     → LibSQLStore (memory + prompt-blocks domains)       │
│   Storage:           → file:~/.hermes/mastra.db                           │
└──────────────────────────────────────────────────────────────────────────┘
```

The full Hermes ↔ Mastra mapping — every hook, every primitive, every latency budget — lives in [`docs/HERMES_INTEGRATION_MAP.md`](docs/HERMES_INTEGRATION_MAP.md).

**Project conventions** keep every Python file under 200 LOC, every function/class under 30 LOC, and max nesting depth ≤ 3. Enforced by [`tests/test_code_size_policy.py`](tests/test_code_size_policy.py).

---

## Development

`mise` is the only user-facing CLI — every workflow goes through `mise run <task>`. Tasks are grouped here by **what role they play** in the dev loop. The full task table at the end shows dependencies + side effects so you can pick the right entrypoint.

> **First time?** Run `mise run install` and you're done. It chains `setup` → `setup:opensrc` → installs the Python venv + Bun deps + opensrc CLI in one shot. Every command below assumes you've done that once.

### 1. Bootstrap — get the project ready to develop

| Task | Role | Side effects |
|------|------|--------------|
| `mise run setup` | Verifies `bun` and `python` are registered globally with mise. Exits 3 with a remediation message if not. | None — read-only check. |
| `mise run setup:opensrc` | Installs the [`opensrc`](https://github.com/vercel-labs/opensrc) CLI used by `compat:*` to clone upstream source for static API checks. **Idempotent** — skips if already present, exits 0 even on offline failure (compat tests skip). | May download `opensrc` to a directory on your `PATH` (e.g. `/usr/local/bin` or `/opt/homebrew/bin`). |
| **`mise run install`** | **The one-shot bootstrap.** Depends on `setup` + `setup:opensrc`. Creates `.venv/`, installs `.[dev]`, drops `server/bun.lock`, and runs `bun install` so `latest` actually walks forward against upstream Mastra/Hermes. | Creates `.venv/`, refreshes `server/node_modules/` and `server/bun.lock`. |

### 2. Run the server — needed if you're hacking on TS

| Task | Role | Side effects |
|------|------|--------------|
| `mise run dev` | Foreground Bun server with `--watch` hot reload. Use this while editing `server/src/`. | Listens on port 4191 (or whatever `MASTRA_PORT` is set to). |
| `mise run server` | Foreground Bun server without hot reload (closer to production). | Same port. |
| `mise run compile` | TS compile to `server/dist/` — sanity build, used by the prod `hermes mastra server start` path. | Writes `server/dist/index.js`. |
| `mise run build` | No-op for the Python plugin; chains `typecheck` for the TS server so a single command verifies "this builds". | Same as `typecheck`. |

### 3. TDD loop — fast feedback on changes

| Task | Role | Side effects |
|------|------|--------------|
| `mise run test:py` | **The fastest gate** — only the Python pytest suite. Most edits should run this. ~3 sec. | None. |
| `mise run test:ts` | Bun TS tests (server-side, when present). | None. |
| **`mise run test`** | **Full Python suite (425+ tests).** Includes `test_code_size_policy.py` (LOC + nesting limits) and `test_non_blocking_hooks.py` (5-second-stuck-client deadline tests). ~2-3 min. | None. |

### 4. Quality gate — what CI runs on every PR

`format`, `lint`, `typecheck`, `test`, `security:audit`, `validate` each enforce one quality dimension. The `quality` task runs all of them in dependency order:

| Task | Role | Side effects |
|------|------|--------------|
| `mise run format` | `ruff format` (Python) + `biome write` (TS) + `ruff check --fix` for safe auto-fixes. | **Edits files in place** — run before committing, not on a dirty WIP. |
| `mise run lint` | `ruff check` + `biome lint`. Read-only. | None. |
| `mise run typecheck` | TS typecheck on the Bun server. Advisory — Bun runs TS permissively at runtime, so this is a CI guard, not a runtime gate. | None. |
| `mise run security:audit` | `pip-audit` + `bun pm audit` for known CVEs. | None. |
| `mise run validate` | Confirms `plugin.yaml` + `pyproject.toml` parse cleanly. | None. |
| **`mise run quality`** | **The canonical CI gate.** Depends on all five above. **Run this before opening a PR.** | Files may be edited by `format`. |

### 5. Sync to live Hermes — push changes into a running install

| Task | Role | Side effects |
|------|------|--------------|
| `mise run sync` | `rsync` runtime files into `~/.hermes/hermes-agent/plugins/memory/mastra/`, then verifies the plugin still loads under Hermes' venv. Skips dev-only files (`tests/`, `scripts/`, `_*.py`, `mise.toml`, etc.). | **Writes to `~/.hermes/`.** Does NOT bounce the running Bun server — that's a separate decision. |
| **`mise run quality:full`** | **The local dev sweet spot.** `quality` + `sync`. Use this as your default loop while iterating. | Same as `quality` + `sync`. |

### 6. Upstream compatibility — keep the plugin honest against `latest`

These tasks use `opensrc` to fetch upstream source code and statically verify the APIs the plugin depends on still exist. They run nightly in CI.

| Task | Role | Side effects |
|------|------|--------------|
| `mise run compat:hermes` | Verifies every `MemoryProvider` hook the plugin implements still exists in `NousResearch/hermes-agent` at HEAD. | Clones the repo via `opensrc` (cached). |
| `mise run compat:mastra` | Verifies every `Memory` / `PromptBlocks` method the plugin calls still exists in `mastra-ai/mastra` at HEAD. | Same. |
| `mise run compat` | Both checks. CI runs this. | Same. Set `GITHUB_TOKEN` to avoid unauth rate limits. |
| `mise run deps:refresh` | Drops `server/bun.lock` and re-`bun install --silent` so transitive `latest` deps actually walk forward. | **Edits `server/bun.lock` + `server/node_modules/`.** |

### 7. Documentation maps — refresh source-of-truth references

These use [Firecrawl](https://firecrawl.dev) to crawl upstream docs sites and write a JSON map of all URLs to `references/`. Used to source-ground future implementation decisions. Requires `FIRECRAWL_API_KEY` (read from `~/.hermes/.env`).

| Task | Role | Side effects |
|------|------|--------------|
| `mise run docs:map-mastra` | Refresh `references/mastra-ai-docs-map.json` (mastra.ai/docs). | Writes to `references/`. |
| `mise run docs:map-hermes` | Refresh `references/hermes-agent-nousresearch-com-map.json`. | Same. |
| `mise run docs:map-mise` | Refresh `references/mise-jdx-dev-map.json`. | Same. |
| `mise run docs:map` | All three. | Same. |

### 8. Benchmarks

| Task | Role | Side effects |
|------|------|--------------|
| `mise run bench` | Plugin's own benchmarks: hot-path latency, runner throughput, recall-cache freshness. | Writes results to stdout and `references/last-benchmark.{json,md}`. |
| `mise run bench:resilience` | Runs `scripts/benchmark.py --resilience` — same metrics plus fault-injected hot-path p99 and `failures escaping hooks` count. **Asserts the plugin never raises into the host.** | Writes results to stdout and `references/last-benchmark.{json,md}`. |
| `mise run bench:compare` | Comparative benchmark against the 8 other Hermes memory provider plugins. | Requires those plugins installed. |
| `mise run chaos` | Runs `tests/test_chaos_resilience.py` under randomized fault injection (slow client, saturated queue, profile flips). Green ten-in-a-row in CI. | None. |
| `mise run bench:all` | `bench` + `bench:compare`. | Same. |

### 9. Diagnostics — when something is off

| Task | Role | Side effects |
|------|------|--------------|
| `mise run env` | Dump the mise-resolved environment as JSON (debug `.env` cascade). | None. |
| `mise run tasks` | List every task this project exposes (this is the live source-of-truth). | None. |
| `mise run doctor` | mise's own diagnostics + project-specific checks. | None. |

---

### CI integration

CI runs `mise run quality` on every PR across **three platforms** (Ubuntu, macOS, Windows) via [`.github/workflows/quality.yml`](.github/workflows/quality.yml). The [`upstream-watch.yml`](.github/workflows/upstream-watch.yml) workflow runs nightly to track Hermes + Mastra at HEAD, opening a rolling sync PR when drift is detected.

Agentic workflows via [GitHub Agentic Workflows (gh-aw)](https://github.com/github/gh-aw) handle higher-level tasks:
- [`aw-failure-investigator.md`](.github/workflows/aw-failure-investigator.md) — auto-investigates failed CI runs and creates issues with root-cause analysis
- [`aw-daily-quality-audit.md`](.github/workflows/aw-daily-quality-audit.md) — weekday audit of code-size limits, stale refs, dependency freshness, and doc drift
- [`aw-stale-ref-sweeper.md`](.github/workflows/aw-stale-ref-sweeper.md) — reviews every PR diff for old-name remnants and code-size violations

All workflows reuse `mise run setup:opensrc` and `mise run install` so local-dev parity is exact.

---

## Project conventions

| Rule | Enforced by |
|------|-------------|
| 200 LOC max per file (Python + TypeScript) | [`tests/test_code_size_policy.py`](tests/test_code_size_policy.py) |
| 30 LOC max per function / class body | same |
| Max nesting depth 3 (.py/.ts/.sh only) | same |
| Max cognitive complexity 8 | biome (TS) + ruff (Python) |
| Mastra/AI-SDK pinned to `latest` (HEAD-tracking) | [`tests/test_latest_pinning.py`](tests/test_latest_pinning.py) |
| Every public hook has a deadline test | [`tests/test_non_blocking_hooks.py`](tests/test_non_blocking_hooks.py) |
| Every commit authored as Kiren Srinivasan only — no AI co-authors, no bot identities | git config in CI workflows + commit hooks |
| `mise` is the only user-facing CLI surface | `mise.toml` (no direct `bun`/`bunx`/`biome`/`tsc`/`prettier` in user-facing surfaces) |
| Pre-emptive code review via `coderabbit.ai` on every PR | `.coderabbit.yml` |

---

## Compatibility & versioning

| Dependency | Pin | Why |
|-----------|-----|-----|
| `@mastra/core` | `latest` | Plugin tracks Mastra at HEAD; `mise run compat:mastra` verifies API surface every CI run |
| `@mastra/libsql` | `latest` | same |
| `@mastra/memory` | `latest` | same |
| `@ai-sdk/openai-compatible` | `latest` | same |
| `hono` | `latest` | Mastra's transitive HTTP layer |
| `zod` | `latest` | Mastra's transitive validator |

`mise run compat` runs daily against `NousResearch/hermes-agent` (verifies all `MemoryProvider` hooks still exist) and `mastra-ai/mastra` (verifies the Memory + PromptBlocks APIs we depend on).

---

## Hermes-side configuration cheat sheet

```yaml
# ~/.hermes/config.yaml
memory:
  provider: mastra              # activate this plugin

# Optional: route compression through the Mastra-aware ContextEngine wrapper
# context:
#   engine: mastra              # observation injection + token-aware recall_top_k
```

```bash
# Activate per profile.  Either install profile-aware wrapper aliases
# (hermes profile alias <name>) and run them directly, or switch profiles
# via `hermes profile use <name>` first and then call `hermes config set`.
hermes config set memory.provider mastra                              # default profile
hermes profile use <profile-a> && hermes config set memory.provider mastra
hermes profile use <profile-b> && hermes config set memory.provider mastra

# Verify (each `resourceId` is one profile that has activated the plugin)
hermes mastra resources
# → ['hermes:default', 'hermes:<profile-a>', 'hermes:<profile-b>']
```

Profile credentials: each profile that uses the provider must be able to resolve `observer_api_key_env` / `reflector_api_key_env`. Set these in `~/.hermes/.env` (auto-inherited by every profile) or in the profile's own `~/.hermes/profiles/<name>/.env`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `bun not found in PATH` | Install Bun: `mise use -g bun@latest` (recommended) or `curl -fsSL https://bun.sh/install \| bash` |
| `Bun install fails: peer dependency 'quansync'` | `cd server && rm -f bun.lock && bun install` |
| `recall returns 0 observations` | Normal early in a session — the Observer fires on token thresholds, not per-message. Check `hermes mastra threads --profile <name>` to confirm ingestion. |
| `mastra server is not running` | `hermes mastra server restart` then `hermes mastra logs` |
| `mise run compat` reports "opensrc not found" | `mise run setup:opensrc` to install it (idempotent — skips if already present). The CI workflows run this best-effort and skip compat checks when offline. |
| `GitHub API rate limit exceeded` (during `mise run compat`) | Set `GITHUB_TOKEN` in env so opensrc authenticates |
| `Profile observations leaking across profiles` | Should never happen — verified by [`tests/test_profile_flip_safety.py`](tests/test_profile_flip_safety.py) and [`tests/test_hermes_link.py`](tests/test_hermes_link.py). If it does, file an issue with `hermes mastra resources` output. |
| `Circuit breaker stays OPEN after upstream recovers` | Wait `breaker_cooldown_seconds` (default 5 s); one successful half-open probe closes it. Bump the threshold with `breaker_threshold` if your upstream is flappy. |
| `references/last-benchmark.md says p99 regressed` | Run `mise run bench` once more to rule out noise; if it reproduces, open an issue and include `references/last-benchmark.json`. |
| `queue_saturation log emitted repeatedly` | Expected under pathological load — drop-oldest preserves non-blocking producers. If sustained, reduce write volume or raise `async_runner` queue size (currently 256). |
| `401 after rotating MASTRA_API_KEY` | `MastraClient` rebuilds lazily on the next 401; the old client closes automatically. If a retry still fails, ensure the new token is present in `os.environ[auth_token_env]` before the next hook fires. |

For more, see `hermes mastra logs` and `~/.hermes/logs/agent.log`.

---

## License

MIT — see [LICENSE](./LICENSE).

Author: [Kiren Srinivasan](https://github.com/srinitude) &lt;kiren@fantasymetals.com&gt;.

This plugin is independent of Mastra and Nous Research. Built against [`@mastra/memory`](https://github.com/mastra-ai/mastra) and [`hermes-agent`](https://github.com/NousResearch/hermes-agent) at HEAD.
