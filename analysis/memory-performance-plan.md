# Memory Performance Plan

## 1. Current-state architecture

* **Storage** — one LibSQL DB per profile at
  `<hermes_home>/data/mastra.db`, namespaced by store id
  `hermes-mastra` and resource id `hermes:<profile>`.
* **Server** — Bun + Hono process on `127.0.0.1:4191`, started lazily
  in the background by `_bring_up_server` (off the hot path).
* **Provider** — Python `MastraMemoryProvider` with thin lifecycle
  hooks delegating to `provider_lifecycle.py` free functions; every
  write enqueues onto `async_runner` (bounded daemon thread pool).
* **Recall surface** — `prefetch()` returns the last cached snapshot
  synchronously and enqueues a refresh; coalesced by
  `RecallCache._in_flight`.
* **System prompt** — static block describing the three recall tools
  (`mastra_recall`, `mastra_search`, `mastra_observe`) plus a
  capacity hint when MEMORY.md / USER.md cross 50 % full.
* **Tool dispatch** — `provider_tools.handle_tool_call` routes to the
  HTTP client, bounded by client-side timeout (5 s default).

## 2. Desired-state architecture

The current architecture already meets the perceived-speed goal:
hot-path hooks return in microseconds because work is enqueued, and
the recall snapshot served synchronously is the last successful
fetch. The improvements we add target *non-interference*, *load-order
invariance*, *failure isolation*, and *retrieval relevance under the
plugin contract*, not raw read latency (which is dominated by Mastra
recall ≪ 100 ms in benchmark runs).

## 3. Memory read path

```
turn → AIAgent.run_conversation → MemoryManager.prefetch_all
     → MastraMemoryProvider.prefetch(query, session_id)
         ├─ session_id != _thread? clear cache, rebind thread
         ├─ enqueue_recall (background HTTP GET /api/memory/recall)
         └─ return RecallCache.get()  # last good snapshot
     → build_memory_context_block (fence + system note)
     → injected into the user message before the LLM call
```

Latency budget: `prefetch()` returns synchronously in < 1 ms. Recall
freshness lags by one turn at most; first-turn cold path returns "" if
no observations yet exist.

## 4. Memory write path

```
turn → AIAgent.run_conversation → MemoryManager.sync_all
     → MastraMemoryProvider.sync_turn(user, assistant)
         ├─ alive(p)? if not, return
         └─ async_runner.submit(client.save_turn(...))
              → POST /api/memory/messages → memory.saveMessages
                  with memoryConfig: { observationalMemory: true }
                  → triggers Mastra Observer model in the background
```

End-to-end commit latency on the user side: < 1 ms (enqueue only).
Observation extraction (Observer + Reflector LLM calls) happens
out-of-band on the Bun server.

## 5. Memory ranking strategy

Ranking is performed by Mastra's `Memory.recall`:

* `lastMessages: 20` — recency floor.
* `semanticRecall: { topK: limit }` for `/api/memory/semantic_search`.
* Observational memory layer ranks by importance via the Reflector
  step (Mastra-internal).

The plugin defers ranking to Mastra; we do NOT re-rank in Python.

## 6. Memory compaction strategy

Triggered by Hermes calling `on_pre_compress(messages)` before
context compression. Behaviour in `do_pre_compress`:

1. Take the last cached observation snapshot (truncated to 4 000
   chars for safety).
2. Enqueue `client.write_observation(thread, profile, snapshot,
   kind="pre_compress")`.
3. Enqueue `client.flush(thread, profile)` to force any pending
   Observer/Reflector work.
4. Enqueue a fresh recall so the next `prefetch` sees post-flush
   state.
5. Return the snapshot text to Hermes; it's appended to the
   compression summary prompt so durable observations survive.

## 7. Tenant isolation strategy

* **Profile = tenant** — each Hermes profile maps to one Mastra
  `resourceId = "hermes:<profile>"`.
* The plugin captures `kwargs["hermes_home"]` in `do_initialize` and
  routes ALL subsequent storage paths through it. Verified by
  `tests/test_hermes_init_contract.py::test_hermes_home_kwarg_overrides_global`.
* `resourceFor(profile)` is the ONLY way the server side derives a
  resource id; every server route accepts `profile` and never reads
  it from anywhere except the request body or query string.
* Mastra `Memory.recall({resourceId})` filters at the DB layer; we
  never have to filter ourselves.

## 8. Profile continuity strategy

* `do_turn_start` synthesises a profile-switch signal when Hermes
  doesn't fire one. It logs the lineage observation and clears the
  recall cache so the next `prefetch` rebinds to the new profile.
