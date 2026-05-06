"""Policy-as-test: every source file obeys the size rules.

Limits (project conventions):

  * 200 LOC per file (logical lines — no blanks/comments)
  * 30 LOC per function/class body
  * Max nesting depth of 3 (relative to the function body — .py/.ts/.sh only)

If you're seeing this fail, the fix is almost always to extract a helper
or split a module — never to bump the limit. The point of small files is
that any future contributor (or this AI agent in a fresh session) can
hold the whole module in their head.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "scripts",
}
FILE_LOC_LIMIT = 200
CONSTRUCT_LOC_LIMIT = 30
NESTING_LIMIT = 3
EXPECTED_RESILIENCE_MODULES = {
    "circuit_breaker.py",
    "response_guard.py",
    "supervisor.py",
    "observation_dedup.py",
}


def _iter_source_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if p.suffix not in {".py", ".ts"}:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        out.append(p)
    return out


def _file_loc(path: Path) -> int:
    comment_prefix = "#" if path.suffix == ".py" else "//"
    return sum(
        1
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(comment_prefix)
    )


def _py_construct_loc(node: ast.AST, src_lines: list[str]) -> int:
    body_lines = src_lines[node.lineno - 1 : node.end_lineno]
    return sum(1 for ln in body_lines if ln.strip() and not ln.strip().startswith("#"))


def _ts_function_loc(content: str) -> list[tuple[str, int, int]]:
    """Parse TS functions and return (name, start_line, loc)."""
    lines = content.split("\n")
    results: list[tuple[str, int, int]] = []
    in_func, func_name, func_start, brace_depth = False, "", 0, 0
    TS_FN = (
        r"(?:async\s+)?function\s+(\w+)|(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\("
    )
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not in_func:
            m = re.match(TS_FN, stripped)
            if m:
                in_func = True
                func_name = m.group(1) or m.group(2) or "<anon>"
                func_start = i
                brace_depth = line.count("{") - line.count("}")
        else:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                func_loc = sum(
                    1
                    for ln in lines[func_start - 1 : i]
                    if ln.strip() and not ln.strip().startswith("//")
                )
                results.append((func_name, func_start, func_loc))
                in_func = False
    return results


_NESTING_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.AsyncFor, ast.AsyncWith)


def _max_nesting(node: ast.AST, depth: int = 0) -> int:
    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _NESTING_NODES):
            best = max(best, _max_nesting(child, depth + 1))
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            best = max(best, _max_nesting(child, 0))
        else:
            best = max(best, _max_nesting(child, depth))
    return best


SOURCE_FILES = _iter_source_files()
PY_FILES = [p for p in SOURCE_FILES if p.suffix == ".py"]
TS_FILES = [p for p in SOURCE_FILES if p.suffix == ".ts"]


def test_expected_resilience_modules_are_policy_inputs() -> None:
    paths = {str(path.relative_to(ROOT)) for path in SOURCE_FILES}
    missing = sorted(EXPECTED_RESILIENCE_MODULES - paths)
    assert not missing, f"missing source policy inputs: {missing}"


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_file_under_loc_limit(path: Path) -> None:
    loc = _file_loc(path)
    assert loc <= FILE_LOC_LIMIT, (
        f"{path.relative_to(ROOT)} has {loc} LOC (limit {FILE_LOC_LIMIT}). "
        "Split into smaller modules."
    )


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_py_constructs_under_loc_limit(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    src_lines = src.splitlines()
    tree = ast.parse(src)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n = _py_construct_loc(node, src_lines)
            if n > CONSTRUCT_LOC_LIMIT:
                offenders.append(f"  L{node.lineno} fn {node.name}: {n} LOC")
    assert not offenders, (
        f"{path.relative_to(ROOT)} has functions over {CONSTRUCT_LOC_LIMIT} LOC:\n"
        + "\n".join(offenders)
        + "\nExtract helpers."
    )


@pytest.mark.parametrize("path", TS_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_ts_constructs_under_loc_limit(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    funcs = _ts_function_loc(src)
    offenders: list[str] = []
    for name, start, loc in funcs:
        if loc > CONSTRUCT_LOC_LIMIT:
            offenders.append(f"  L{start} fn {name}: {loc} LOC")
    assert not offenders, (
        f"{path.relative_to(ROOT)} has functions over {CONSTRUCT_LOC_LIMIT} LOC:\n"
        + "\n".join(offenders)
        + "\nExtract helpers."
    )


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_nesting_within_limit(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            d = _max_nesting(node, 0)
            if d > NESTING_LIMIT:
                offenders.append(f"  L{node.lineno} fn {node.name}: depth {d}")
    assert not offenders, (
        f"{path.relative_to(ROOT)} has functions exceeding nesting depth "
        f"{NESTING_LIMIT}:\n"
        + "\n".join(offenders)
        + "\nFlatten with guard clauses or extract helpers."
    )
