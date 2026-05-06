"""Tests for flexible Mastra Memory configuration passthrough.

The plugin must let users pass ANY supported Mastra `MemoryOptions` field
through to the underlying `new Memory({ options })` call on the TS server,
with no Python-side knowledge of the schema. The Python plugin is a dumb
JSON courier; Mastra is the source of truth.

Goal: a user who reads the Mastra docs at
https://mastra.ai/reference/memory/Memory should be able to set ANY
documented option via:

    hermes mastra mastra set <dotted.key> <json-value>

…or by editing `~/.hermes/mastra.json` under the `"mastra"` key.

Behaviors covered:
  - Arbitrary mastra.<key> values round-trip through config.
  - Nested keys (e.g. `mastra.workingMemory.scope`) are stored as nested JSON.
  - The TS server receives the merged JSON via env var MASTRA_OPTIONS_JSON.
  - Plugin defaults still apply when user supplies no `mastra.*` keys.
  - User-supplied keys override plugin defaults.
  - Boolean / number / array / null values are preserved (not stringified).
  - `mastra reset` clears all custom mastra config.
  - Validation: rejects malformed JSON values via the public setter.
"""

from __future__ import annotations

import json

import pytest

# ---- get / set roundtrip ---------------------------------------------------


def test_default_mastra_options_includes_observational_memory(fake_hermes_home):
    import mastra_options as mo

    opts = mo.resolve_options()
    assert "observationalMemory" in opts
    # Observational memory MUST be enabled by default — that's the whole plugin.
    assert opts["observationalMemory"] not in (False, None, {})


def _assert_default_processor_options(opts: dict) -> None:
    assert opts["workingMemory"]["enabled"] is True
    assert opts["workingMemory"]["scope"] == "resource"
    assert "# Hermes Working Memory" in opts["workingMemory"]["template"]
    assert opts["lastMessages"] == 20
    assert opts["semanticRecall"] == {
        "topK": 5,
        "messageRange": {"before": 2, "after": 2},
        "scope": "resource",
        "threshold": 0.65,
    }
    assert opts["filterIncompleteToolCalls"] is True
    assert "processors" not in opts


def _assert_default_observational_memory(om: dict) -> None:
    assert om["enabled"] is True
    assert om["retrieval"] == {"vector": True, "scope": "resource"}
    assert om["activateAfterIdle"] == "5m"
    assert om["activateOnProviderChange"] is True
    assert om["observation"]["messageTokens"] == 60_000
    assert om["observation"]["maxTokensPerBatch"] == 40_000
    assert om["observation"]["bufferTokens"] == 0.2
    assert om["observation"]["bufferActivation"] == 0.8
    assert om["observation"]["blockAfter"] == 1.2
    assert om["observation"]["previousObserverTokens"] == 10_000
    assert om["observation"]["threadTitle"] is True
    assert om["observation"]["modelSettings"]["maxOutputTokens"] == 100_000
    assert om["reflection"]["observationTokens"] == 80_000
    assert om["reflection"]["bufferActivation"] == 0.5
    assert om["reflection"]["blockAfter"] == 1.2
    assert om["reflection"]["modelSettings"]["maxOutputTokens"] == 100_000


def test_default_observer_and_reflector_have_large_output_budgets(fake_hermes_home):
    import mastra_options as mo

    opts = mo.resolve_options()
    _assert_default_processor_options(opts)
    _assert_default_observational_memory(opts["observationalMemory"])


def test_set_top_level_key_persists(fake_hermes_home):
    import mastra_options as mo

    mo.set_option("lastMessages", 50)
    assert mo.resolve_options()["lastMessages"] == 50


def test_set_nested_dotted_key(fake_hermes_home):
    import mastra_options as mo

    mo.set_option("workingMemory.scope", "thread")
    opts = mo.resolve_options()
    assert opts["workingMemory"]["scope"] == "thread"
    # Sibling defaults must survive a nested write
    assert opts["workingMemory"]["enabled"] is True


def test_deeply_nested_keys(fake_hermes_home):
    import mastra_options as mo

    mo.set_option("observationalMemory.observation.messageTokens", 4000)
    mo.set_option("observationalMemory.reflection.observationTokens", 12000)
    opts = mo.resolve_options()
    assert opts["observationalMemory"]["observation"]["messageTokens"] == 4000
    assert opts["observationalMemory"]["reflection"]["observationTokens"] == 12000


