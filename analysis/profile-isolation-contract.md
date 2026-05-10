# Profile-isolation contract

Generated for ANALYSIS task A06.

## Derivation rule

Every Mastra call MUST carry a deterministic, per-Hermes-profile `resourceId`:

```python
resource_id = f"hermes:{agent_identity or 'default'}@{Path(hermes_home).name}"
```

- Source of `agent_identity`: `MemoryProvider.initialize(session_id, agent_identity=...)` kwarg passed by Hermes at session start (`agent/memory_manager.py` contract).
- Source of `hermes_home`: `MemoryProvider.initialize(session_id, hermes_home=...)` kwarg.
- The rule is stable across restarts and identical for two sessions of the same profile.
- Two distinct hermes_home directories produce two distinct resourceIds; the
  invariant is enforced end-to-end by R08 / G02.

## Centralisation

`mastra_options.derive_resource_id(hermes_home: str, agent_identity: str | None) -> str`
is the single derivation function. Every call site below routes through it
instead of fabricating a resourceId locally.

## Required call sites (every Mastra surface must use derive_resource_id)

1. `client.observe(...)` — observation writes
2. `client.recall(...)` — recall reads
3. `client.search_observations(...)` — keyword search
4. `client.semantic_search(...)` — vector search
5. `client.get_working_memory(...)` — working memory reads
6. `client.set_working_memory(...)` — working memory writes (G00 adds this method)
7. `client.upsert_artifact(...)` — artifact writes
8. `client.artifact_history(...)` — artifact reads
9. `client.artifact_revert(...)` — artifact restore
10. `agent_observers.*` — every agent observation event
11. `tool_observers.*` — every tool observation event
12. `artifact_tools.*` — artifact tool invocations
13. `provider_lifecycle.*` — every lifecycle hook payload

## Validation contract

- R08 / `tests/test_profile_isolation.py::test_red_profile_isolation_full`
  runs two HERMES_HOME dirs (A and B), seeds 10 distinct facts in each
  via memory_tool, runs cross-session recall queries, and asserts ZERO
  cross-contamination across observe / recall / search / semantic_search
  / working_memory / artifacts.
- G02 wires every call site to `derive_resource_id` and is the GREEN
  task that flips R08 from RED to GREEN.

## Hard rules

- Never default to a global resourceId. If `derive_resource_id` cannot
  produce one (no agent_identity AND no hermes_home), the operation MUST
  raise a `ValueError("missing profile context")` rather than falling
  through to a global namespace.
- Never read another profile's working memory by handing in its
  resourceId from a different session.
