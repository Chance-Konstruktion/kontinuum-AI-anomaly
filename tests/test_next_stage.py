"""Tests for the next-stage features (GrokAI improvement list):

sequence-awareness, cross-stream correlation, strategy presets,
alerting escalation + snooze, LLM feedback loop, long-term pattern analysis.

All are additive layers over an untouched kontinuum-core.
"""
from datetime import datetime, timedelta, timezone

import pytest

from kontinuum_ai_anomaly import (
    AlertRouter,
    AnomalyHistory,
    AnomalyRecord,
    AnomalyScorer,
    CrossStreamCorrelator,
    LLMFeedbackSink,
    LogSink,
    MultiAgentWatch,
    SequenceStrategy,
    builtin_presets,
    escalation_level,
    export_preset,
    import_preset,
    save_preset,
    load_preset,
    sequence_aware_strategy,
)


def _obs(action, *, novel=False, surprise=0.5):
    return {"action": action, "is_novel": novel, "surprise": surprise,
            "threshold": 0.4, "learning_state": "cold_start"}


# --------------------------------------------------------------------------
# 1. Sequence awareness
# --------------------------------------------------------------------------
def test_sequence_flags_unexpected_transition():
    strat = SequenceStrategy(min_context=5, min_prob=0.0)
    # Teach a strict rhythm a -> b -> a -> b ...
    for _ in range(10):
        strat.evaluate(_obs("a"))
        strat.evaluate(_obs("b"))
    # After "a", "b" is expected -> not anomalous.
    strat.evaluate(_obs("a"))
    ok = strat.evaluate(_obs("b"))
    assert not ok.is_anomaly
    # A never-seen transition a -> c is a sequence anomaly.
    strat.evaluate(_obs("a"))
    bad = strat.evaluate(_obs("c"))
    assert bad.is_anomaly
    assert "transition" in "; ".join(bad.reasons)


def test_sequence_needs_context_before_judging():
    strat = SequenceStrategy(min_context=5, min_prob=0.0)
    strat.evaluate(_obs("a"))
    # Only one prior observation of "a" -> below min_context -> no flag yet.
    res = strat.evaluate(_obs("zzz"))
    assert not res.is_anomaly


def test_sequence_flags_rare_known_transition_at_probability_boundary():
    strat = SequenceStrategy(min_context=10, min_prob=0.1)
    for _ in range(9):
        strat.evaluate(_obs("a"))
        strat.evaluate(_obs("b"))
    strat.evaluate(_obs("a"))
    strat.evaluate(_obs("c"))

    strat.evaluate(_obs("a"))
    rare = strat.evaluate(_obs("c"))

    assert rare.is_anomaly
    assert rare.score == 0.9
    assert any("rare transition" in reason for reason in rare.reasons)


def test_sequence_leaves_novel_actions_to_novelty_strategy():
    strat = SequenceStrategy(min_context=3, min_prob=0.0)
    for _ in range(5):
        strat.evaluate(_obs("a"))
        strat.evaluate(_obs("b"))

    strat.evaluate(_obs("a"))
    result = strat.evaluate(_obs("brand_new", novel=True, surprise=0.95))

    assert result.is_anomaly is False
    assert result.reasons == []


def test_sequence_aware_strategy_factory():
    strat = sequence_aware_strategy()
    names = {s.name for s in strat.strategies}
    assert names == {"novelty", "adaptive", "sequence"}


# --------------------------------------------------------------------------
# 2. Cross-stream correlation
# --------------------------------------------------------------------------
def test_correlator_finds_cross_agent_cluster():
    corr = CrossStreamCorrelator(window_seconds=30)
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    corr.record("agentA", "escalate", 0.9, ts=base)
    corr.record("agentB", "crash", 0.8, ts=base + timedelta(seconds=10))
    corr.record("agentA", "retry", 0.5, ts=base + timedelta(hours=2))  # isolated
    clusters = corr.clusters(min_agents=2)
    assert len(clusters) == 1
    assert set(clusters[0]["agents"]) == {"agentA", "agentB"}
    assert clusters[0]["size"] == 2


def test_multi_agent_watch_routes_and_correlates(tmp_path):
    maw = MultiAgentWatch(window_seconds=60, brain_dir=str(tmp_path / "b"),
                          history_dir=str(tmp_path / "h"))
    base = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)
    # Warm both agents on a normal rhythm.
    for i in range(20):
        for a in ("plan", "act", "done"):
            maw.observe("botX", a, ts=base + timedelta(seconds=i * 300))
            maw.observe("botY", a, ts=base + timedelta(seconds=i * 300 + 5))
    # Both hit a novel action within the window.
    t = base + timedelta(hours=5)
    rx = maw.observe("botX", "meltdown", ts=t)
    ry = maw.observe("botY", "meltdown", ts=t + timedelta(seconds=15))
    assert rx.is_anomaly and ry.is_anomaly
    clusters = maw.correlated_clusters(min_agents=2)
    assert clusters and set(clusters[-1]["agents"]) == {"botX", "botY"}
    maw.save()
    assert (tmp_path / "b" / "botX.json").exists()


