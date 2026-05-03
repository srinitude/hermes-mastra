#!/usr/bin/env bash
# Re-runnable Firecrawl /map probe for source-grounding upstream docs.
# Reads FIRECRAWL_API_KEY from ~/.hermes/.env (the Hermes default location).
# Writes a JSON map to references/<slug>-map.json with limit=5000 by default.
#
# Usage:
#   ./firecrawl-map.sh <url> [out-path] [limit]
#
# Examples:
#   ./firecrawl-map.sh https://mise.jdx.dev/ references/mise-map.json
#   ./firecrawl-map.sh https://mastra.ai/docs references/mastra-map.json 5000
#   ./firecrawl-map.sh https://skills.sh/
#
# Cross-platform note: requires bash + curl. On native Windows, run under
# WSL2 or Git Bash. macOS and Linux work natively.

set -euo pipefail

URL="${1:?usage: firecrawl-map.sh <url> [out-path] [limit]}"
OUT="${2:-}"
LIMIT="${3:-5000}"

# Derive slug from URL host if no out-path provided
if [ -z "$OUT" ]; then
  HOST=$(echo "$URL" | sed -E 's#^https?://([^/]+).*#\1#' | tr '.' '-')
  OUT="references/${HOST}-map.json"
fi

# Load FIRECRAWL_API_KEY from ~/.hermes/.env if not already set
if [ -z "${FIRECRAWL_API_KEY:-}" ] && [ -f "$HOME/.hermes/.env" ]; then
  # shellcheck disable=SC1091
  set -a; . "$HOME/.hermes/.env"; set +a
fi

if [ -z "${FIRECRAWL_API_KEY:-}" ]; then
  echo "ERROR: FIRECRAWL_API_KEY not set and not found in ~/.hermes/.env" >&2
  exit 4
fi

mkdir -p "$(dirname "$OUT")"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

curl -fsSL -X POST https://api.firecrawl.dev/v1/map \
  -H "Authorization: Bearer $FIRECRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$(printf '{"url":"%s","limit":%s}' "$URL" "$LIMIT")" \
  -o "$TMP"

# Annotate with metadata and pretty-print
python3 -c "
import json, sys, datetime
d = json.load(open('$TMP'))
links = sorted(d.get('links', []))
out = {
    'source': '$URL',
    'tool': 'firecrawl',
    'endpoint': 'v1/map',
    'limit': $LIMIT,
    'count': len(links),
    'fetched_at': datetime.date.today().isoformat(),
    'success': d.get('success', False),
    'links': links,
}
with open('$OUT', 'w') as f:
    json.dump(out, f, indent=2)
print(f'wrote {out[\"count\"]} links to $OUT')
"
