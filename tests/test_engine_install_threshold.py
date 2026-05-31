"""Tests for honoring the main Hermes ``compression.threshold`` in the
Mastra context-engine delegate.

Regression guard for the bug where the delegate ``ContextCompressor`` was
constructed without ``threshold_percent``, so it fell back to the 0.50
default and compacted at 50% of the window even when the user configured
``compression.threshold: 0.9``.
"""

from __future__ import annotations

import sys
import types
from typing import ClassVar

import pytest

import engine_install


class _CaptureCompressor:
    """Records constructor kwargs so the test can assert what was passed."""

    last_kwargs: ClassVar[dict] = {}

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = dict(kwargs)
        self.model = kwargs.get("model", "x")
        self.threshold_percent = kwargs.get("threshold_percent", 0.50)
        self.threshold_tokens = 100_000
        self.context_length = 200_000

    @property
    def name(self) -> str:
        return "compressor"


@pytest.fixture
def capture_compressor(monkeypatch):
    fake = types.ModuleType("agent.context_compressor")
    fake.ContextCompressor = _CaptureCompressor
    monkeypatch.setitem(sys.modules, "agent.context_compressor", fake)
    _CaptureCompressor.last_kwargs = {}
    return _CaptureCompressor


def _patch_main_threshold(monkeypatch, value):
    monkeypatch.setattr(engine_install, "_main_compression_threshold", lambda: value, raising=True)


class _FakeProvider:
    _cfg: ClassVar[dict] = {"recall_top_k": 4}


def test_delegate_receives_configured_threshold(capture_compressor, monkeypatch):
    _patch_main_threshold(monkeypatch, 0.9)
    engine_install._build_engine(_FakeProvider(), {})
    assert capture_compressor.last_kwargs.get("threshold_percent") == 0.9


def test_delegate_uses_default_when_threshold_unreadable(capture_compressor, monkeypatch):
    _patch_main_threshold(monkeypatch, None)
    engine_install._build_engine(_FakeProvider(), {})
    # When unreadable, we must NOT pass threshold_percent — let the
    # delegate keep its own default rather than forcing a wrong value.
    assert "threshold_percent" not in capture_compressor.last_kwargs


def test_main_compression_threshold_reads_host_config(monkeypatch):
    fake_cfg_mod = types.ModuleType("hermes_cli.config")
    fake_cfg_mod.load_config = lambda: {"compression": {"threshold": 0.85}}
    fake_pkg = types.ModuleType("hermes_cli")
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", fake_cfg_mod)
    assert engine_install._main_compression_threshold() == 0.85


def test_main_compression_threshold_none_when_absent(monkeypatch):
    fake_cfg_mod = types.ModuleType("hermes_cli.config")
    fake_cfg_mod.load_config = lambda: {"compression": {}}
    fake_pkg = types.ModuleType("hermes_cli")
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", fake_cfg_mod)
    assert engine_install._main_compression_threshold() is None
