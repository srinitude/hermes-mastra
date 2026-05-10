"""B01 — parity-matrix harness skeleton.

Loads ``analysis/parity-matrix.json``, walks every dimension D01..D13, and
invokes the measurement registered for that cell (or marks it
``UNIMPLEMENTED`` if no measurement is wired yet). Writes the results to
``analysis/parity-results.json`` and exits non-zero when any cell is
missing or any TARGET is unmet.

The skeleton keeps every cell UNIMPLEMENTED until its corresponding RED
test lands. GREEN tasks G00..G09 wire each measurement in turn.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "analysis" / "parity-matrix.json"
RESULTS_PATH = REPO_ROOT / "analysis" / "parity-results.json"


# Registry of per-dimension measurement callables. A measurement returns a
# (mastra_score, bundled_max_score) pair or raises ``MeasurementUnavailable``
# when bundled-provider live credentials / runtime prerequisites are missing.
MEASURE: dict[str, Callable[[], tuple[float, float]]] = {}


class MeasurementUnavailable(RuntimeError):
    """Raised when a parity cell cannot be measured in this environment."""


def register(dim_id: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        MEASURE[dim_id] = fn
        return fn

    return _wrap


def _load_matrix() -> dict[str, Any]:
    if not MATRIX_PATH.exists():
        raise FileNotFoundError(f"missing parity matrix: {MATRIX_PATH}")
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _run_one(dim: dict[str, Any]) -> dict[str, Any]:
    """Invoke the measurement for one dimension; classify the outcome."""
    dim_id = str(dim.get("id") or "")
    fn = MEASURE.get(dim_id)
    if fn is None:
        return _cell_result(dim, status="UNIMPLEMENTED", note="no measurement registered")
    try:
        mastra, bundled = fn()
    except MeasurementUnavailable as exc:
        return _cell_result(dim, status="WAIVED", note=str(exc))
    except Exception as exc:  # pragma: no cover - any other defect surfaces here
        return _cell_result(dim, status="ERROR", note=f"{type(exc).__name__}: {exc}")
    status = "PASS" if _meets_target(dim, mastra, bundled) else "FAIL"
    return _cell_result(dim, status=status, mastra=mastra, bundled=bundled)


def _meets_target(dim: dict[str, Any], mastra: float, bundled: float) -> bool:
    rule = (dim.get("win_rule") or "").lower()
    if "+0.10" in rule or "+10%" in rule:
        return mastra >= bundled + 0.10
    if "<=1.1x" in rule:
        return mastra <= bundled * 1.1
    if "<=" in rule:
        return mastra <= bundled
    return mastra >= bundled


def _cell_result(
    dim: dict[str, Any],
    *,
    status: str,
    note: str = "",
    mastra: float | None = None,
    bundled: float | None = None,
) -> dict[str, Any]:
    return {
        "id": dim.get("id"),
        "name": dim.get("name"),
        "status": status,
        "mastra_score": mastra,
        "bundled_max_score": bundled,
        "target": dim.get("target"),
        "win_rule": dim.get("win_rule"),
        "note": note,
    }


def _summary(cells: list[dict[str, Any]]) -> dict[str, int]:
    out = {"PASS": 0, "FAIL": 0, "UNIMPLEMENTED": 0, "WAIVED": 0, "ERROR": 0}
    for c in cells:
        out[c["status"]] = out.get(c["status"], 0) + 1
    return out


def _exit_code(summary: dict[str, int]) -> int:
    """Exit non-zero whenever any cell is missing or unmet (FAIL/UNIMPLEMENTED/ERROR)."""
    if summary.get("FAIL", 0) or summary.get("UNIMPLEMENTED", 0) or summary.get("ERROR", 0):
        return 1
    return 0


def _import_measurements() -> None:
    """Register the per-dimension measurements; works as a script or via -m."""
    try:
        from . import measurements
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import measurements  # type: ignore[no-redef]


def run() -> int:
    # Importing measurements registers every dimension with the MEASURE table.
    _import_measurements()
    matrix = _load_matrix()
    dims = list(matrix.get("dimensions") or [])
    cells = [_run_one(d) for d in dims]
    summary = _summary(cells)
    payload = {
        "schema_version": "1.0.0",
        "source_matrix": str(MATRIX_PATH.relative_to(REPO_ROOT)),
        "summary": summary,
        "cells": cells,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return _exit_code(summary)


if __name__ == "__main__":
    sys.exit(run())
