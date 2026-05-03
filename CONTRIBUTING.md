# Contributing to hermes-mastra

Thanks for considering a contribution — the rules of engagement are short and strict so the project stays maintainable.

## Hard rules (these are tested, not aspirational)

1. **TDD-first.** No production code lands without a failing test. The test gate is `mise run test`. RED → GREEN → REFACTOR is enforced by review and by the CI gate.

2. **Code-size policy:**
   - 200 LOC max per Python file
   - 30 LOC max per function/class body
   - max nesting depth 3 (relative to a function body)

   Enforced by `tests/test_code_size_policy.py`. If you bump the limit, your PR is rejected.

3. **Single-author identity.** Every commit, PR, automation, and CI auto-fix is authored solely as `Kiren Srinivasan <kiren@fantasymetals.com>`. **No `Co-Authored-By: Claude/etc.`, no bot identities (`github-actions[bot]`), no `🤖 Generated with` trailers.** CI workflows explicitly `git config user.name`/`user.email` to this identity before any commit.

4. **`mise` is the only user-facing CLI surface.** Direct `bun`/`bunx`/`biome`/`tsc`/`prettier`/`npm`/`npx`/`pnpm`/`yarn` commands are forbidden in user-facing surfaces (README, docs, scripts). They live only inside `package.json` script bodies and `mise.toml` `run = "..."` strings.

5. **Mastra/AI-SDK packages pin to `latest`.** This plugin tracks Mastra at HEAD on purpose. Tests in `test_latest_pinning.py` enforce this; if you genuinely need a temporary pin, add the package to `ALLOWED_PIN_OVERRIDES` with a comment and a tracking issue link.

6. **Non-blocking guarantee.** Every hot-path `MemoryProvider` hook returns in <100 ms even when Mastra is slow. The benchmark in `scripts/benchmark.py` plus `tests/test_non_blocking_hooks.py` enforces this. If a new hook makes a synchronous HTTP call, your PR is rejected.

## Quickstart

```bash
git clone https://github.com/srinitude/hermes-mastra.git
cd hermes-mastra

# Bootstrap: verifies global bun + python via mise
mise run setup

# Install Python venv + Bun deps (latest)
mise run install

# Run the full pytest suite
mise run test
```

`mise run quality:full` is the "before-you-PR" command — it runs format, lint, typecheck, test, security audit, validate, then syncs the active plugin at `~/.hermes/hermes-agent/plugins/memory/mastra/` so you can also test against your live Hermes session.

## Development loop

```bash
# Edit a test in tests/<your-feature>_test.py
mise run test     # RED — verify it fails for the right reason

# Edit code until it passes
mise run test     # GREEN — verify the fix works without regressions

# Refactor while keeping tests green
mise run quality  # full gate: format + lint + typecheck + test + audit
mise run sync     # push to ~/.hermes/ for live testing

# Or do all of the above in one shot
mise run quality:full
```

## Submitting a pull request

1. **Fork** the repo and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Write tests first.** Every PR must include a test that failed before the change and passes after. See "What useful tests look like" below.

3. **Run the full quality gate** before pushing:
   ```bash
   mise run quality:full
   ```
   This runs format → lint → typecheck → test → security audit → validate → sync to `~/.hermes/`. All steps must pass.

4. **Push and open a PR** against `main`. The PR template will ask for:
   - Summary of changes
   - Test plan
   - Checklist confirmation (code-size policy, CONTRIBUTING guidelines)

5. **CI runs automatically** — the same `mise run quality` gate runs in GitHub Actions. Your PR cannot merge until CI is green.

6. **One approval required** before merge. Squash-merge is preferred to keep history linear.

### PR conventions

- **One concern per PR.** Mixing a refactor + a feature + a doc update makes review harder.
- **Commit messages:** short imperative summary, blank line, optional body. No co-author trailers.
- **Keep the diff small.** If the PR touches >10 files, consider splitting it.
- **No force-push after review starts.** Amend or add new commits; the reviewer can squash at merge.

## What "useful" tests look like

Three patterns we use:

1. **Behaviour tests.** Mock the HTTP client, exercise the hook, assert the right call shape. Example: `tests/test_non_blocking_hooks.py`.
2. **Policy tests.** AST-walk the source tree and assert structural invariants. Example: `tests/test_code_size_policy.py`, `tests/test_latest_pinning.py`.
3. **Integration tests.** Verify cross-cutting wiring — e.g. that a hook signal actually triggers the right downstream observation. Example: `tests/test_hermes_link.py`, `tests/test_session_search_integration.py`, `tests/test_memory_md_integration.py`.

Avoid tests that just exercise mocks. If a test would still pass with a `pass` body in the production code, it's useless.

## File organization

