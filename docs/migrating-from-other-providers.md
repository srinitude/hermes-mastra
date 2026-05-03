# Migrating to mastra

If you're running another Hermes external memory provider today, here's how to switch — and what changes when you do.

## TL;DR for each provider

| Coming from | Migration cost | What you keep | What's new |
|-------------|----------------|---------------|------------|
| `honcho` (cloud knowledge graph) | low — both expose recall + search | nothing in Honcho cloud transfers | Observer/Reflector summarization, per-profile isolation, three-tool surface, `/mastra` skill |
| `mem0` (cloud knowledge graph) | low — keyword-search compatible | nothing in mem0 cloud transfers | dense observation log instead of fact extraction; local libSQL storage |
| `supermemory` (cloud) | low | nothing in supermemory cloud transfers | local-first storage, Observer/Reflector pipeline |
| `byterover` (context engine, local) | medium — different mental model | local files moved aside | full memory provider semantics, not just context-engine output |
| `hindsight` (local SQLite) | medium | local DB stays put (read-only fallback for older data) | Observer-driven distillation; current state is raw history |
| `holographic` (local embeddings) | medium | local indexes stay put | distilled observations + LLM-native recall instead of vector top-k |
| `openviking` (cloud) | low | nothing in openviking cloud transfers | local libSQL storage, no cloud key required for storage |
| `retaindb` (cloud) | low | nothing in retaindb cloud transfers | same |

> No automated data migration ships today — all providers store their state in their own format. Old data stays put under `~/.hermes/` (different paths) and you can read it with the previous provider's CLI if needed. Mastra starts a fresh observation log when activated.

## Step-by-step

### 1. Snapshot what's currently in built-in memory

Before switching providers, dump what's in `MEMORY.md` and `USER.md` so you can re-add the durable bits to mastra if needed:

```bash
cat ~/.hermes/memories/MEMORY.md
cat ~/.hermes/memories/USER.md
```

The first session after activating mastra will automatically snapshot these into the observation log via `do_memory_snapshot`, so this is mostly insurance.

### 2. Stop the old provider's services

Each provider has its own lifecycle. Common ones:

```bash
# honcho
hermes honcho shutdown

# mem0 / supermemory / openviking / retaindb
# These are cloud — no local processes to stop. The plugin just stops being called.

# hindsight / holographic / byterover
# Local-only — no daemon to stop.
```

### 3. Activate mastra

```bash
hermes plugins install srinitude/hermes-mastra
hermes config set memory.provider mastra

# One-time: install Bun deps + start the local server
hermes mastra setup

# Verify
hermes memory status        # → "Provider: mastra ← active"
hermes mastra status     # → server health probe
```

### 4. (Optional) Re-add durable facts

If you had hand-curated facts in the old provider that you want carried over, re-add them via the `mastra_observe` tool from any agent session — or import them programmatically:

```python
import client
c = client.client_from_env()
c.write_observation(
    thread="migration-import",
    profile="default",
    text="Long-form fact carried over from hindsight ...",
    kind="migration",
)
```

The Observer will pick these up and merge them into the next reflection pass.

### 5. (Optional) Coexist for a while

Hermes only allows one external memory provider at a time, so coexistence isn't possible at runtime. But you can **export** from the old provider before switching:

| Provider | Export command |
|----------|----------------|
| `honcho` | `hermes honcho export > backup.jsonl` |
| `hindsight` | `cp ~/.hermes/hindsight.db backup.db` |
| `holographic` | `cp -r ~/.hermes/holographic backup/` |
| Cloud providers | check each provider's web console |

Save the export somewhere durable. mastra won't read it directly, but if you ever decide to roll back, you have the data.

## What changes mentally

### What you gain

- **Observer/Reflector compression.** No other provider runs two LLM agents in the background to distill turns into a dense observation log. You get summaries that survive `/compress` and that future sessions read instantly via the recall cache.
- **Per-profile resource isolation.** Hermes profiles map cleanly to Mastra `resourceId`s. Every profile that activates the plugin gets its own observation namespace under one shared Bun server with zero cross-leakage.
- **Eight explicit memory tools** (`mastra_recall`, `mastra_search`, `mastra_semantic_search`, `mastra_observe`, `mastra_working_memory`, `mastra_artifact_get`, `mastra_artifact_history`, `mastra_artifact_revert`) plus the existing `session_search` — the agent gets clear guidance on which to use for each kind of question. Per-tool spec: [`README.md → Tools the agent gets`](../README.md#tools-the-agent-gets).
- **Capacity-aware system prompt.** When `MEMORY.md` or `USER.md` is ≥50% full, the system prompt adds a hint telling the agent to use mastra for overflow.
- **Bundled `SKILL.md`.** `/mastra` works in any Hermes session.

### What you give up (or gain by losing)

- **No knowledge graph.** mem0/honcho extract entities and edges; mastra operates on natural-language observations. If your workflow leans on graph queries (`MATCH (a)-[r]->(b)`-style), stay on mem0/honcho.
- **No semantic vector search.** holographic gives you embedding-based similarity. mastra's `_search` is substring/keyword. If you need fuzzy semantic recall, stick with holographic or layer it on top.
- **No cloud-hosted history.** mem0/supermemory/honcho/openviking/retaindb give you cross-machine sync via their cloud. mastra stores everything locally in libSQL — that's a feature for privacy/sovereignty, a regression for cross-device.
- **One LLM provider dependency.** mastra needs an OpenAI-compatible endpoint to run the Observer/Reflector. The presets cover Venice (default), OpenAI, OpenRouter, Anthropic-via-OR, and `hermes-local` (reuses Hermes's own logged-in provider — zero extra keys). Hindsight/Holographic don't need this at all.

## When NOT to switch

- You depend on a knowledge-graph schema (mem0/honcho).
- You need semantic vector search (holographic).
- You need cross-device cloud sync (any cloud-backed provider).
- You're running on a machine where Bun isn't installable (mastra requires it).
- Your privacy model forbids any LLM call leaving your network and you can't run a local OpenAI-compatible server (the Observer/Reflector won't run).

In those cases, mastra can still be a valuable **complement** if Hermes ever supports multiple memory providers — but today, you pick one.

## Rollback

If you switch and want to go back:

```bash
hermes config set memory.provider <old-provider>
hermes mastra server stop      # don't forget — the Bun process keeps running otherwise
```

Your old provider's state is unchanged (different file paths). The mastra observation log stays in `$HERMES_HOME/mastra.db` — wipe it later with `hermes mastra reset --profile default --yes` if you want a clean slate.

## Pre-flight checklist

Before activating mastra in production:

- [ ] `bun --version` returns ≥1.3
- [ ] `python3 --version` returns ≥3.10
- [ ] `hermes mastra status` shows `health: { ok: true }`
- [ ] At least one of `VENICE_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` is set in `~/.hermes/.env` (or you've applied the `hermes-local` preset which reuses Hermes's own provider)
- [ ] You've read [`docs/non-blocking-architecture.md`](./non-blocking-architecture.md) (if you're on a slow network — explains why hooks return in <1ms even when Mastra is laggy)
- [ ] If you're a memory-provider author: skim [`CONTRIBUTING.md`](../CONTRIBUTING.md) for our project conventions

That's it. Welcome aboard.
