"""Strategy presets — export / import scoring configurations as JSON.

GrokAI's "Export / Import von Konfigurationen (Strategie-Presets)". A tuned
scoring setup (which strategies, with which thresholds) is worth saving and
sharing between deployments. This module serializes a :class:`ScoringStrategy`
tree to a plain JSON-able dict and rebuilds it, plus a small library of named
built-in presets.

Only the strategies defined in :mod:`.scoring` are supported; the format is a
declarative spec (``{"type": ..., "params": {...}}``), never pickled code, so a
preset file is safe to read and diff.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from .scoring import (
    AdaptiveThresholdStrategy,
    CompositeStrategy,
    NoveltyStrategy,
    ScoringStrategy,
    SequenceStrategy,
    default_strategy,
    sequence_aware_strategy,
)

PRESET_VERSION = 1

# Constructor param names we round-trip per strategy type. Anything else on the
# instance is left at its class default on rebuild.
_PARAMS: Dict[str, List[str]] = {
    "novelty": [],
    "adaptive": [
        "window", "k", "warmup", "floor", "min_spread",
        "early_warmup", "early_k_boost",
    ],
    "sequence": ["min_context", "min_prob"],
}
_TYPES = {
    "novelty": NoveltyStrategy,
    "adaptive": AdaptiveThresholdStrategy,
    "sequence": SequenceStrategy,
}


def strategy_to_spec(strategy: ScoringStrategy) -> Dict[str, Any]:
    """Serialize a strategy (including a CompositeStrategy tree) to a dict."""
    if isinstance(strategy, CompositeStrategy):
        return {
            "type": "composite",
            "mode": strategy.mode,
            "strategies": [strategy_to_spec(s) for s in strategy.strategies],
        }
    stype = getattr(strategy, "name", None)
    if stype not in _PARAMS:
        raise ValueError(f"cannot serialize strategy {strategy!r} (type {stype!r})")
    params = {p: getattr(strategy, p) for p in _PARAMS[stype]}
    return {"type": stype, "params": params}


def strategy_from_spec(spec: Dict[str, Any]) -> ScoringStrategy:
    """Rebuild a strategy from a spec produced by :func:`strategy_to_spec`."""
    stype = spec.get("type")
    if stype == "composite":
        subs = [strategy_from_spec(s) for s in spec.get("strategies", [])]
        return CompositeStrategy(subs, mode=spec.get("mode", "or"))
    if stype not in _TYPES:
        raise ValueError(f"unknown strategy type {stype!r}")
    params = {
        k: v for k, v in (spec.get("params") or {}).items() if k in _PARAMS[stype]
    }
    return _TYPES[stype](**params)


def export_preset(strategy: ScoringStrategy, *, name: str = "custom") -> Dict[str, Any]:
    """Wrap a strategy spec in a versioned, named preset envelope."""
    return {
        "version": PRESET_VERSION,
        "name": name,
        "strategy": strategy_to_spec(strategy),
    }


def import_preset(preset: Dict[str, Any]) -> ScoringStrategy:
    """Rebuild the strategy from a preset envelope (or a bare spec)."""
    if "strategy" in preset:
        return strategy_from_spec(preset["strategy"])
    return strategy_from_spec(preset)  # tolerate a bare spec


def save_preset(strategy: ScoringStrategy, path: str, *, name: str = "custom") -> None:
    """Write a preset to ``path`` as JSON (atomic replace)."""
    payload = export_preset(strategy, name=name)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


def load_preset(path: str) -> ScoringStrategy:
    """Read a preset JSON file and rebuild its strategy."""
    with open(path, "r", encoding="utf-8") as fh:
        return import_preset(json.load(fh))


def builtin_presets() -> Dict[str, ScoringStrategy]:
    """Named, ready-to-use strategy presets.

    * ``default`` — novelty OR per-stream adaptive threshold (the package default).
    * ``sequence_aware`` — adds first-order sequence anomalies on top.
    * ``novelty_only`` — the most conservative: flag only never-seen actions.
    * ``sensitive`` — sequence-aware with lowered bars for early, noisy streams.
    """
    return {
        "default": default_strategy(),
        "sequence_aware": sequence_aware_strategy(),
        "novelty_only": NoveltyStrategy(),
        "sensitive": CompositeStrategy(
            [
                NoveltyStrategy(),
                AdaptiveThresholdStrategy(warmup=50, k=2.5, floor=0.3),
                SequenceStrategy(min_context=10, min_prob=0.05),
            ],
            mode="or",
        ),
    }
