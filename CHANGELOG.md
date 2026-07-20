# Changelog

All notable changes to `ai-kontinuum-monitor` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/); this project adheres to
[Semantic Versioning](https://semver.org/).

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
