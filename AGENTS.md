# AGENTS.md — project conventions for hermes-mastra

## TDD-first workflow (mandatory)

Every code change MUST follow **BOOTSTRAP → RED → GREEN → REFACTOR**:

1. **BOOTSTRAP** — Create the test file with the function/method signature and a placeholder test. Run `mise run test` to confirm it collects (no skip, no import error).

2. **RED** — Write a test that exercises the desired behaviour and **asserts a specific failure**. Run `mise run test` and confirm the test fails for the *right* reason (not a syntax error or import failure). The failing test is your spec.

3. **GREEN** — Write the **minimum** production code to make the test pass. No gold-plating, no "while I'm here" changes. Run `mise run test` to confirm green.

4. **REFACTOR** — Clean up naming, extract helpers, reduce duplication. Run `mise run test` after every refactor step. If any test goes red, undo and try again.

**No production code may exist without a corresponding test that failed before the implementation.**

### Applies to all languages

- **Python** — `tests/test_*.py`, enforced by `mise run test`
- **TypeScript** — routes, helpers, config in `server/src/`, typechecked by `mise run typecheck`, linted by `mise run lint`
- **YAML** — GitHub Actions workflows, biome.json, tsconfig.json validated by `mise run validate`
- **Shell** — scripts in `scripts/`, executed by mise tasks

### Code-size policy (language-agnostic)

- **200 LOC** per file (non-blank, non-comment lines)
- **30 LOC** per function/class/method body
- **Max nesting depth** 3 (relative to function body; .py/.ts/.sh only — not .md/.yaml/.json config files)
- **Max cognitive complexity** 8 (enforced by biome for TS, ruff for Python)

Enforced by `tests/test_code_size_policy.py` (Python + TypeScript). Bumping limits is not acceptable — split the file instead.

### Before every commit

```bash
mise run quality        # format → lint → typecheck → test → audit → validate
```

All steps must pass. If `quality` fails, the commit is not ready.

## Project structure

```
server/src/
├── config.ts              # Env vars, constants, pure helpers
├── resources.ts           # Mastra storage, memory, agents (shared singletons)
├── helpers.ts             # Cross-route helpers (message builders, artifact ops)
├── routes-memory.ts       # Core memory routes (health, messages, recall, observation)
├── routes-admin.ts        # Admin routes (resources, threads, search, reset)
├── routes-artifacts.ts    # Artifact routes (SOUL/MEMORY/USER/AGENTS versioning)
└── index.ts               # Entry point: compose Hono sub-apps + auth + serve
```

## Key conventions

- `mise` is the only user-facing CLI surface
- Mastra/AI-SDK packages pin to `latest` (tracks upstream HEAD)
- Every hot-path hook must return in < 100ms (non-blocking guarantee)
- Commits only from humans with `[name] <email>`, no co-author trailers and commits from agents
