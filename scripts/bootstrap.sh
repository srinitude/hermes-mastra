#!/usr/bin/env bash
# BOOTSTRAP — stand up a working dev/test environment in one shot.
#
# After this runs you should be able to:
#   make test     # full RED/GREEN gate (python + bun)
#   make lint
#
# Re-runnable; idempotent. Safe to run on a fresh checkout, in CI, or
# after a `make clean`.
#
# Cross-platform note: requires bash. On native Windows, run under WSL2
# or Git Bash (both provide bash). macOS and Linux work natively.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "▶ BOOTSTRAP — hermes-mastra"
echo "  repo: $ROOT"
echo

# ---- Python venv + deps -------------------------------------------------
# Prefer `uv` (fast, handles externally-managed Python correctly).
# Fall back to plain `python -m venv` for environments without uv.
if command -v uv >/dev/null 2>&1; then
  PYVER="${PYTHON_VERSION:-3.11}"
  echo "▶ uv venv .venv --python $PYVER"
  uv venv .venv --python "$PYVER" --quiet
  echo "▶ uv pip install -e .[dev]"
  uv pip install --quiet --python .venv/bin/python -e ".[dev]"
else
  PY="${PYTHON:-python3}"
  PYV=$("$PY" -c "import sys; print('%d.%d' % sys.version_info[:2])")
  case "$PYV" in
    3.10|3.11|3.12|3.13) ;;
    *) echo "✖ Need Python >=3.10 (have $PYV). Install uv or a newer python."; exit 1 ;;
  esac
  if [ ! -d ".venv" ]; then
    echo "▶ creating .venv with $($PY --version)"
    "$PY" -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  echo "▶ pip install -e .[dev]"
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -e ".[dev]"
  deactivate
fi

# ---- Bun deps for the TS server ----------------------------------------
if ! command -v bun >/dev/null 2>&1; then
  echo "✖ bun not found in PATH."
  echo "  Install it first:  curl -fsSL https://bun.sh/install | bash"
  exit 1
fi

echo "▶ bun install (server)"
( cd server && bun install --silent )

# ---- Sanity check -------------------------------------------------------
echo
echo "▶ self-test"
.venv/bin/python -c "import sys; sys.path.insert(0, '.'); import client; import server_manager; print('   plugin source importable ✓')"
( cd server && bun --version | sed 's/^/   bun version: /' )

echo
echo "✓ BOOTSTRAP complete. Next:"
echo "    make test    # run RED/GREEN gate"
echo "    make lint"
