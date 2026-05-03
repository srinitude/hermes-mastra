# 🧠 Mastra Observational Memory installed

This plugin gives Hermes humanlike long-context memory via a local Bun
server backed by [`@mastra/memory`](https://mastra.ai/docs/memory/observational-memory).

## Next steps

1. **Make this the active memory provider** (per profile):

   ```bash
   hermes config set memory.provider mastra
   ```

2. **Install Bun** if you don't have it:

   ```bash
   curl -fsSL https://bun.sh/install | bash
   ```

3. **One-time setup** — installs the Mastra TS deps and starts the local
   server (default port `4191`):

   ```bash
   hermes mastra setup
   ```

4. **Verify**:

   ```bash
   hermes mastra status
   hermes memory status
   ```

5. **Restart the gateway** (if running) so the provider is wired in:

   ```bash
   hermes gateway restart
   ```

## Default model wiring

The Observer (cheap, frequent) and Reflector (stronger, less frequent)
both default to Venice — `gemini-3-flash-preview` for the Observer,
`gemini-3-1-pro-preview` for the Reflector — and reuse `VENICE_API_KEY`.

Edit `~/.hermes/mastra.json` to point them at any
OpenAI-compatible endpoint (Hermes API server, OpenRouter, OpenAI,
Anthropic-OAI shim, local llama.cpp, etc.) and change
`observer_api_key_env` / `reflector_api_key_env` to whatever env var
holds the right key.

## Useful commands

```bash
hermes mastra server start|stop|restart|logs
hermes mastra resources                   # one resourceId per profile
hermes mastra threads --profile <name>    # threads for a profile
hermes mastra observations <thread_id>    # dump the observation log
hermes mastra reset --profile <name>      # nuke everything for a profile
```

## What the agent gets — 8 new tools

The plugin registers **8 model-driven memory tools**. The agent picks the right one per question; each tool does one thing well and cross-references its siblings.

| Tool | Purpose |
|------|---------|
| `mastra_recall` | This thread's observation log (no query) |
| `mastra_search` | Keyword search across observations in this profile |
| `mastra_semantic_search` | Vector / meaning-based search |
| `mastra_observe` | Persist a manual observation (corrections, decisions, preferences) |
| `mastra_working_memory` | Read the resource-scoped working-memory mirror |
| `mastra_artifact_get` | Read the canonical version of `SOUL.md` / `MEMORY.md` / `USER.md` / `AGENTS.md` |
| `mastra_artifact_history` | List version history of an identity file |
| `mastra_artifact_revert` | Restore an old version (history preserved — never rewinds) |

Per-tool spec (params, return shapes, costs, pitfalls): see [`README.md → Tools the agent gets`](./README.md#tools-the-agent-gets) or load the bundled `mastra` skill (`/mastra` in any Hermes session).

Full docs: see `README.md` in this plugin directory or
`https://github.com/srinitude/hermes-mastra`.