```
.
├── __init__.py                  # MastraMemoryProvider — thin shell, every method delegates
├── provider.py                  # Top-level export of the class for absolute imports
├── provider_lifecycle.py        # Every MemoryProvider hook as a free function
├── provider_tools.py            # Tool dispatch (recall, search, observe)
├── tool_observers.py            # do_todo_snapshot, do_skill_loaded, do_memory_snapshot
├── tool_schemas.py              # JSON schemas for the 3 tools
├── recall_cache.py              # Cached observation snapshot (thread-safe)
├── async_runner.py              # Bounded background work queue
├── client.py                    # httpx wrapper for the Bun server
├── server_config.py             # Paths + config (pure helpers)
├── server_env.py                # Build env dict for Bun spawn
├── server_process.py            # Bun install/spawn/stop
├── server_manager.py            # Backwards-compat shim re-exporting the above
├── model_config.py              # Observer/Reflector role config
├── model_presets.py             # Built-in presets (Venice/OpenAI/etc.)
├── mastra_options.py            # Flexible MemoryOptions passthrough
├── cli.py + cli_commands.py     # `hermes mastra` argparse + handlers
├── config_schema.py             # Memory setup wizard schema
├── lifecycle_helpers.py         # Tiny shared helpers (alive, profile, safe_call)
└── server/                      # Bun + Hono TS server (Mastra bridge)
    ├── package.json             # latest-pinned deps
    ├── biome.json               # TS lint/format
    ├── tsconfig.json
    └── src/
        ├── config.ts              # Env vars, constants, pure helpers
        ├── resources.ts           # Mastra storage, memory, agents (shared singletons)
        ├── helpers.ts             # Cross-route helpers (message builders, artifact ops)
        ├── routes-memory.ts       # Core memory routes (health, messages, recall, observation)
        ├── routes-admin.ts        # Admin routes (resources, threads, search, reset)
        ├── routes-artifacts.ts    # Artifact routes (SOUL/MEMORY/USER/AGENTS versioning)
        └── index.ts               # Entry point: compose Hono sub-apps + auth + serve
```

If you're adding a new module, the rule of thumb is **one concern per file, ≤200 LOC**. If a module starts approaching that limit, split it.

## Common patterns

### Adding a new MemoryProvider hook

1. Write a failing test in `tests/test_<area>_integration.py`.
2. Add a `do_<hook>(p, ...)` function in `provider_lifecycle.py` (or `tool_observers.py` for tool/skill-driven signals).
3. Add a thin method on `MastraMemoryProvider` in `__init__.py` that delegates: `def on_<hook>(self, ...): L.do_<hook>(self, ...)`.
4. Run `mise run test`. The new test should pass; the size-policy test should also pass (no file >200 LOC, no function >30 LOC).

### Adding a new Mastra Memory option

The plugin is a "dumb JSON courier" for Mastra options. Users set them through dotted keys:

```python
import mastra_options as mo
mo.set_option("workingMemory.scope", "thread")
```

There's nothing for you to wire on the Python side — the option flows through `MASTRA_OPTIONS_JSON` to the Bun server which deep-merges it. Just verify `tests/test_mastra_options.py` covers the new key shape.

### Adding a new Bun server route

1. Add the route in the appropriate `server/src/routes-*.ts` module (memory, admin, or artifacts).
2. Add a corresponding method on `MastraClient` in `client.py`.
3. If it's a new tool surface, add a tool schema in `tool_schemas.py` and dispatch in `provider_tools.py`.
4. Run `mise run lint` — biome will flag complexity issues. Keep TS functions small (extract helpers like `collectThreadObservations` and `matchesIn` in the search route).
5. `mise run typecheck` is advisory (Mastra type drift); the runtime test (`mise run test`) is authoritative.

## Upstream compatibility

`mise run compat` runs daily in CI to detect API drift in `NousResearch/hermes-agent` and `mastra-ai/mastra`. If an upstream change breaks us:

1. The `Upstream Watch` workflow opens a PR on `chore/upstream-sync`.
2. CodeRabbit auto-reviews; once green, the PR auto-merges (CI auto-merge handles its own commits as `Kiren Srinivasan <kiren@fantasymetals.com>`).
3. If you're hand-fixing drift, run `mise run compat:hermes` and `mise run compat:mastra` locally to confirm.

## Filing issues

Before filing, run:

```bash
hermes mastra logs --lines 50
hermes mastra status
mise run doctor
```

Attach the output. Especially useful for:

- "Recall returns nothing" → likely Mastra hasn't fired the Observer yet (token threshold). Check `hermes mastra threads --profile <name>` to confirm ingestion is alive.
- "Server won't start" → check `hermes mastra logs`, then `bun --version`.
- "Observations leaking across profiles" → should never happen; verified by `tests/test_hermes_link.py`. File with `hermes mastra resources` output.

## License

MIT. By contributing you agree to license your work the same way.

## Code of Conduct

Don't be a jerk. Be precise. Test your changes. Use Kiren's identity for all commits per the project conventions.