* `do_session_switch` carries lineage forward via a "Session continues
  from prior thread {old}" observation when `parent_session_id` is
  set, so the new thread has provenance even though it has no
  history yet.

## 9. Session continuity strategy

* Working memory scoped to `resource` keeps user-level facts surviving
  every session switch.
* Observational memory scoped to `thread` keeps session-specific
  observations contained.
* `lastMessages: 20` is the verbatim history cap inside Mastra; the
  Observer summarises everything older into observations.

## 10. Caching strategy

* `RecallCache` — in-process, thread-safe, last-known snapshot.
* `_in_flight` flag coalesces concurrent refreshes into one HTTP
  round-trip.
* Cache is cleared on profile switch, `/reset`, or `on_session_switch`
  with `reset=True`.

## 11. Invalidation strategy

| Trigger                              | Action                       |
|--------------------------------------|------------------------------|
| Profile change                       | clear cache, enqueue refresh |
| Session switch with reset=True       | clear cache, enqueue refresh |
| `/api/memory/observation` write      | server-side; client refreshes via next `prefetch` |
| `do_pre_compress`                    | enqueue flush + refresh      |

## 12. Performance instrumentation

* `tests/test_non_blocking_hooks.py` — every hot-path hook returns
  in < 100 ms even under simulated 1 s server latency.
* `scripts/benchmark.py` — measures hot-path latency, runner
  throughput, cache freshness; output → `references/last-benchmark.md`.
* `scripts/compare_providers.py` — measures the same against 8 other
  shipped memory provider plugins; output →
  `references/provider-comparison.md`.

## 13. Rollout strategy

* Plugin is opt-in via `memory.provider: mastra` in `~/.hermes/config.yaml`.
* Existing users keep their built-in memory; switching is purely
  additive (working memory + observational memory layered on top).
* No migration of existing MEMORY.md / USER.md content is required;
  the on_memory_write hook back-fills as edits happen.

## 14. Risks

* Bun process unavailability on first run — mitigated by best-effort
  background bring-up; provider transparently no-ops when `_alive(p)`
  is false. Verified in `provider_lifecycle._alive`.
* Cross-profile leakage if `do_initialize` is skipped — mitigated by
  `_alive(p)` check that requires `_client` and `_thread` and
  `_profile` to be set.
* Latency spikes under high write load — bounded by `async_runner`
  queue size (256) and *drop-oldest* policy, so the producer never
  stalls.

## 15. Unknowns

* Mastra Memory may emit telemetry through `@mastra/core/observability`
  in future versions; if it adds default exporters, we may need to
  silence them by default to honour the "no observability collisions"
  invariant. Tracked as an upstream watch in `references/upstream-watch.md`.

## 16. Disconfirming evidence

* The Hermes plugin runtime *already* isolates plugin failures via
  `try/except` in `MemoryManager` and `invoke_hook`. Tests we add are
  *contract* tests, not bug fixes.
* Mastra Memory already enforces `resourceId` filtering at the storage
  layer. Tests we add are contract tests that *we* always pass the
  right resourceId, not that Mastra filters correctly.

## 17. Acceptance criteria

* All 30 acceptance criteria of the parent prompt met.
* Local CI gate (`mise run quality`) passes.
* New plugin-clash + plugin-non-interference + plugin-load-order +
  plugin-failure-isolation tests pass.
* Existing 439-test suite stays green.
* Code-size policy stays satisfied.

## 18. Plugin correctness strategy

* Tests under `tests/test_plugin_*.py` form a contract suite executed
  by `mise run test`.
* Hot-path budget enforced by `tests/test_non_blocking_hooks.py`.
* Profile/tenant isolation enforced by `tests/test_profile_switch.py`
  and `tests/test_hermes_init_contract.py`.

## 19. Plugin non-interference strategy

* No mutation of kwargs passed to hooks.
* No monkey-patching of agent core modules.
* All resources stamped with stable namespace prefixes.
* Test plugins under `tests/helpers/` (created in BOOTSTRAP) emulate
  real plugin behaviours and assert nothing under our control mutates
  them.

## 20. Compatibility matrix summary

See `analysis/plugin-compatibility-matrix.yaml`. 8 plugins compatible,
6 plugins incompatible (all are mutually-exclusive memory providers
per Hermes' single-external-provider rule).

## 21. Clash-prevention strategy

See `analysis/plugin-clash-analysis.md`. 24 distinct resources audited;
zero high-risk, one medium-risk (intentional `HERMES_HOME` env
propagation), four low-risk, nineteen none-risk.
