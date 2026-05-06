# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2026-05-06

### Added

- **Thorough `./README.md` refresh.** Reconciles every section with the shipped code (provider hooks, tools, CLI, config surface, mise tasks); adds an explicit "Resilience guarantees" section enumerating every promise; documents every new resilience config knob and the new `mise run chaos` / `mise run bench:resilience` tasks; refreshes the install block to match `plugin.yaml` v0.2.2; embeds the latest measured benchmark numbers.
- **Resilience layer.** Added fail-closed `CircuitBreaker`, stdlib response guards, bounded observation deduplication, profile/thread LRU recall cache, server-supervisor restart policy, filesystem-safe write helpers, and cron/partial-init no-op paths.
- **Fault-injection gates.** Added the resilience RED suite plus `tests/test_chaos_resilience.py`, `mise run chaos`, and `mise run bench:resilience`.
- **Server hard-fail boundary.** Bun now declares `idleTimeout`, a structured `error` handler, and `/api/memory/healthz` probe data.

### Changed

- `MastraClient` now validates response payloads before use, rotates auth on 401 from `auth_token_env`, deduplicates repeated observations, and runs HTTP calls through the circuit breaker.
- Capacity hints now recommend `mastra_observe` only when built-in memory is >=50% and observations are below the action floor; explicit recall phrasing with an empty cache recommends `mastra_search`.
- `references/last-benchmark.{json,md}` now includes fault-injected resilience numbers.
- `plugin.yaml` bumped to `0.2.2`; `/health` route in `server/src/routes-memory.ts` reports the same version.

### Verified

- `mise run test:py` passes (648 tests).
- `mise run chaos` passes.
- `mise run bench:resilience` passes with fault-injected hot-path p99 **0.03 ms** and 0 escaped hook failures.
- `mise run compat:hermes` and `mise run compat:mastra` pass against cached upstream sources.

[0.2.2]: https://github.com/srinitude/hermes-mastra/releases/tag/v0.2.2

## [0.2.1] - 2026-05-05

### Fixed

- **Import context bug under the real Hermes loader.** `server_manager.py` and `server_process.py` used bare absolute imports (`from server_config import …`) that worked under pytest (because `conftest.py` adds the plugin root to `sys.path`) but raised `ModuleNotFoundError` under Hermes' actual loader, which loads the plugin as `plugins.memory.mastra.<module>`. The downstream effect was silent: `is_available()` swallowed the `ImportError` and returned `False`, so the plugin appeared healthy in tests yet refused to activate at runtime. Fixed by wrapping the sibling imports in the `try: from .X import …; except ImportError: from X import …` pattern already used by every other module in this codebase. Caught by manual smoke testing v0.2.0 on a clean install — see `scripts/manual-smoke.sh`.

### Added

- **`tests/test_hermes_loader_imports.py`** (5 tests) — RED-then-GREEN regression guard for the import-context bug. Every assertion runs in a fresh subprocess that simulates the Hermes loader (synthetic `plugins.memory.mastra` package via symlink, plugin root NOT on `sys.path`) so in-process state can never leak into the rest of the suite. Includes a smoke test that calls `plugins.memory.load_memory_provider('mastra')` through Hermes' actual venv.
- **`scripts/manual-smoke.sh`** — one-shot 9-phase manual smoke test: pre-flight → sync → activate → server bring-up → tool surface → round-trip → tenant isolation → in-process hook roundtrip with 100 ms budget enforcement → tear-down. Distinct exit codes per phase (2=preflight, 3=server, 4=load, 5=tenant-leak, 6=budget) for CI integration.

### Verified live

- All 9 smoke phases pass against a freshly-installed plugin: every hot-path hook returns in **< 0.1 ms** (`system_prompt_block` 0.03 ms · `prefetch` 0.07 ms · `sync_turn` / `on_session_switch` / `on_pre_compress` / `on_memory_write` all 0.01 ms).
- **Tenant isolation verified end-to-end on a live Bun server**: writes to `hermes:smoke-default` and `hermes:smoke-other` stayed in their own resourceIds; cross-profile keyword search returned 0 hits; working-memory values per profile remained distinct. No leakage at any boundary.
- `mise run quality` passes (560 tests, format · lint · typecheck · security:audit · validate).

[0.2.1]: https://github.com/srinitude/hermes-mastra/releases/tag/v0.2.1

## [0.2.0] - 2026-05-05

### Added

#### Plugin contract suite (113 new tests)

- **`tests/test_plugin_clash.py`** (18 tests) — locks namespace ownership for every plugin-owned resource: plugin id, provider name, tool prefix (`mastra_*`), env vars (`MASTRA_*`), LibSQL store id (`hermes-mastra`), resource id format (`hermes:<profile>`), recall-cache instance scoping, async-runner thread names, logger names, and a no-monkey-patch guard.
- **`tests/test_plugin_non_interference.py`** (8 tests) — proves coexistence with arbitrary contract-valid Hermes plugins: hook callbacks never mutate kwargs, lifecycle events propagate to other plugins, foreign storage namespaces are untouched, no command/tool collisions.
- **`tests/test_plugin_load_order_permutations.py`** (54 parametrized cases) — proves load-order invariance across every permutation of `{mastra, observer, command, lifecycle}` registrars.
- **`tests/test_plugin_failure_isolation.py`** (7 tests) — proves failures are contained in both directions: our hooks never propagate exceptions; foreign plugin failures don't block our callbacks.
- **`tests/test_retrieval_relevance.py`** (8 tests) — proves prefetch returns empty when cache is empty, announces the active profile, clears stale cache on session-id mismatch, on profile flip, and on `reset=True`, and writes lineage observations on session continuation.
- **`tests/helpers/fake_plugins.py`** — in-test fakes (`install_observer_plugin`, `install_command_plugin`, `install_failing_plugin`, `install_storage_writer`, `install_lifecycle_plugin`) emulate real Hermes plugin behaviours without shipping production-mock code.