# --------------------------------------------------------------------------
# 3. Strategy presets — export / import
# --------------------------------------------------------------------------
def test_preset_roundtrip_preserves_params():
    strat = sequence_aware_strategy()
    # Tune a param so we can prove it survives the round-trip.
    strat.strategies[1].k = 4.2
    preset = export_preset(strat, name="tuned")
    rebuilt = import_preset(preset)
    assert rebuilt.strategies[1].k == 4.2
    assert {s.name for s in rebuilt.strategies} == {"novelty", "adaptive", "sequence"}


def test_preset_file_roundtrip(tmp_path):
    p = tmp_path / "preset.json"
    save_preset(builtin_presets()["sensitive"], str(p), name="sensitive")
    rebuilt = load_preset(str(p))
    assert rebuilt.mode == "or"


def test_builtin_presets_all_score():
    for name, strat in builtin_presets().items():
        scorer = AnomalyScorer(strategy=strat)
        res = scorer.score(_obs("new_action", novel=True, surprise=0.9))
        assert res.is_anomaly, name


# --------------------------------------------------------------------------
# 4. Alerting — escalation levels + snooze
# --------------------------------------------------------------------------
def _rec(action="x", score=0.5, novel=False):
    return AnomalyRecord(
        action=action, score=score, surprise=score, threshold=0.4,
        is_novel=novel, reasons=["r"], strategy="s",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
    )


def test_escalation_levels():
    assert escalation_level(_rec(score=0.1)) == "info"
    assert escalation_level(_rec(score=0.5)) == "warning"
    assert escalation_level(_rec(score=0.9)) == "critical"
    # Novel floors to warning even with a low score.
    assert escalation_level(_rec(score=0.05, novel=True)) == "warning"


def test_router_min_level_filters_sink():
    delivered = []

    class Cap:
        name = "cap"

        def deliver(self, rec):
            delivered.append(rec.action)
            return True

    router = AlertRouter([(Cap(), "critical")])
    router.route(_rec("low", score=0.5))   # warning -> filtered out
    assert delivered == []
    router.route(_rec("high", score=0.95))  # critical -> delivered
    assert delivered == ["high"]


def test_router_snooze():
    delivered = []

    class Cap:
        name = "cap"

        def deliver(self, rec):
            delivered.append(rec.action)
            return True

    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    router = AlertRouter([Cap()])
    router.snooze("flappy", 100, now=now)
    r1 = router.route(_rec("flappy", score=0.9), now=now + timedelta(seconds=10))
    assert r1["delivered"] is False and r1["reason"] == "snoozed"
    # After the window it delivers again.
    r2 = router.route(_rec("flappy", score=0.9), now=now + timedelta(seconds=200))
    assert r2["delivered"] is True
    assert delivered == ["flappy"]


# --------------------------------------------------------------------------
# 5. LLM feedback loop
# --------------------------------------------------------------------------
def test_llm_feedback_sink_builds_prompt_and_captures_reply():
    seen = {}

    def fake_llm(prompt):
        seen["prompt"] = prompt
        return "verdict: investigate; next: check logs"

    replies = []
    sink = LLMFeedbackSink(
        fake_llm,
        context_provider=lambda: "engine is warming",
        on_reply=lambda rec, reply: replies.append((rec.action, reply)),
    )
    ok = sink.deliver(_rec("escalate", score=0.9, novel=True))
    assert ok
    assert "escalate" in seen["prompt"]
    assert "engine is warming" in seen["prompt"]
    assert sink.last_reply.startswith("verdict")
    assert replies and replies[0][0] == "escalate"


def test_llm_feedback_sink_survives_bad_model_and_respects_cap():
    def boom(prompt):
        raise RuntimeError("model down")

    sink = LLMFeedbackSink(boom)
    assert sink.deliver(_rec()) is False  # error swallowed, routing safe

    calls = []
    sink2 = LLMFeedbackSink(lambda p: calls.append(1) or "ok", max_calls=1)
    assert sink2.deliver(_rec("a")) is True
    assert sink2.deliver(_rec("b")) is False  # capped
    assert sink2.skipped == 1


# --------------------------------------------------------------------------
# 6. Long-term analysis — patterns over weeks
# --------------------------------------------------------------------------
def test_history_patterns_over_weeks():
    hist = AnomalyHistory()
    base = datetime(2025, 1, 6, 9, 0, tzinfo=timezone.utc)  # a Monday
    # "escalate" recurs in two different weeks; "blip" only once.
    for wk in range(3):
        for _ in range(2):
            hist.record(AnomalyRecord(
                action="escalate", score=0.9, surprise=0.9, threshold=0.4,
                is_novel=False, reasons=[], strategy="s",
                ts=(base + timedelta(weeks=wk)).isoformat(),
            ))
    hist.record(AnomalyRecord(
        action="blip", score=0.5, surprise=0.5, threshold=0.4,
        is_novel=False, reasons=[], strategy="s", ts=base.isoformat(),
    ))
    pat = hist.patterns()
    assert pat["weeks_observed"] == 3
    assert pat["total"] == 7
    assert "escalate" in pat["recurring_actions"]
    assert "blip" not in pat["recurring_actions"]
    assert pat["by_weekday"]["Mon"] == 7
    assert pat["by_hour"][9] == 7
