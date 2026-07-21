"""Scoring strategies: novelty, per-stream adaptive threshold, composition."""
from ai_kontinuum_monitor.scoring import (
    AdaptiveThresholdStrategy,
    AnomalyScorer,
    CompositeStrategy,
    NoveltyStrategy,
    default_strategy,
)


def _obs(action, surprise, novel):
    return {"action": action, "surprise": surprise, "is_novel": novel, "threshold": 0.0}


def test_novelty_flags_only_first_occurrence():
    s = NoveltyStrategy()
    assert s.evaluate(_obs("a", 0.8, True)).is_anomaly is True
    assert s.evaluate(_obs("a", 0.8, False)).is_anomaly is False


def test_adaptive_silent_during_warmup():
    s = AdaptiveThresholdStrategy(warmup=100)
    # A wild swing before warmup is not flagged (unless novel).
    for i in range(20):
        r = s.evaluate(_obs("x", 0.9 if i == 10 else 0.2, i == 0))
        if i not in (0,):
            assert r.is_anomaly is False


def test_adaptive_flags_spike_after_warmup():
    s = AdaptiveThresholdStrategy(window=300, warmup=100)
    for i in range(120):
        s.evaluate(_obs("x", 0.2, i == 0))
    assert s.evaluate(_obs("x", 0.95, False)).is_anomaly is True
    assert s.evaluate(_obs("x", 0.22, False)).is_anomaly is False


def test_adaptive_steady_stream_not_flagged_by_wobble():
    """A flat stream must not collapse the band onto its median (min_spread)."""
    s = AdaptiveThresholdStrategy(window=300, warmup=50, min_spread=0.2)
    for i in range(80):
        s.evaluate(_obs("x", 0.50, i == 0))
    # A small wobble within min_spread stays quiet.
    assert s.evaluate(_obs("x", 0.60, False)).is_anomaly is False
    # A clear jump past median+min_spread fires.
    assert s.evaluate(_obs("x", 0.80, False)).is_anomaly is True


def test_composite_or_merges_reasons():
    c = CompositeStrategy([NoveltyStrategy(), AdaptiveThresholdStrategy()], mode="or")
    r = c.evaluate(_obs("a", 0.9, True))
    assert r.is_anomaly is True
    assert any("novelty" in x for x in r.reasons)


def test_composite_dedupes_shared_reason():
    """Two strategies both reporting 'never-seen action' collapse to one line."""
    c = CompositeStrategy([NoveltyStrategy(), AdaptiveThresholdStrategy()], mode="or")
    r = c.evaluate(_obs("a", 0.9, True))
    never_seen = [x for x in r.reasons if "never-seen action" in x]
    assert len(never_seen) == 1


def test_composite_and_requires_all():
    c = CompositeStrategy([NoveltyStrategy(), AdaptiveThresholdStrategy()], mode="and")
    # Novel but adaptive is in warmup → novelty True, adaptive True (novel path).
    assert c.evaluate(_obs("a", 0.9, True)).is_anomaly is True
    # Known + calm → neither fires.
    assert c.evaluate(_obs("a", 0.2, False)).is_anomaly is False


def test_scorer_tracks_stream_stats():
    scorer = AnomalyScorer(strategy=default_strategy())
    scorer.score(_obs("a", 0.9, True))
    scorer.score(_obs("a", 0.2, False))
    scorer.score(_obs("b", 0.9, True))
    stats = scorer.stream_stats()
    assert stats["a"]["observations"] == 2
    assert stats["a"]["anomalies"] == 1
    assert stats["b"]["anomalies"] == 1
    # Per-stream trend is surfaced alongside the counts.
    assert "surprise_trend" in stats["a"]


def test_adaptive_early_engagement_catches_spike_before_full_warmup():
    """A clear spike is caught in the early window, before ``warmup`` samples."""
    s = AdaptiveThresholdStrategy(warmup=100, early_warmup=20)
    for i in range(30):  # < warmup but > early_warmup
        s.evaluate(_obs("x", 0.20, i == 0))
    r = s.evaluate(_obs("x", 0.95, False))
    assert r.is_anomaly is True
    assert any("early" in reason for reason in r.reasons)


def test_adaptive_early_engagement_disabled_stays_silent():
    """With early_warmup=None the old, fully-conservative behaviour holds."""
    s = AdaptiveThresholdStrategy(warmup=100, early_warmup=None)
    for i in range(30):
        s.evaluate(_obs("x", 0.20, i == 0))
    assert s.evaluate(_obs("x", 0.95, False)).is_anomaly is False


def test_early_window_does_not_flag_small_wobble():
    s = AdaptiveThresholdStrategy(warmup=100, early_warmup=20, min_spread=0.2)
    for i in range(30):
        s.evaluate(_obs("x", 0.50, i == 0))
    # Wobble within the widened early band stays quiet.
    assert s.evaluate(_obs("x", 0.62, False)).is_anomaly is False


def test_scorer_metrics_learning_progress_and_trend():
    scorer = AnomalyScorer(strategy=default_strategy())
    # Rising surprise on a known stream → positive trend.
    scorer.score({"action": "a", "surprise": 0.1, "is_novel": True,
                  "threshold": 0.0, "learning_state": "cold_start"})
    for v in [0.1, 0.15, 0.2, 0.5, 0.6, 0.7, 0.8]:
        scorer.score({"action": "a", "surprise": v, "is_novel": False,
                      "threshold": 0.0, "learning_state": "warming"})
    m = scorer.metrics()
    assert m["observations"] == 8
    assert m["learning_state"] == "warming"
    assert 0.0 <= m["learning_progress"] <= 1.0
    assert m["learning_progress_pct"] == round(100 * m["learning_progress"], 1)
    assert m["surprise_trend"] > 0  # surprise is rising


def test_learning_progress_caps_at_one():
    scorer = AnomalyScorer(strategy=default_strategy())
    scorer._total_observations = 5000  # beyond MATURE_EVENTS
    assert scorer.learning_progress() == 1.0
