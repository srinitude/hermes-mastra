---
name: Daily Quality Audit
on:
  schedule:
    - cron: "0 8 * * 1-5"
  workflow_dispatch:
engine: copilot
permissions:
  contents: read
  issues: write
safe-outputs:
  create-issue:
    title-prefix: "[quality-audit] "
    labels: [quality-audit, automated]
    max: 1
    close-older-issues: true
tools:
  github:
    toolsets: [repos, actions]
  cache-memory: true
---

# Daily Quality Audit

Perform a daily quality audit of the hermes-mastra plugin.

## What to check

1. **Code size compliance** — read `tests/test_code_size_policy.py` limits, then spot-check
   files that are close to the 200 LOC limit (especially `server/src/` modules)
2. **Stale reference scan** — search for any remaining `_om`, `-om`, `OM`, `mastra_om`,
   `hermes-om` fragments across all source files
3. **Dependency freshness** — check if `@mastra/core`, `@mastra/memory`, `@mastra/libsql`
   have published new versions since the last audit (use `cache-memory` to track)
4. **Test coverage** — are there new functions in `server/src/*.ts` or `*.py` that lack tests?
5. **Documentation drift** — does `README.md` still match the actual `mise.toml` tasks?

## Output

Create a GitHub issue summarizing findings. Close the previous audit issue first.
Include specific file paths, line numbers, and actionable fix suggestions.
