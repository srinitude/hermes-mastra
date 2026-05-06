"""R14 RED: resilience modules are part of the source-size policy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = [
    "circuit_breaker.py",
    "response_guard.py",
    "supervisor.py",
    "observation_dedup.py",
]


def test_resilience_modules_are_policy_managed():
    import tests.test_code_size_policy as policy

    policy_paths = {str(path.relative_to(ROOT)) for path in policy.SOURCE_FILES}
    missing = [name for name in EXPECTED if name not in policy_paths]
    assert not missing, f"resilience modules missing from code-size policy: {missing}"
