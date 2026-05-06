# RED Test Manifest — resilience and performance contract

This manifest is derived from `hermes-mastra-resilience-and-perf-goal.md` Phase 1 and maps every acceptance criterion to a failing RED test and the minimum GREEN module expected to satisfy it.

| RED id | Test file | Contract behavior | Acceptance criteria | GREEN modules |
|---|---|---|---|---|
| R01 | `tests/test_resilience_hot_path.py` | Every hot-path hook returns below 100 ms p99 under slow client, dead server, queue saturation, recall-cache rotation, and profile flip. | AC 3, 8, 9 | `recall_cache.py`, `provider_lifecycle.py`, `server/src/index.ts`, `scripts/benchmark.py` |
| R02 | `tests/test_circuit_breaker.py` | Consecutive client failures open a breaker, no-op calls stay fast, cooldown half-opens, success closes. | AC 3, 8, 12 | `circuit_breaker.py`, `client.py`, `server_config.py` |
| R03 | `tests/test_server_supervisor.py` | Bun crash is detected within a health interval and restarted with bounded exponential backoff. | AC 10 | `supervisor.py`, `server_process.py`, `server_manager.py` |
| R04 | `tests/test_observation_dedup.py` | Duplicate `(thread, profile, kind, normalized_text)` observations are written once; changed fields write again. | AC 8 | `observation_dedup.py`, `client.py`, `provider_lifecycle.py` |
| R05 | `tests/test_profile_flip_safety.py` | A profile flip clears recall cache synchronously and never returns previous-profile observations. | AC 9 | `recall_cache.py`, `provider_lifecycle.py`, `lifecycle_helpers.py` |
| R06 | `tests/test_filesystem_resilience.py` | PID, log, and config writes degrade to logged no-ops under read-only or denied paths. | AC 11 | `server_config.py`, `server_process.py` |
| R07 | `tests/test_response_validation.py` | Non-JSON, partial JSON, wrong-schema, and oversized responses are rejected at the boundary. | AC 12 | `response_guard.py`, `client.py` |
| R08 | `tests/test_runner_saturation.py` | Pathological queue overflow increments a drop counter, keeps producer latency fast, and logs one burst. | AC 8 | `async_runner.py` |
| R09 | `tests/test_cron_context_safety.py` | Cron initialization skips server bring-up, leaves hooks no-op, and hides Mastra tools. | AC 13 | `provider_lifecycle.py`, `__init__.py` |
| R10 | `tests/test_partial_init.py` | Failure after `_profile` but before `_client` leaves provider deterministic no-op and re-init works. | AC 8 | `provider_lifecycle.py`, `lifecycle_helpers.py` |
| R11 | `tests/test_auth_rotation.py` | A 401 after `auth_token_env` changes lazily rebuilds the HTTP client and closes the old one. | AC 8 | `client.py`, `server_config.py` |
| R12 | `tests/test_capacity_hint_smartness.py` | `_capacity_hint` recommends `mastra_observe` vs `mastra_search` from capacity, observation count, and recall intent. | AC 14 | `__init__.py`, `memory_rules.py` |
| R13 | `tests/test_lineage_prefetch.py` | `on_session_switch(parent_session_id=...)` warms the new thread cache with parent observations once. | AC 8, 9 | `provider_lifecycle.py`, `lifecycle_helpers.py`, `recall_cache.py` |
| R14 | `tests/test_code_size_policy.py` | New resilience modules are covered by LOC, construct, nesting, and cognitive-complexity policy. | AC 7 | `tests/test_code_size_policy.py`, all new modules |

## Acceptance coverage

- AC 1, 2, 6, 7 are enforced by `mise run quality`, targeted pytest commands, compat gates, and the policy test.
- AC 3, 4, 5 are enforced by R01 plus `mise run bench`, `mise run bench:resilience`, and `mise run chaos` in REFACTOR.
- AC 8 through AC 14 map directly to R01–R14 above.
- AC 15 is enforced by REFACTOR docs tasks after benchmark numbers are captured.
- AC 16 is enforced by the final squash task and git history audit.
- AC 17 is enforced by analysis/source-validation evidence and final documentation citation checks.
