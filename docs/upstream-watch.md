# Upstream Watch — operations guide

This plugin tracks `mastra-ai/mastra` and `NousResearch/hermes-agent` at HEAD
on purpose (server/package.json pins `latest`). The `upstream-watch.yml`
workflow keeps drift visible by:

1. Re-resolving Bun deps to true `latest` (drops `server/bun.lock` first).
2. Running the upstream-compat checks against fresh opensrc clones.
3. Auto-applying safe fixes (`ruff --fix`, `biome --write`).
4. Refreshing Firecrawl docs maps.
5. Opening / updating a single rolling PR (`chore/upstream-sync`).

## Triggers

- **Nightly:** `cron: 17 7 * * *` (07:17 UTC).
- **Manual:** Actions → "Upstream Watch" → Run workflow.
- **Repo-dispatch:** any external system can `POST /repos/<owner>/<repo>/dispatches`
  with `event_type: upstream-mastra` or `upstream-hermes` to trigger it
  immediately. Wire those in upstream by adding a release / push workflow that
  calls back here:

  ```yaml
  # Example: dispatch from upstream when their main moves.
  - name: Notify hermes-mastra to resync
    run: |
      curl -fsSL -X POST \
        -H "Authorization: Bearer ${{ secrets.MASTRA_DISPATCH_PAT }}" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/repos/srinitude/hermes-mastra/dispatches \
        -d '{"event_type":"upstream-mastra","client_payload":{"sha":"${{ github.sha }}"}}'
  ```

  Mastra and Hermes don't ship this dispatch by default — you can either
  PR it upstream or rely on the nightly cron, which is sufficient for most
  drift.

## One-time setup

1. **Personal access token (optional but recommended).** GitHub's default
   `GITHUB_TOKEN` can open PRs but cannot trigger downstream workflows
   (so a freshly-opened sync PR won't run the Quality workflow). To fix,
   create a fine-grained PAT with `contents: write` + `pull_requests: write`
   on this repo and add it as `UPSTREAM_SYNC_PAT` in repo secrets.

2. **Firecrawl key (optional).** Add `FIRECRAWL_API_KEY` to repo secrets if
   you want the workflow to refresh `references/*-map.json`. Without it,
   the docs-map step is silently skipped.

3. **opensrc rate limits.** The workflow installs `opensrc` and uses the
   default `GITHUB_TOKEN` for archive downloads. No extra setup needed
   unless your repo lives in an org with restrictive workflow permissions.

## Local rehearsal with `act`

```bash
# Install act once: `brew install act`
act workflow_dispatch -W .github/workflows/upstream-watch.yml \
    --secret-file ~/.hermes/.env --container-architecture linux/amd64
```

`act` runs the same job in Docker; useful for iterating on the workflow
without burning Actions minutes.

## What lands in the rolling PR

Every successful run writes to the same branch (`chore/upstream-sync`),
so reviewers see a single living PR rather than nightly noise. The PR body
is the structured drift report:

- Resolved Bun versions
- Upstream commit pointers (with subject lines)
- Step outcomes (quality + compat)
- `git diff --stat` of what the auto-fixer changed

If `quality` or `compat` failed, the workflow run itself goes red so the
PR shows ❌ — you're meant to investigate before merging.
