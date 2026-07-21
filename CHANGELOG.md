# Changelog

All notable changes to `ai-kontinuum-monitor` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/); this project adheres to
[Semantic Versioning](https://semver.org/).

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
