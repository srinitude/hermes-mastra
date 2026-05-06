"""R02 RED: circuit breaker fail-closes client work."""

from __future__ import annotations

import importlib
import importlib.util


def _module():
    spec = importlib.util.find_spec("circuit_breaker")
    assert spec is not None, "circuit_breaker.py must exist before GREEN"
    return importlib.import_module("circuit_breaker")


def test_breaker_opens_half_opens_and_closes_on_success():
    module = _module()
    clock = {"now": 100.0}
    breaker = module.CircuitBreaker(threshold=2, cooldown_seconds=5, now=lambda: clock["now"])
    calls: list[str] = []

    def fail():
        calls.append("fail")
        raise RuntimeError("server down")

    assert breaker.call(fail, fallback="cached") == "cached"
    assert breaker.call(fail, fallback="cached") == "cached"
    assert breaker.state == "OPEN"
    assert breaker.call(lambda: "network", fallback="cached") == "cached"
    clock["now"] += 5.1
    assert breaker.call(lambda: "ok", fallback="cached") == "ok"
    assert breaker.state == "CLOSED"
    assert calls == ["fail", "fail"]
