# Parity matrix — hermes-mastra vs. bundled providers

Generated for ANALYSIS task A03 (goal: mastra-first-class-memory-provider-hermes).

Inputs:

- `/Users/kiren/hermes-setup/memory/hermes-mastra/analysis/provider-capability-matrix.json`
- `/Users/kiren/hermes-setup/memory/hermes-mastra/analysis/mastra-current-surface.json`

Each row is a dimension Hermes care about; the win rule is the contract
the goal's RED phase will assert. Targets quantified per `win_rule`.

| ID  | Dimension                              | Bundled max provider             | Bundled max score (today)          | Mastra score (May 2026 audit)            | Target                                                      |
| --- | -------------------------------------- | -------------------------------- | ---------------------------------- | ---------------------------------------- | ----------------------------------------------------------- |
| D01 | prefetch p50 ms                        | holographic                      | <5 ms (sync sqlite)                | TBD (A05 baseline)                       | <=5 ms cache-only                                           |
| D02 | prefetch p99 ms                        | honcho                           | bg-thread, p99 <100 ms warm        | TBD                                      | <=10 ms cache-only (HTTP runs in queue_prefetch)            |
| D03 | sync_turn durability                   | mem0                             | server extraction within 1 thread  | observation_messages + reflector enqueue | 100% within 30 s window                                     |
| D04 | semantic recall@5                      | max(mem0, honcho, supermemory)   | TBD by R01 harness                 | 0 hits (audit)                           | recall@5 ≥ bundled_max + 0.10                               |
| D05 | keyword search precision@5             | openviking                       | tiered FTS                         | FTS5 over observation_messages           | precision@5 ≤ 1.1× bundled_max                              |
| D06 | cross-session recap hit rate           | honcho                           | TBD by R01                         | 0%                                       | ≥ 80% Mastra-first wins                                     |
| D07 | profile isolation                      | all                              | 100% (per resource_id)             | partial (default fallback in some calls) | 100%                                                        |
| D08 | on_pre_compress extraction density     | max(holographic, hindsight)      | TBD by R04                         | minimal/empty                            | density ≥ 1.2× bundled_max                                  |
| D09 | on_session_end summary quality         | max(honcho, hindsight, supermem) | TBD by R05                         | TBD                                      | strictly more facts & 0 PII; ≤ 1.2× token cost              |
| D10 | on_memory_write mirror coverage        | max(supermem, retaindb, openvik) | fully overridden                   | observation only                         | 100% dual-write MEMORY.md/USER.md ⇄ Mastra working memory   |
| D11 | tool schema count                      | retaindb                         | 10                                 | 8                                        | ≥ 12 (add profile/synthesize/browse/add_fact)               |
| D12 | graceful degradation under outage      | all (circuit breakers)           | fail closed; turns complete        | partial wiring                           | <1 s open; <30 s recover; turns always complete             |
| D13 | credential surface (zero-cfg vs key'd) | holographic                      | 0 credentials                      | Venice (Observer/Reflector) + GoogleAI   | docs + fallback to keyword-only if embedder unavailable     |

## Provenance

- Bundled per-provider hooks/tools/lines: provider-capability-matrix.json.
- Mastra current hooks/tools/client/server: mastra-current-surface.json.
- Latency contract (D01/D02): formalised in A05.
- Profile isolation contract (D07): formalised in A06.
- Graceful degradation contract (D12): formalised in A07.

## Win rule legend

- "≥ bundled_max + N" = absolute delta on the same metric (recall, hit rate).
- "≤ K×" = ratio cap on a cost metric (token, latency).
- "100%" = full coverage required (no exceptions).
