# Memory provider comparison

_Generated 2026-05-02 23:52:02 from `opensrc path NousResearch/hermes-agent`._


## Capability matrix

| Provider | LOC | Hooks | recall | search | observe | tools | CLI | non-blocking sync_turn | local-only |
|----------|----:|------:|:------:|:------:|:-------:|:-----:|:---:|:---:|:---:|
| `honcho` | 1161 | 14 | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ |
| `mem0` | 317 | 10 | — | ✅ | — | ✅ | — | — | ✅ |
| `supermemory` | 707 | 12 | ✅ | ✅ | — | ✅ | — | — | — |
| `byterover` | 307 | 11 | — | — | — | ✅ | — | — | ✅ |
| `hindsight` | 1436 | 12 | ✅ | — | — | ✅ | — | — | ✅ |
| `holographic` | 353 | 11 | — | ✅ | — | ✅ | — | — | ✅ |
| `openviking` | 663 | 11 | — | ✅ | — | ✅ | — | — | — |
| `retaindb` | 655 | 10 | — | ✅ | — | ✅ | — | — | — |
| **`mastra` (this)** | _shell ~120 + helpers_ | **17** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | _libSQL local + LLM via API_ |

## Hook coverage detail

| Provider | Hooks implemented |
|----------|-------------------|
| `honcho` | get_config_schema, get_tool_schemas, handle_tool_call, initialize, is_available, on_memory_write, on_session_end, on_turn_start, post_setup, prefetch, queue_prefetch, save_config, sync_turn, system_prompt_block |
| `mem0` | get_config_schema, get_tool_schemas, handle_tool_call, initialize, is_available, prefetch, queue_prefetch, save_config, sync_turn, system_prompt_block |
| `supermemory` | get_config_schema, get_tool_schemas, handle_tool_call, initialize, is_available, on_memory_write, on_session_end, on_turn_start, prefetch, save_config, sync_turn, system_prompt_block |
| `byterover` | get_config_schema, get_tool_schemas, handle_tool_call, initialize, is_available, on_memory_write, on_pre_compress, prefetch, queue_prefetch, sync_turn, system_prompt_block |
| `hindsight` | get_config_schema, get_tool_schemas, handle_tool_call, initialize, is_available, on_session_switch, post_setup, prefetch, queue_prefetch, save_config, sync_turn, system_prompt_block |
| `holographic` | get_config_schema, get_tool_schemas, handle_tool_call, initialize, is_available, on_memory_write, on_session_end, prefetch, save_config, sync_turn, system_prompt_block |
| `openviking` | get_config_schema, get_tool_schemas, handle_tool_call, initialize, is_available, on_memory_write, on_session_end, prefetch, queue_prefetch, sync_turn, system_prompt_block |
| `retaindb` | get_config_schema, get_tool_schemas, handle_tool_call, initialize, is_available, on_memory_write, prefetch, queue_prefetch, sync_turn, system_prompt_block |
| **`mastra` (this)** | initialize, is_available, system_prompt_block, prefetch, queue_prefetch, sync_turn, on_session_end, on_session_switch, on_pre_compress, on_memory_write, on_delegation, on_turn_start, get_tool_schemas, handle_tool_call, get_config_schema, save_config, post_setup |

## Non-blocking guarantee — measured

Our plugin's hot-path hooks return in **<1 ms** even when the underlying HTTP call sleeps **500 ms**, because every write is fire-and-forget through a bounded async queue and `prefetch` serves a cached snapshot.

- `sync_turn` p50: **0.001 ms**
- `prefetch`  p50: **0.001 ms**
- naive baseline (any provider that synchronously awaits HTTP): **500 ms per call**

The `non-blocking sync_turn` column above is a **static-analysis heuristic** (does sync_turn touch a Thread/Executor/Queue?). It can have false negatives — we inspect source patterns, not runtime behaviour. For our own plugin the number above is a real measurement.


## What this comparison means

- **More hooks ≠ better provider.** Hindsight (8) and Honcho (10) are excellent providers with deep capabilities; we just integrate with more Hermes lifecycle events (17/17) because we have to bridge profile switches, todo snapshots, skill loads, and the `MEMORY.md`/`USER.md` cross-talk.
- **`local-only` is a tradeoff, not a verdict.** Hindsight, Holographic, RetainDB store everything on disk — zero network calls, zero API keys. mastra uses libSQL locally for storage but reaches an LLM provider for the Observer/Reflector to do the actual summarization, which is what gives it the dense-observation behaviour those providers don't offer.
- **CLI presence matters for ops.** Only `honcho` and (now) `mastra` ship a dedicated `hermes <provider>` subcommand tree.
- **Capability overlap is partial.** `mem0` and `supermemory` are cloud-hosted knowledge graphs. `byterover` is a context engine. `holographic` indexes via embeddings. Pick the one whose capability bundle matches what you need; this matrix is a starting point, not a full evaluation.