def test_user_overrides_default(fake_hermes_home):
    import mastra_options as mo

    default = mo.resolve_options()["observationalMemory"]["scope"]
    new = "resource" if default == "thread" else "thread"
    mo.set_option("observationalMemory.scope", new)
    assert mo.resolve_options()["observationalMemory"]["scope"] == new


# ---- value types -----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        0,
        42,
        -1,
        3.14,
        "string-value",
        [1, 2, 3],
        ["a", "b"],
        {"nested": {"deep": True}},
        None,
    ],
)
def test_arbitrary_json_value_roundtrip(fake_hermes_home, value):
    import mastra_options as mo

    mo.set_option("custom_field", value)
    assert mo.resolve_options()["custom_field"] == value


# ---- precedence ------------------------------------------------------------


def test_explicit_top_level_legacy_field_still_works(fake_hermes_home):
    """Old configs that set top-level keys like `temporal_markers` (snake_case)
    must continue mapping to the equivalent Mastra option."""
    import json

    cfg_path = fake_hermes_home / "mastra.json"
    cfg_path.write_text(
        json.dumps(
            {
                "temporal_markers": False,
                "share_token_budget": True,
            }
        ),
        encoding="utf-8",
    )
    import importlib

    import mastra_options as mo

    importlib.reload(mo)
    opts = mo.resolve_options()
    assert opts["observationalMemory"]["temporalMarkers"] is False
    assert opts["observationalMemory"]["shareTokenBudget"] is True


# ---- env var serialization for the TS server -------------------------------


def test_env_payload_is_valid_json(fake_hermes_home):
    """The Bun server reads MASTRA_OPTIONS_JSON; payload must be a single
    JSON string of the merged options."""
    import mastra_options as mo

    mo.set_option(
        "workingMemory.schema", {"type": "object", "properties": {"foo": {"type": "string"}}}
    )
    payload = mo.options_env_payload()
    parsed = json.loads(payload)
    assert parsed["workingMemory"]["schema"]["properties"]["foo"]["type"] == "string"


def test_env_payload_omits_disabled_features_correctly(fake_hermes_home):
    import mastra_options as mo

    mo.set_option("semanticRecall", False)
    payload = mo.options_env_payload()
    parsed = json.loads(payload)
    # Boolean false must survive serialization (NOT be dropped)
    assert parsed["semanticRecall"] is False


# ---- reset / unset --------------------------------------------------------


def test_unset_removes_key(fake_hermes_home):
    import mastra_options as mo

    mo.set_option("lastMessages", 100)
    assert mo.resolve_options()["lastMessages"] == 100
    mo.unset_option("lastMessages")
    # After unset, the key is gone or returns to its built-in default
    opts = mo.resolve_options()
    assert opts.get("lastMessages") != 100


def test_reset_wipes_all_user_overrides(fake_hermes_home):
    import mastra_options as mo

    mo.set_option("lastMessages", 999)
    mo.set_option("workingMemory.scope", "thread")
    mo.set_option("custom_field", "hello")
    mo.reset_options()
    opts = mo.resolve_options()
    assert opts.get("lastMessages") != 999
    assert opts["workingMemory"]["scope"] == "resource"  # back to default
    assert "custom_field" not in opts


# ---- error paths ----------------------------------------------------------


def test_set_rejects_empty_dotted_key(fake_hermes_home):
    import mastra_options as mo

    with pytest.raises(ValueError, match="key"):
        mo.set_option("", 1)


def test_set_rejects_dotted_key_with_blank_segment(fake_hermes_home):
    import mastra_options as mo

    with pytest.raises(ValueError, match="key"):
        mo.set_option("observationalMemory..scope", "thread")


def test_set_rejects_value_overwriting_intermediate_scalar(fake_hermes_home):
    """Trying to set `a.b` when `a` is already a scalar string is ambiguous."""
    import mastra_options as mo

    mo.set_option("a", "im a scalar")
    with pytest.raises(ValueError, match="scalar"):
        mo.set_option("a.b", "wat")
