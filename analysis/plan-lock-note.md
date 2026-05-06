# Plan-lock note — R00 hard gate

The immutable contract is `hermes-mastra-resilience-and-perf-goal.md`; the runtime ledger is `hermes-mastra-resilience-and-perf-tdd-tasks.yaml`.

Before any GREEN production-code edit, the RED hard gate requires:

1. Analysis source-reality and RED manifest evidence recorded.
2. Bootstrap helpers and RED test files present and collecting cleanly.
3. Baseline `mise run quality`, `mise run bench`, `mise run compat:hermes`, and `mise run compat:mastra` observed.
4. R00 committed.
5. Every RED test committed and observed failing for the right reason.

No production file under `provider_lifecycle.py`, `async_runner.py`, `recall_cache.py`, `client.py`, or `server/src/*` is edited by this kickoff note.
