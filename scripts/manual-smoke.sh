#!/usr/bin/env bash
# scripts/manual-smoke.sh — one-shot manual smoke test for hermes-mastra.
#
# Verifies, from a clean state:
#   1. Pre-flight: bun, mise, hermes, VENICE_API_KEY, port 4191 free.
#   2. Sync runtime files into the active Hermes plugin directory.
#   3. Activate the provider in ~/.hermes/config.yaml.
#   4. Bring up the Bun server via the plugin's own post_setup path.
#   5. Health probe + tool surface check.
#   6. Single-session round-trip: observe → save → recall.
#   7. Profile / tenant isolation: writes in profile A vs profile B
#      stay in their own resourceId; no leakage.
#   8. Hermes-side hook roundtrip through the in-process provider:
#      every lifecycle hook fires, returns under 100 ms budget.
#   9. Tear-down: stop server, optionally reset test profiles.
#
# Usage:
#   ./scripts/manual-smoke.sh              # full run
#   KEEP=1 ./scripts/manual-smoke.sh       # don't tear down at the end
#   TEAR_TEST_DATA=1 ./scripts/manual-smoke.sh  # also wipe test profiles
#
# Exit codes:
#   0  — all phases passed
#   2  — pre-flight blocker (missing tool / key)
#   3  — server didn't come up
#   4  — provider not loadable under Hermes venv
#   5  — tenant isolation FAILED (the most important regression signal)
#   6  — hot-path budget violated

set -euo pipefail
cd "$(dirname "$0")/.."

