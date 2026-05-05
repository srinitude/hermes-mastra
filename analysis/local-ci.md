# Local CI/CD — single command surface

The canonical local CI/CD command for this repository is:

```bash
mise run quality
```

Defined in `mise.toml` at `[tasks.quality]`. It depends on:

| Step              | Command                                        | Enforces                                  |
|-------------------|------------------------------------------------|-------------------------------------------|
| `format`          | ruff format + ruff fix + biome check --write | Pythonic style + TS style                 |
| `lint`            | `ruff check` + `biome lint src`                | static lint, complexity                   |
| `typecheck`       | `tsc --noEmit` (advisory)                      | TS type drift                             |
| `test`            | `pytest -q`                                    | unit + contract + integration             |
| `security:audit`  | `pip check` + `bun pm scan` (best-effort)      | dependency CVEs                           |
| `validate`        | `yaml.safe_load(plugin.yaml)` + `tomllib.loads(pyproject.toml)` | manifest sanity        |

Aggregate exit status: any sub-task failure causes `mise run quality`
to exit non-zero.

## Code-size + nesting limits enforced by `tests/test_code_size_policy.py`

* 200 LOC per file (non-blank, non-comment) — Python and TypeScript.
* 30 LOC per construct (function, class, method).
* Max nesting depth 3.
* Max cognitive complexity 8 (biome for TS, ruff for Python).

The test fails fast if any of those limits are breached, and is
included in the `test` step of the quality gate.

## Other useful local commands

| Goal                                | Command                          |
|-------------------------------------|----------------------------------|
| Verify upstream Hermes contract     | `mise run compat:hermes`         |
| Verify upstream Mastra API surface  | `mise run compat:mastra`         |
| Both compatibility checks           | `mise run compat`                |
| Hot-path benchmarks                 | `mise run bench`                 |
| Compare against other memory provs  | `mise run bench:compare`         |
| Both benchmarks                     | `mise run bench:all`             |
| Sync runtime files into ~/.hermes   | `mise run sync`                  |
| Quality gate + sync                 | `mise run quality:full`          |
| Refresh upstream doc maps           | `mise run docs:map`              |

## Runtime requirements

* `mise` ≥ 2026.2.0 (declared in `mise.toml`).
* Bun ≥ 1.3 (server-side TypeScript).
* Python ≥ 3.11 (plugin code, tests, code-size policy).
* `opensrc` ≥ 0.7.2 (recommended; soft-required by `compat:*`).
* `firecrawl` (recommended; consumed by `docs:map*`).

Bootstrap from a fresh checkout:

```bash
mise trust              # accept this project's mise.toml
mise run install        # creates .venv + installs Bun deps
mise run quality        # runs the full local CI gate
```
