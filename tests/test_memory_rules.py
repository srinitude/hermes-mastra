"""Tests for the canonical Mastra rules installed into MEMORY.md + USER.md.

When the plugin is set up (`hermes mastra setup` → `post_setup` hook),
it installs ONE rule per file that redirects the agent to mastra
for everything except a few always-true facts. Net effect:

  * Built-in memory stays small (humans skim 2 entries, not 20).
  * Future writes get routed to mastra automatically because the
    rule explicitly tells the agent which surface to use.
  * Re-running setup is idempotent — no duplicate rules, no overwriting
    of user-curated content.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def memories_dir(tmp_path, monkeypatch):
    home = tmp_path / "hermes_home"
    (home / "memories").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    import sys
    import types

    if "hermes_constants" not in sys.modules:
        stub = types.ModuleType("hermes_constants")
        stub.get_hermes_home = lambda: home  # type: ignore[attr-defined]
        sys.modules["hermes_constants"] = stub
    else:
        sys.modules["hermes_constants"].get_hermes_home = lambda: home  # type: ignore[attr-defined]
    return home / "memories"


# ---- shape of the rules we install ---------------------------------------


def test_canonical_memory_rule_is_short():
    """The rule itself must fit comfortably under MEMORY.md's 2200-char cap.
    We install ONE rule. It should leave plenty of room for the user's
    own entries — target <600 chars."""
    from memory_rules import MEMORY_MD_RULE

    assert 0 < len(MEMORY_MD_RULE) < 600, (
        f"MEMORY_MD_RULE is {len(MEMORY_MD_RULE)} chars — too big. "
        "The whole point is staying small."
    )


def test_canonical_user_rule_is_short():
    """USER.md is even tighter (1375 chars). Target <400."""
    from memory_rules import USER_MD_RULE

    assert 0 < len(USER_MD_RULE) < 400


def test_memory_rule_names_mastra_tools():
    """The rule must explicitly point at the three tools so the agent
    learns the routing without us having to repeat ourselves elsewhere."""
    from memory_rules import MEMORY_MD_RULE

    for tool in ("mastra_observe", "mastra_recall", "mastra_search"):
        assert tool in MEMORY_MD_RULE, f"missing reference to {tool}"


def test_user_rule_names_mastra_observe():
    from memory_rules import USER_MD_RULE

    assert "mastra_observe" in USER_MD_RULE


def test_rules_specify_what_stays_local():
    """Both rules must spell out what STAYS in built-in memory so the
    agent doesn't end up offloading literally everything (defeating the
    point of having a frozen system-prompt block)."""
    from memory_rules import MEMORY_MD_RULE, USER_MD_RULE

    # MEMORY.md keeps environment facts + project conventions small
    assert "environment" in MEMORY_MD_RULE.lower() or "convention" in MEMORY_MD_RULE.lower()
    # USER.md keeps name + communication style
    assert "name" in USER_MD_RULE.lower()


# ---- idempotent installation --------------------------------------------


def test_install_creates_rule_in_empty_memory_md(memories_dir):
    from memory_rules import install_memory_rules

    install_memory_rules()
    text = (memories_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "mastra" in text


def test_install_creates_rule_in_empty_user_md(memories_dir):
    from memory_rules import install_memory_rules

    install_memory_rules()
    text = (memories_dir / "USER.md").read_text(encoding="utf-8")
    assert "mastra" in text


def test_install_is_idempotent(memories_dir):
    """Running twice doesn't duplicate the rule."""
    from memory_rules import install_memory_rules

    install_memory_rules()
    install_memory_rules()
    install_memory_rules()
    mem = (memories_dir / "MEMORY.md").read_text(encoding="utf-8")
    usr = (memories_dir / "USER.md").read_text(encoding="utf-8")
    # The rule's anchor string appears exactly once
    assert mem.count("[mastra-rule]") == 1
    assert usr.count("[mastra-rule]") == 1


def test_install_preserves_existing_user_entries(memories_dir):
    """If MEMORY.md already has user-curated entries, install must
    APPEND the rule, not overwrite the file."""
    pre = "User runs macOS 14, Bun installed.\n§\nProject uses Go 1.22."
    (memories_dir / "MEMORY.md").write_text(pre, encoding="utf-8")
    from memory_rules import install_memory_rules

    install_memory_rules()
    text = (memories_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "macOS 14" in text
    assert "Go 1.22" in text
    assert "[mastra-rule]" in text


def test_uninstall_removes_only_the_canonical_rule(memories_dir):
    """When the plugin is removed, the rule should be cleanly excisable
    without touching anything else."""
    pre = "User runs macOS.\n§\nProject Go 1.22."
    (memories_dir / "MEMORY.md").write_text(pre, encoding="utf-8")
    from memory_rules import install_memory_rules, uninstall_memory_rules

    install_memory_rules()
    uninstall_memory_rules()
    text = (memories_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "[mastra-rule]" not in text
    assert "macOS" in text
    assert "Go 1.22" in text


# ---- post_setup wiring ---------------------------------------------------


def test_post_setup_calls_install_memory_rules(monkeypatch, memories_dir):
    """post_setup should install the rules so users don't have to think
    about it. Bun install + server start are mocked out so this stays fast."""
    import sys
    import types

    # Stub Hermes deps the provider imports.
    if "agent" not in sys.modules:
        sys.modules["agent"] = types.ModuleType("agent")
    if "agent.memory_provider" not in sys.modules:
        mp = types.ModuleType("agent.memory_provider")
        mp.MemoryProvider = type("S", (), {})
        sys.modules["agent.memory_provider"] = mp
    if "tools" not in sys.modules:
        sys.modules["tools"] = types.ModuleType("tools")
    if "tools.registry" not in sys.modules:
        reg = types.ModuleType("tools.registry")
        reg.tool_error = lambda m: m
        sys.modules["tools.registry"] = reg

    # Skip the bun install + server start side-effects — only memory rules matter here.
    import server_manager

    monkeypatch.setattr(server_manager, "install_dependencies", lambda: (True, "stub"))
    monkeypatch.setattr(server_manager, "start_server", lambda *a, **kw: (True, "stub"))

    import provider

    p = provider.MastraMemoryProvider()
    p.post_setup(str(memories_dir.parent), {})

    text = (memories_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "[mastra-rule]" in text
