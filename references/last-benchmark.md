# Plugin benchmarks

_Generated 2026-05-06 11:00:43_


## Q1+Q2 — Hot-path latency (plugin vs naive sync baseline)

Naive baseline = what each hook would take if it awaited the HTTP call inline.
Slow-client column injects 500ms HTTP latency into the mock client.

| Hook | p50 (fast) | p95 (fast) | p99 (slow 500ms HTTP) | naive baseline |
|------|-----------:|-----------:|----------------------:|---------------:|
| `prefetch` | 0.00 ms | 0.00 ms | 0.02 ms | 500 ms |
| `sync_turn` | 0.00 ms | 0.00 ms | 0.02 ms | 500 ms |
| `on_pre_compress` | 0.01 ms | 0.01 ms | 0.03 ms | 500 ms |
| `on_session_end` | 0.00 ms | 0.00 ms | 0.03 ms | 500 ms |
| `on_memory_write` | 0.00 ms | 0.00 ms | 0.02 ms | 500 ms |
| `on_delegation` | 0.00 ms | 0.00 ms | 0.02 ms | 500 ms |

## Q3 — Background queue throughput

**Sustained** (paced producer; workers keep up):
- Delivered **5,000** of 5,000 in 0.327s = **15,298 jobs/sec**
- Delivery rate: **100.0%**

**Burst overflow** (producer floods, queue drops oldest):
- Enqueue cost: **1.79 µs/job** (17.94 ms total for 10,000 submits)
- Delivery rate: **2.64%** — 264 delivered before drop-oldest kicked in
- _Bounded queue drops oldest when full (size=256). A delivery_rate <100% under burst is the documented overflow policy — producers stay non-blocking by dropping pending writes._


## Q4 — Cache freshness over 200-turn loop (80ms recall latency)

- Cache hit rate: **93.5%** (187 hit / 13 miss)
- Background recalls completed during run: **16**


## Resilience — fault-injected hot-path latency

- p99: **0.03 ms** under fault injection
- Failures escaping hooks: **0**

## Chaos loop

- `mise run chaos` passed **10/10** consecutive runs on 2026-05-06.


_Reproduce: `mise run bench` or `mise run bench:resilience`. Raw numbers in `references/last-benchmark.json`._