#### Analysis artifacts (`analysis/`)

- `source-analysis.md` — Hermes + Mastra primitives, lifecycle diagrams, performance-sensitive paths, risks/unknowns/disconfirming evidence.
- `local-ci.md` — canonical local CI/CD command surface (`mise run quality`).
- `plugin-contract.md` — 17-section operational plugin contract derived from Hermes source.
- `plugin-clash-analysis.md` — 24-resource collision matrix with per-resource owner, namespace, risk, prevention strategy, and test coverage.
- `plugin-compatibility-matrix.yaml` — 8 compatible plugins, 6 mutually-exclusive memory peers, explicit `unknown_plugins_policy`.
- `memory-performance-plan.md` — read/write paths, ranking, compaction, isolation, caching, instrumentation, rollout, risks, acceptance criteria.
- `tdd-task-list.yaml` — dynamic BOOTSTRAP/RED/GREEN/REFACTOR task ledger.
- `research/firecrawl-url-map.yaml` — relevance-classified URL inventory across 5 documentation roots (Hermes docs + Mastra docs/reference/models/guides), each mapped at `limit=5000`.
- `research/{hermes,mastra}-docs-knowledge.yaml` — extracted findings tagged by source-classification (`primary_source_claim` / `secondary_source_claim` / `source_inference` / `implementation_inference` / `common_knowledge`).
- `research/memory-integration-findings.md` — where Hermes and Mastra contracts agree, disagree, and how the boundary is reconciled.
- `final-report.md` — summary, evidence, tests added, CI commands run, performance measurements, behaviour validated, files changed, risks/unknowns, counter-arguments, per-conclusion confidence, and the 30-row acceptance-criteria checklist.

#### Documentation maps

- `references/mastra-reference-map.json` (323 links), `references/mastra-models-map.json` (128), `references/mastra-guides-map.json` (63) — Firecrawl `/v1/map` snapshots at `limit=5000`, complementing the existing `mastra-docs-map.json` and `hermes-docs-map.json`.

### Changed

- `references/last-benchmark.{json,md}` — refreshed; every hot-path hook returns under 0.2 ms p99 even with 500 ms simulated HTTP latency. Background queue throughput 16,376 jobs/sec sustained; 93 % cache hit rate over a 200-turn loop.

### Verified

- `mise run quality` passes (format · lint · typecheck · 552 tests · security:audit · validate).
- `mise run compat` confirms all 16 Hermes `MemoryProvider` hooks and all 8 used `@mastra/memory` APIs are present in upstream HEAD.
- Every new test file respects the 200 LOC / 30 LOC-per-construct / depth-3 code-size policy (200/200 policy checks pass).
- Zero changes to production Python or TypeScript source — the plugin's existing `0.1.0` implementation already met every contract; the upgrade is delivered as enforceable regression-guard tests.

[0.2.0]: https://github.com/srinitude/hermes-mastra/releases/tag/v0.2.0

## [0.1.0] - 2025-05-03

### Added

#### Mastra-Backed Tools (8)

- **mastra_recall** — Retrieve stored memories for the active profile using Mastra's memory provider.
- **mastra_search** — Keyword-based search across profile-isolated memory entries.
- **mastra_semantic_search** — Vector / semantic search over embedded memory content via Mastra.
- **mastra_observe** — Trigger an observation cycle that feeds into the Observer/Reflector pipeline.
- **mastra_working_memory** — Read and write short-lived working-memory slots scoped to the current session.
- **mastra_artifact_get** — Fetch a named artifact (identity file, prompt block, etc.) by ID.
- **mastra_artifact_history** — Retrieve the full version history of a stored artifact.
- **mastra_artifact_revert** — Revert an artifact to a prior version from its history.

#### Per-Profile Isolation

- All memory, artifact, and working-memory data is isolated per profile using **libSQL** as the backing store.
- Each profile receives its own namespace, preventing cross-profile data leakage.

#### Observer / Reflector Agent Roles

- **Observer** role watches agent interactions and extracts salient facts, decisions, and context into memory.
- **Reflector** role periodically reviews accumulated observations, consolidating and pruning memory to maintain relevance.

#### Non-Blocking Hook Contract

- Hooks execute under a strict **5-second deadline**.
- Hook results are returned asynchronously so the host agent loop is never blocked by a slow provider.

#### Capacity-Aware System Prompt Hints

- When stored memory or artifact volume exceeds **50%** of the configured capacity, the system automatically injects hints into the agent's system prompt encouraging consolidation or archival.

#### Versioned Identity-File Storage

- Identity files are stored as versioned **Mastra prompt-blocks**, enabling deterministic retrieval of any prior version and safe atomic updates.

#### Optional Mastra-Aware ContextEngine Wrapper

- A drop-in `ContextEngine` wrapper is provided that transparently routes memory operations through Mastra when the plugin is installed, while falling back to the built-in engine otherwise.

#### Bun Server

- Production-ready Bun server exposing **17 routes** for tool invocations, health checks, profile management, artifact CRUD, and memory queries.

#### Code-Size Policy Enforcement

- Automated policy checks reject PRs or builds that exceed the configured code-size budget, keeping the plugin lightweight.

#### Test Suite

- **425+ tests** covering tool contracts, isolation boundaries, hook deadlines, capacity hints, artifact versioning, server routes, and the ContextEngine wrapper.

[0.1.0]: https://github.com/srinitude/hermes-mastra/releases/tag/v0.1.0
