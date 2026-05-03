---
name: CI Failure Investigator
on:
  workflow_run:
    workflows: ["quality"]
    types: [completed]
    conclusion: failed
engine: claude
permissions:
  contents: read
  actions: read
  issues: write
safe-outputs:
  create-issue:
    title-prefix: "[ci-failure] "
    labels: [ci-failure, automated]
    max: 1
tools:
  github:
    toolsets: [actions, repos]
---

# CI Failure Investigator

A quality workflow run just failed. Investigate and create an issue with findings.

## Steps

1. Find the most recent failed **quality** workflow run
2. Download and read the failure logs
3. Identify the root cause — is it a lint error, test failure, typecheck error, or dependency issue?
4. Check if this is a new failure or a recurring one (search existing `[ci-failure]` issues)
5. Create or update an issue with:
   - Which matrix OS failed (ubuntu, macos, windows)
   - The exact error message and which step failed
   - Root cause analysis
   - Suggested fix with specific file paths and line numbers
   - Link to the failed workflow run
