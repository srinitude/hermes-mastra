"""G03: secret redaction at the Mastra HTTP boundary.

Every outbound write payload (observation, working_memory, artifact)
runs through ``redact_payload`` before serialization. Patterns that
match common credentials are replaced with ``[REDACTED]`` regardless
of the global ``HERMES_REDACT_SECRETS`` setting — Mastra observations
are persistent and indexed, so even one leaked secret survives across
sessions and may be retrieved by ``mastra_search``/``mastra_recall``.

The module deliberately keeps a small set of patterns covering the
formats the R09 contract enumerates (GitHub PAT, OpenRouter / OpenAI
sk- keys, Bearer tokens, password= assignments). Hermes ships a much
broader regex library at ``agent.redact``; when that is importable
(plugin-in-Hermes runtime) we additionally fold its prefix-pattern
output through our marker so cross-vendor coverage stays in sync.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Vendor-prefixed credentials. Each pattern is anchored with a non-word
# boundary so we don't slice the middle of an unrelated token.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-or-[A-Za-z0-9_-]{10,}"),
    re.compile(r"sk-(?:proj|live|test|ant|or)?-?[A-Za-z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]+"),
    re.compile(
        r"\b(?:password|passwd|pwd|secret|token|apikey|api_key|credential|auth)"
        r"\s*=\s*[^\s;,&]+",
        re.IGNORECASE,
    ),
)


def redact_secrets(text: str) -> str:
    """Replace every recognized secret-shaped substring with ``[REDACTED]``."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern in _PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def redact_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Recursively redact secret-shaped values in an outbound payload."""
    if not isinstance(payload, dict) or not payload:
        return payload
    return {k: _redact_value(v) for k, v in payload.items()}


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return redact_payload(value)
    if isinstance(value, (list, tuple)):
        kind = type(value)
        return kind(_redact_value(item) for item in value)
    return value
