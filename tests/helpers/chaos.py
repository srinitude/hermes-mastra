"""Chaos-suite helpers for resilience and non-raising hook assertions."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Iterable
from typing import Any

HookCall = tuple[str, Callable[..., Any], tuple[Any, ...], dict[str, Any]]


def elapsed_ms(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> float:
    start = time.perf_counter()
    fn(*args, **kwargs)
    return (time.perf_counter() - start) * 1000


def p99_ms(samples: Iterable[float]) -> float:
    values = sorted(samples)
    if not values:
        return 0.0
    index = min(len(values) - 1, int(len(values) * 0.99))
    return values[index]


def assert_hooks_do_not_raise(calls: Iterable[HookCall]) -> None:
    errors: list[str] = []
    for name, fn, args, kwargs in calls:
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - assertion evidence
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not errors, "Hook failures escaped provider boundary: " + "; ".join(errors)


def assert_p99_under(samples: list[float], budget_ms: float, label: str) -> None:
    value = p99_ms(samples)
    assert value < budget_ms, f"{label} p99 {value:.3f}ms exceeded {budget_ms:.3f}ms"


def median_ms(samples: list[float]) -> float:
    return float(statistics.median(samples)) if samples else 0.0