ROOT="$(pwd)"
HERMES_VENV="$HOME/.hermes/hermes-agent/venv/bin/python"
BASE="${BASE:-http://127.0.0.1:4191}"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m⚠\033[0m %s\n" "$*"; }
fail() { printf "  \033[31m✖\033[0m %s\n" "$*"; }

# ---- 1. pre-flight ---------------------------------------------------------
bold "[1/9] Pre-flight"
command -v bun >/dev/null   || { fail "bun not on PATH"; exit 2; }
command -v mise >/dev/null  || { fail "mise not on PATH"; exit 2; }
command -v hermes >/dev/null|| { fail "hermes not on PATH"; exit 2; }
ok "bun=$(bun --version) mise=$(mise --version | head -1) hermes=$(hermes --version 2>&1 | head -1)"

if grep -q VENICE_API_KEY "$HOME/.hermes/.env" 2>/dev/null; then
  ok "VENICE_API_KEY present in ~/.hermes/.env"
else
  warn "VENICE_API_KEY not in ~/.hermes/.env — Observer/Reflector will 401"
fi

# Free port 4191 if a stale server is around
lsof -ti :4191 2>/dev/null | xargs -r kill -9 2>/dev/null || true
sleep 1
if lsof -ti :4191 >/dev/null 2>&1; then
  fail "port 4191 still occupied after kill — investigate"
  exit 2
fi
ok "port 4191 free"

# ---- 2. sync runtime files ------------------------------------------------
bold "[2/9] Sync runtime files into active Hermes plugin dir"
mkdir -p "$HOME/.hermes/hermes-agent/plugins/memory/mastra"
mise run sync >/dev/null
ok "synced → ~/.hermes/hermes-agent/plugins/memory/mastra"

# ---- 3. activate provider --------------------------------------------------
bold "[3/9] Activate provider in config.yaml"
hermes config set memory.provider mastra >/dev/null
ok "memory.provider = mastra"

# ---- 4. bring up server ----------------------------------------------------
bold "[4/9] Bring up the Bun server"
"$HERMES_VENV" - <<'PY'
from pathlib import Path
from plugins.memory import load_memory_provider
p = load_memory_provider("mastra")
assert p is not None, "load_memory_provider returned None"
p.post_setup(str(Path.home() / ".hermes"), config={})
PY
sleep 3
if ! curl -fsS "$BASE/health" >/dev/null 2>&1; then
  fail "server health probe failed at $BASE/health"
  exit 3
fi
ok "server up and healthy"

# ---- 5. tool surface -------------------------------------------------------
bold "[5/9] Tool surface (8 mastra_* tools)"
TOOL_COUNT=$("$HERMES_VENV" -c "
from plugins.memory import load_memory_provider
p = load_memory_provider('mastra')
print(len(p.get_tool_schemas()))
")
if [ "$TOOL_COUNT" != "8" ]; then
  fail "expected 8 tools, got $TOOL_COUNT"
  exit 4
fi
ok "8 mastra_* tools exposed"

# ---- 6. round-trip ---------------------------------------------------------
bold "[6/9] Single-session round-trip (observe + save + recall)"
THREAD="smoke-$(date +%s)"
curl -sS -X POST "$BASE/api/memory/observation" -H "content-type: application/json" \
  -d "{\"thread\":\"$THREAD\",\"profile\":\"smoke-default\",\"text\":\"smoke-test fact $(date)\",\"kind\":\"smoke\"}" >/dev/null
curl -sS -X POST "$BASE/api/memory/messages" -H "content-type: application/json" \
  -d "{\"thread\":\"$THREAD\",\"profile\":\"smoke-default\",\"user\":\"u\",\"assistant\":\"a\"}" >/dev/null
RESOURCES=$(curl -sS "$BASE/api/memory/resources" | python3 -c "import sys,json; print(\",\".join(json.load(sys.stdin)[\"resources\"]))")
echo "$RESOURCES" | grep -q "hermes:smoke-default" || { fail "resource hermes:smoke-default not present after write: $RESOURCES"; exit 4; }
ok "observation written, resource present"

# ---- 7. tenant isolation (THE critical contract) --------------------------
bold "[7/9] Profile (tenant) isolation"
curl -sS -X POST "$BASE/api/memory/observation" -H "content-type: application/json" \
  -d "{\"thread\":\"$THREAD-b\",\"profile\":\"smoke-other\",\"text\":\"PROFILE_OTHER_SECRET\",\"kind\":\"secret\"}" >/dev/null
LEAK_A=$(curl -sS "$BASE/api/memory/search?query=PROFILE_OTHER_SECRET&profile=smoke-default&limit=5" | python3 -c "import sys,json; print(json.load(sys.stdin)[\"count\"])")
if [ "$LEAK_A" != "0" ]; then
  fail "TENANT LEAK: profile smoke-default sees $LEAK_A hits for smoke-other secret"
  exit 5
fi
LEAK_B_THREADS=$(curl -sS "$BASE/api/memory/threads?profile=smoke-default" | python3 -c "
import sys, json
threads = json.load(sys.stdin)[\"threads\"]
print(\"\\n\".join(t[\"id\"] for t in threads))
")
echo "$LEAK_B_THREADS" | grep -q -- "-b\$" && { fail "thread $THREAD-b leaked into smoke-default"; exit 5; } || true
ok "no cross-profile leakage (search count=0, no foreign threads)"

# ---- 8. in-process hook roundtrip + hot-path budget ------------------------
bold "[8/9] In-process hook roundtrip with hot-path budget enforcement"
"$HERMES_VENV" - <<PY
import time
from pathlib import Path
from plugins.memory import load_memory_provider

p = load_memory_provider("mastra")
p.initialize("smoketest", hermes_home=str(Path.home() / ".hermes"),
             platform="cli", agent_identity="default", agent_context="primary")
time.sleep(2)
budget_ms = 100
violations = []
for label, call in [
    ("system_prompt_block", lambda: p.system_prompt_block()),
    ("prefetch",            lambda: p.prefetch("q", session_id="smoketest")),
    ("sync_turn",           lambda: p.sync_turn("u", "a", session_id="smoketest")),
    ("on_session_switch",   lambda: p.on_session_switch("smoketest-2", parent_session_id="smoketest")),
    ("on_pre_compress",     lambda: p.on_pre_compress([{"role":"user","content":"x"}])),
    ("on_memory_write",     lambda: p.on_memory_write("add", "memory", "x")),
]:
    t0 = time.perf_counter()
    call()
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   {label:22s} {elapsed:6.2f} ms")
    if elapsed > budget_ms:
        violations.append((label, elapsed))
p.shutdown()
if violations:
    raise SystemExit(f"BUDGET VIOLATIONS: {violations}")
PY
ok "every hook < 100 ms"

# ---- 9. tear-down ----------------------------------------------------------
bold "[9/9] Tear-down"
if [ -z "${KEEP:-}" ]; then
  lsof -ti :4191 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  ok "stopped Bun server"
fi
if [ -n "${TEAR_TEST_DATA:-}" ]; then
  for prof in smoke-default smoke-other; do
    curl -sS -X POST "$BASE/api/memory/reset" -H "content-type: application/json" \
      -d "{\"profile\":\"$prof\"}" >/dev/null 2>&1 || true
  done
  ok "reset test profiles"
fi

bold "✓ all 9 phases passed"
