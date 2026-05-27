---
name: mastra
description: "Mastra memory provider for Hermes — observation log, semantic recall, working-memory mirror, and versioned identity-file storage (SOUL/MEMORY/USER/AGENTS) backed by @mastra/memory + @mastra/libsql."
version: 1.0.0
metadata:
  hermes:
    tags:
      - memory
      - mastra
      - observability
      - recall
      - prompt-blocks
      - versioning
    category: memory
    requires_tools:
      - mastra_recall
      - mastra_search
      - mastra_semantic_search
      - mastra_observe
      - mastra_working_memory
      - mastra_artifact_get
      - mastra_artifact_history
      - mastra_artifact_revert
---

# Mastra memory provider

Cross-session memory backed by [Mastra](https://mastra.ai/docs/memory/observational-memory) — two background agents (Observer + Reflector) compress raw conversation history into a dense observation log, plus versioned storage for the agent's identity files (SOUL.md, MEMORY.md, USER.md, AGENTS.md) via Mastra's `prompt-blocks` domain.

## When to load this skill

Load this skill (or just call the tools directly) when:

- The user asks "what were we doing last time?", "remember when…", "what did I tell you about X?"
- You're starting a new session in an active project and want the durable context
- You're about to make a decision the user has weighed in on before
- A long task is about to be compressed and you want to survive the cut
- You discover a durable fact (preference, decision, correction) worth persisting
- The user asks to inspect / revert / diff `SOUL.md`, `MEMORY.md`, `USER.md`, or a project's `AGENTS.md`

## The 8 tools at a glance

The full per-tool spec — parameters, return shapes, costs, pitfalls — lives in the plugin repository README: https://github.com/srinitude/hermes-mastra#tools-the-agent-gets. Quick reference here:

### Recall + search

| Tool | Required | Returns | When |
|------|----------|---------|------|
| `mastra_recall` | — | This thread's observation log | Want fresher detail than the cached system-prompt block |
| `mastra_search` | `query` | Keyword-matched observations + their thread IDs | Cross-thread search, exact word/phrase |
| `mastra_semantic_search` | `query` | Vector-matched observations + relevance scores | Keyword failed; want synonym / paraphrase / concept matches |

### Persist

| Tool | Required | Returns | When |
|------|----------|---------|------|
| `mastra_observe` | `text` (+ optional `kind`) | `{ ok }` | Persist a manual observation: correction, decision, preference, delegation result |

### Mirror inspection

| Tool | Required | Returns | When |
|------|----------|---------|------|
| `mastra_working_memory` | — | The resource-scoped working-memory document | Audit / debug; suspect divergence from MEMORY.md |

### Versioned identity files (SOUL.md / MEMORY.md / USER.md / AGENTS.md)

| Tool | Required | Returns | When |
|------|----------|---------|------|
| `mastra_artifact_get` | `kind` | Active version of the artifact | Verify on-disk file matches the canonical version |
| `mastra_artifact_history` | `kind` | Version history (newest first) | Audit changes, diff revisions before reverting |
| `mastra_artifact_revert` | `kind`, `version` | New version with old content | Restore a prior version (history preserved — never rewinds) |

`kind` ∈ {`soul`, `memory`, `user`, `agents`}.

**Recall hierarchy.** Observations (Mastra, distilled) live above transcripts (`session_search`, raw). Reach for `mastra_*` first when you want **what was decided**; reach for `session_search` when you want **what was said**.

## Procedure

1. **System prompt block already shows you** the active profile + thread + a hint that observations are streaming in. No tool call needed for orientation.
2. **Recall first.** Call `mastra_recall` (no args) to pull the latest observation block for the current session.
3. **If recall is thin or empty**, fall back to:
   - `mastra_search` with a keyword query — observations from past threads in this profile.
   - `mastra_semantic_search` if keyword failed — vector match by meaning.
4. **If those fail**, escalate to `session_search` — full-text search of every past Hermes session transcript.
5. **Persist durable facts** via `mastra_observe` when the user corrects you, makes a decision, or states a preference. Tag with `kind="preference"`, `kind="decision"`, or `kind="correction"`.
6. **For identity-file changes**, use `mastra_artifact_get` to confirm canonical state, `mastra_artifact_history` to inspect prior versions, and `mastra_artifact_revert` to restore (history preserved — every revert appends a new version).

## Pitfalls

- **Don't observe everything.** The Observer / Reflector handle that automatically from raw turns. `mastra_observe` is for facts you want guaranteed to land — not commentary.
- **Don't expect immediate recall.** The Observer fires on token thresholds, not per-message. Several turns must accumulate before the observation log populates. Test pings won't show up.
- **Profile = isolation boundary.** Observations are tagged `resourceId = hermes:<profile>`. Switching profiles gives you a completely separate observation namespace — facts learned in one profile aren't visible from another.
- **Prefetch is cached.** The system-prompt observation block reflects the LAST cached recall, not a live query. If you need fresh data mid-turn, call `mastra_recall` directly.
- **Semantic search is conditionally available.** If the vector store isn't configured, `mastra_semantic_search` returns empty. Re-run with `mastra_search` (keyword) as the cheap fallback.
- **`mastra_working_memory` is for inspection, not routine recall.** Hermes' built-in `MEMORY.md` / `USER.md` is the canonical store and is already in the system prompt at layer 5.
- **Artifact reverts are append-only.** `mastra_artifact_revert` creates a new version with the old content. The history stays intact; nothing is destructively rewound.
- **Per-project AGENTS.md is keyed by `sha256(absolute_cwd_path)`** — you can't cross-reference one project's AGENTS.md from another working directory.

## MEMORY.md / USER.md format (entry separator)

When you do edit Hermes' built-in `MEMORY.md` or `USER.md` (via the built-in `memory` tool), entries are delimited by a single line containing only the section sign **`§`**:

```
First durable fact lives here.
§
Second durable fact lives here.
§
[mastra-rule] mastra plugin is active — keep MEMORY.md SMALL...
```

The plugin's `memory_rules.py` defines `SECTION_SEPARATOR = "\n§\n"` and uses it to split, replace, or remove individual entries without touching the rest of the file. This means:

- **Each `§`-delimited block is one independently-addressable entry** — `memory(action="remove", old_text="...")` matches by substring against a single block.
- **Use `§` (the section sign, U+00A7), not `---`, `===`, or blank lines.** Other delimiters break the parser.
- **Don't put `§` inside an entry.** It's reserved as the boundary marker.

Verbose facts (project specs, full preferences, design stacks) belong in mastra — not MEMORY.md — so this format only matters for the small core facts that must live in the system prompt.

## Verification

```bash
# Server health
hermes mastra status

# What this profile has stored
hermes mastra threads --profile $(hermes profile show | head -1)

# Inspect a thread
hermes mastra observations <thread_id>

# Inspect a versioned artifact
hermes mastra artifact get --kind soul
hermes mastra artifact history --kind memory
```

## Related skills

- `hermes-agent` — Hermes platform reference (loads when configuring Hermes itself)
- `obsidian` — long-form note storage (Mastra is for conversational memory; Obsidian for knowledge bases)

## Configuration

Per-profile model + flexible Mastra options live in `~/.hermes/mastra.json`. Edit via:

```bash
hermes mastra setup
```

Or programmatically — see the `model_config` and `mastra_options` modules in this plugin.
