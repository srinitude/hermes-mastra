---
name: Stale Reference Sweeper
on:
  pull_request:
    branches: [main]
engine: copilot
permissions:
  contents: read
  pull-requests: write
safe-outputs:
  add-comment: {}
tools:
  github:
    toolsets: [repos, pull_requests]
---

# Stale Reference Sweeper

Review the pull request diff for stale references from the old plugin name.

## What to flag

Any occurrence of these patterns in the diff (added lines only):
- `mastra_om` (old tool prefix)
- `MASTRA_OM` (old env var)
- `mastra-om` (old CLI name)
- `hermes-om` (old agent name)
- `Bun OM` (old description)
- `OM server` / `OM observation`
- `Mastra-OM`

## Also check

- Code-size violations: any new file over 200 LOC or function over 30 LOC
- Missing tests: new functions/classes without corresponding test coverage
- Hardcoded platform paths: `/opt/homebrew`, `C:\`, or other OS-specific paths

## Output

Post a review comment listing any violations found. If clean, post a confirmation.
