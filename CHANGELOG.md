# Changelog

All notable changes to `ai-kontinuum-monitor` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/); this project adheres to
[Semantic Versioning](https://semver.org/).

## [0.2.0] — Next-stage improvements

Implements the next-stage improvement list (sequence-awareness, cross-stream
correlation, config presets, alerting escalation/snooze, LLM feedback loop,
long-term analysis). Every item is an **additive layer in this package** —
`kontinuum-core` is untouched, so its Home-Assistant ingestion path is
unchanged. All new behaviour is opt-in; existing call sites keep working.

### Added

- **Sequence-awareness (`SequenceStrategy`)** — a first-order (bigram)
  transition model in the monitor layer catches an action arriving in an
  unexpected *order* (never-seen / rare transition), the signal core is weak on.
  Wire it in via the new `sequence_aware_strategy()` factory (novelty OR
  adaptive OR sequence). This addresses the "sequence-awareness" item *without*
  a core change — it lives entirely on top of core.
- **Cross-stream correlation (`correlation.py`)** — `CrossStreamCorrelator`
  finds anomalies that co-occur across different agents within a time window,
  and `MultiAgentWatch` runs one `AnomalyWatch` per agent (own brain/ledger)
  while feeding every flagged anomaly into the shared correlator;
  `correlated_clusters()` surfaces multi-agent incidents.
- **Strategy presets (`presets.py`)** — export/import a scoring configuration as
  safe declarative JSON (`export_preset`/`import_preset`, `save_preset`/
  `load_preset`), plus named `builtin_presets()` (`default`, `sequence_aware`,
  `novelty_only`, `sensitive`).
- **Alerting escalation + snooze** — `escalation_level()` maps a score to
  `info`/`warning`/`critical` (novel actions floored to `warning`); `AlertRouter`
  accepts `(sink, min_level)` pairs so each sink only fires at/above its level,
  and gains `snooze()`/`unsnooze()` to mute a known-flapping action for a window.
- **LLM feedback loop (`feedback.py`)** — `LLMFeedbackSink` is an alert sink that
  builds a compact prompt from the anomaly (plus optional live engine context)
  and calls a user-supplied `llm(prompt) -> str`. Provider-agnostic, no new hard
  dependency; model/handler errors are swallowed so routing can't break, with an
  optional `max_calls` cost guard.
- **Long-term analysis** — `AnomalyHistory.patterns(weeks=…)` buckets anomalies
  by ISO week / weekday / hour and reports *recurring* actions (flagged in 2+
  weeks) — "Anomalie-Muster über Wochen".

## [Unreleased]

Constructive-improvement pass — addresses feedback on threshold latency,
missing run-wide metrics, dashboard interactivity, and clock configurability.
All changes are additive and backward-compatible; existing call sites keep
their behaviour unless they opt into the new parameters.

### Added

- **Run-wide metrics** — `AnomalyScorer.metrics()` (and pass-through
  `AnomalyWatch.metrics()`) report `learning_progress` / `learning_progress_pct`
  (event volume toward core's maturity threshold, SPEC §5.4) and a signed
  `surprise_trend` (recent-half mean vs. older-half mean — positive = drifting
  more surprising). `stream_stats()` now also carries a per-stream
  `surprise_trend`.
- **Earlier adaptive engagement** — `AdaptiveThresholdStrategy` gained an
  `early_warmup` window (default 20): a *provisional*, deliberately widened
  per-stream test runs on partial history so short or very stable streams react
  before the full 100-sample warmup instead of staying blind. Set
  `early_warmup=None` to keep the previous fully-conservative behaviour.
- **Interactive dashboard** — `render_dashboard()` timeline is now filterable
  (inline search box + novel/outlier toggle, self-contained inline JS, still no
  external assets) and can render learning-progress / surprise-trend / mean
  cards when passed the optional `metrics=` dict.
- **Configurable virtual clock** — `AgentMonitor(step_seconds=…)` lets callers
  widen event spacing for genuinely high-frequency replays; clamped to the
  burst-safe default so it can't reintroduce silent drops (SPEC §5.5).

## [0.1.0] - 2026-07-20

Initial release: an anomaly / novelty monitor for agent action streams, built as
a thin, additive layer over `kontinuum-core` (core stays untouched).

### Added

- **`AgentMonitor`** (`monitor.py`) — log named agent actions and read back
  surprise / novelty / anomaly. Works around core's ingestion filters:
  per-action room registration for distinct tokens (SPEC §3), on/off state
  alternation to defeat per-entity last-token dedup (SPEC §1), and a monotonic
  virtual clock spaced above the reticular burst gate (SPEC §5.5).
- **Scoring layer** (`scoring.py`) — a robust verdict where core's raw flag is
  jittery on short runs: `NoveltyStrategy`, `AdaptiveThresholdStrategy`
  (per-stream `median + k·MAD` with a `min_spread` floor and a warmup aligned to
  core's ~100-event cold-start boundary), `CompositeStrategy` (OR/AND), and
  `AnomalyScorer` with cross-stream aggregate stats.
- **Anomaly history** (`history.py`) — a persisted, queryable ledger
  (`recent`, `for_action`, `summary`) answering *"what was odd this week?"*.
- **Alerting & routing** (`alerting.py`) — `LogSink`, `WebhookSink`
  (generic / Slack / Discord), `CallbackSink` (feed back into openclaw), and
  `AlertRouter` with per-action rate-limiting.
- **Dashboard** (`dashboard.py`) — `render_dashboard()` produces a single
  self-contained HTML view of recent anomalies (no external assets, no JS).
- **`AnomalyWatch`** (`watch.py`) — orchestrator wiring monitor → scorer →
  history → alerts behind one `observe()` call.
- **Diagnostics** — `AgentMonitor.diagnostics()` passes through
  `engine.get_diagnostics()` under an `hasattr` guard, degrading gracefully on
  cores that predate it (SPEC §5.1).
- Tests for registration/dedup, novelty, persistence roundtrips, `context()`
  shape, diagnostics degradation, every scoring strategy, history/alerting, the
  dashboard, and the SPEC §4 acceptance criterion.
- `docs/USAGE.md` with a minimal openclaw example.

### Polish

- `CompositeStrategy` now dedupes shared reasons, so a novel action reports
  `never-seen action` once instead of once per strategy.
- `AnomalyHistory` gained an `autosave` flag (default on); turn it off for
  high-volume streams to skip the O(n) rewrite per anomaly and persist via
  `save()` / `AnomalyWatch.save()`.
- Ships `py.typed` — the package is distributed as typed.

### Notes

- Licensed **AGPL-3.0**, deliberately, because core is AGPL-3.0 and this package
  imports it (SPEC §5.2). Not legal advice.
- Depends on `kontinuum-core>=0.6.0`.
