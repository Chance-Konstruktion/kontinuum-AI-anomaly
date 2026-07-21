"""Strategy presets: round-trip serialization, built-ins, safety."""
import json

import pytest

from ai_kontinuum_monitor import (
    AdaptiveThresholdStrategy,
    CompositeStrategy,
    NoveltyStrategy,
    SequenceStrategy,
    builtin_presets,
    export_preset,
    import_preset,
    load_preset,
    save_preset,
    sequence_aware_strategy,
)
from ai_kontinuum_monitor.presets import PRESET_VERSION, strategy_to_spec


def test_roundtrip_composite_preserves_params():
    strat = CompositeStrategy(
        [
            NoveltyStrategy(),
            AdaptiveThresholdStrategy(window=123, k=2.7, warmup=50),
            SequenceStrategy(min_context=7, min_prob=0.05),
        ],
        mode="or",
    )
    rebuilt = import_preset(export_preset(strat, name="t"))
    assert isinstance(rebuilt, CompositeStrategy)
    assert rebuilt.mode == "or"
    adaptive = rebuilt.strategies[1]
    assert isinstance(adaptive, AdaptiveThresholdStrategy)
    assert (adaptive.window, adaptive.k, adaptive.warmup) == (123, 2.7, 50)
    seq = rebuilt.strategies[2]
    assert (seq.min_context, seq.min_prob) == (7, 0.05)


def test_export_envelope_is_versioned_and_named():
    env = export_preset(NoveltyStrategy(), name="just-novelty")
    assert env["version"] == PRESET_VERSION
    assert env["name"] == "just-novelty"
    assert env["strategy"]["type"] == "novelty"


def test_import_tolerates_bare_spec():
    spec = strategy_to_spec(NoveltyStrategy())
    assert isinstance(import_preset(spec), NoveltyStrategy)


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "preset.json")
    strat = sequence_aware_strategy()
    save_preset(strat, path, name="seq")
    # File is human-readable JSON, not pickled code.
    with open(path) as fh:
        data = json.load(fh)
    assert data["name"] == "seq"
    reloaded = load_preset(path)
    assert isinstance(reloaded, CompositeStrategy)
    assert len(reloaded.strategies) == 3


def test_unknown_type_rejected():
    with pytest.raises(ValueError):
        import_preset({"strategy": {"type": "not_a_strategy"}})


def test_all_builtin_presets_roundtrip():
    for name, strat in builtin_presets().items():
        rebuilt = import_preset(export_preset(strat, name=name))
        # Round-tripping a built-in yields an equivalent spec.
        assert strategy_to_spec(rebuilt) == strategy_to_spec(strat)
