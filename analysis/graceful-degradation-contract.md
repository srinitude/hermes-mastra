# Graceful-degradation contract

Generated for ANALYSIS task A07.

## State machine (existing circuit_breaker.py)

- States: `closed` → `open` → `half-open` → `closed`.
- Transitions:
  - `closed` → `open` on 3 consecutive failures.
  - `open` → `half-open` after 30 s cooldown (no traffic during cooldown).
  - `half-open` → `closed` on 1 successful probe.
  - `half-open` → `open` on 1 failed probe.

## Per-hook behaviour when the circuit is OPEN

| Hook                | Behaviour on OPEN circuit                                                            |
| ------------------- | ------------------------------------------------------------------------------------ |
| `prefetch`          | return cached/empty (no HTTP); the agent loop still runs                              |
| `queue_prefetch`    | drop with a metric; do not spawn the worker thread                                   |
| `sync_turn`         | drop the message into a disk replay log under `~/.hermes/data/mastra/replay-*.ndjson`; flush on `closed` |
| `on_pre_compress`   | return `""` so context_compressor falls back to its default summarisation path       |
| `on_session_end`    | drop with a metric; replay log catches the durable summary on recovery               |
| `on_memory_write`   | local MEMORY.md / USER.md disk write STILL succeeds; Mastra mirror enqueued for replay |
| `on_session_switch` | update local cached state; never block                                               |
| `on_delegation`     | drop with a metric; replay log catches it                                            |
| `on_turn_start`     | unaffected (no HTTP)                                                                  |
| `system_prompt_block` | unaffected                                                                          |

## Hard rules

- A Hermes turn MUST always complete even when the Mastra server is hard down.
- A Mastra outage MUST NOT propagate as a Python exception out of any
  MemoryProvider hook; every hook must catch and degrade.
- The breaker MUST open within 1 s of the third consecutive failure.
- The breaker MUST close within 30 s of recovery (one successful probe).
- The replay log MUST be capped (default 16 MiB) and rolled when full;
  oldest entries dropped first with a warning metric.

## Validation contract

- R07 / `tests/test_circuit_breaker_integration.py::test_red_graceful_degradation`
  kills the test server mid-turn, runs 5 more turns, asserts:
  - every turn completes,
  - MEMORY.md / USER.md writes still land,
  - prefetch returns "" within 5 ms,
  - the circuit opens within 1 s and closes within 30 s after the server returns.
- G04 wires the breaker into every client method and adds the disk
  replay log; flips R07 from RED to GREEN.

## Telemetry

- Every breaker transition emits a structured log line via G11 telemetry:
  `{ts, op:"circuit", state:"open|half-open|closed", reason, consecutive_failures}`.
- Every replay-log entry carries `{ts, op, resource_id, attempt_count, original_payload_hash}`.
