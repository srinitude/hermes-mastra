#!/usr/bin/env bash
# Sync this repo's runtime files into the active Hermes plugin directory
# (~/.hermes/hermes-agent/plugins/memory/mastra/).
#
# Excludes dev-shell files: tests, scripts, mise/pyproject configs, .venv,
# node_modules, caches, .git, .github, references, docs, backups.
#
# Idempotent — re-run anytime. Safe-by-design: --delete is scoped to runtime
# files only via the explicit exclude list, so tests/scripts/etc never get
# pushed and a manual edit to the active plugin gets overwritten.
#
# Cross-platform note: requires bash + rsync. On native Windows, run under
# WSL2 or Git Bash. macOS and Linux work natively.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/.hermes/hermes-agent/plugins/memory/mastra"
DEST_PARENT="$(dirname "$DEST")"

if [ ! -d "$DEST" ]; then
  if [ -d "$DEST_PARENT" ]; then
    mkdir -p "$DEST"
  else
    echo "✖ Hermes memory plugin directory not found at $DEST_PARENT"
    echo "  Is Hermes installed? Try: hermes plugins install srinitude/hermes-mastra"
    exit 2
  fi
fi

# Clear stale pyc cache so Hermes recompiles after the sync.
rm -rf "$DEST/__pycache__"

rsync -a \
  --include='__init__.py' \
  --exclude='_*.py' \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='tests' \
  --exclude='scripts' \
  --exclude='.git' \
  --exclude='.github' \
  --exclude='references' \
  --exclude='docs' \
  --exclude='Makefile' \
  --exclude='conftest.py' \
  --exclude='pyproject.toml' \
  --exclude='mise.toml' \
  --exclude='.miserc.toml' \
  --exclude='*.bak.*' \
  --exclude='*.test.ts' \
  --exclude='*.spec.ts' \
  --exclude='bun.lock' \
  --exclude='.gitignore' \
  --exclude='.coderabbit*' \
  "$ROOT"/ "$DEST"/

echo "✓ synced runtime files → $DEST"

# Quick sanity: confirm the plugin still imports under Hermes' venv.
HERMES_VENV="$HOME/.hermes/hermes-agent/venv/bin/python"
if [ -x "$HERMES_VENV" ]; then
  "$HERMES_VENV" -c "
from plugins.memory import load_memory_provider
p = load_memory_provider('mastra')
assert p, 'plugin failed to load'
print(f'✓ verified loadable via Hermes venv ({type(p).__name__})')
" || { echo "✖ plugin failed to load under Hermes — sync rolled back not implemented; investigate"; exit 1; }
else
  echo "ℹ Hermes venv not at $HERMES_VENV — skipping load check"
fi
