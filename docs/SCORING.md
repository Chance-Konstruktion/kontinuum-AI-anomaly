# How the scoring decides

`kontinuum-core` gives you a per-event `surprise` (0–1) and a raw `anomaly`
flag. On short runs that raw flag is jittery — it fires and un-fires as the
engine's global baseline wobbles. This package's scoring layer sits *on top* and
turns that signal into a **stable verdict**. This document explains the decision
path so you can trust — or tune — the result.

The guiding principle is **novelty-first**: the one thing we can say confidently
at any run length is "this action has never been seen before." Everything else
is layered on as evidence accumulates.

---

## The verdict pipeline

Each `observe()` produces an observation dict; the strategy turns it into an
`AnomalyScore`. The default (`default_strategy()`) is:

```
NoveltyStrategy  OR  AdaptiveThresholdStrategy
```

`sequence_aware_strategy()` adds `SequenceStrategy` as a third OR term. OR is the
right default for anomaly detection: any strategy raising a flag is enough, and
the combined `score` is the max of the components.

---

## 1. Novelty — the reliable signal

`NoveltyStrategy` flags the **first occurrence** of any action. A never-seen
action has no learned expectation, so its surprise is high by construction and
its severity `score` is that raw surprise. This is run-length-independent: it is
just as reliable on event 3 as on event 30 000.

This is the signal to trust. If you only take one thing from the scorer, take
novelty.

---

## 2. Adaptive threshold — for *known* actions

Once an action has a history, "is this occurrence weirdly surprising *for this
action*?" becomes answerable. `AdaptiveThresholdStrategy` keeps a rolling window
of each action's surprise values and flags when the current surprise exceeds:

```
threshold = median + max(min_spread, k · 1.4826 · MAD)
```

- **Per-stream, not global.** A chatty benign action can't raise the bar for a
  rare critical one — each action is judged against its *own* normal.
- **Robust.** Median + MAD (the same estimator core uses globally) shrugs off
  outliers that would drag a mean/stdev around.
- **`min_spread` floor.** A very *steady* stream collapses MAD → 0, which would
  make every tiny wobble trip the flag. Requiring the threshold to sit at least
  `min_spread` (default 0.2) above the median means only a real jump counts.
- **`floor`.** An absolute surprise floor (default 0.4) so an unusually calm
  stream never alerts on noise.

### Warmup, and reacting sooner

Below `warmup` samples (default 100) the full test stays silent — thin evidence
shouldn't drive a confident verdict. But waiting for 100 samples is slow on
short runs, so an **early window** engages a *provisional* test from
`early_warmup` (default 20) samples onward, with the spread widened by
`early_k_boost` so it only trips on a clear spike. Set `early_warmup=None` to
restore the old, fully-conservative behaviour.

The current event is recorded **after** it is judged, so an event never shifts
its own baseline.

---

## 3. Sequence — right action, wrong order

Core's own order-awareness is weak on short runs, and that is a *core*
limitation. `SequenceStrategy` adds the missing signal in the monitor layer
(core untouched): a first-order (bigram) transition model that learns, for each
action, how often each *following* action occurs. Once a predecessor has been
seen `min_context` times (default 20), a transition whose learned probability is
`≤ min_prob` (default 0.02) — including a never-seen transition — is flagged.

It complements novelty: novelty catches a brand-new *action*, sequence catches a
familiar action arriving in an unfamiliar *order*.

---

## Severity, escalation, and alerting

`score` is a 0–1 severity. For a threshold flag it is how far past the bar the
surprise landed, normalized to the headroom above it; for a novel action it is
the raw surprise. `escalation_level()` maps it to `info` / `warning` /
`critical` (cut-points 0.4 / 0.75 by default), and a **novel action is always
floored to at least `warning`** — a never-seen action is worth a human's glance
even when its raw score is modest.

---

## Learning state

`metrics()` reports two related-but-distinct notions of "how learned is this?":

- **`learning_state`** — core's own label. Core actually emits *two* dialects
  depending on the build: the engine returns `cold_start` / `learning` /
  `stable`, while its LLM-context helper describes the scale as `cold_start` <
  `warming` < `mature`. We normalize both onto one canonical
  `cold_start` / `warming` / `mature` scale (`normalize_learning_state`) so a
  dashboard never shows two words for one concept. The exact string core emitted
  is preserved as `learning_state_raw`.

- **`learning_progress_pct`** — a smooth 0–100 % estimate, computed purely from
  **event volume** (`observations / MATURE_EVENTS`, anchored to core's 1000-event
  `stable` gate).

These two can legitimately disagree. Progress is volume-only; core's state also
weighs prediction *accuracy*. A stream that has seen plenty of events but whose
predictions haven't converged can read **100 % progress while still `warming`**.
That is a true signal — "enough data, not yet accurate" — not a bookkeeping
error. Read them together: progress answers "how much has it seen?", state
answers "how well does it predict?".

---

## Tuning cheat-sheet

| Want | Knob |
|---|---|
| Fewer false positives on known actions | raise `k`, raise `floor` |
| React before 100 samples | lower `early_warmup` (or `warmup`) |
| Catch rarer order violations | lower `SequenceStrategy.min_prob` |
| Only ever flag brand-new actions | use the `novelty_only` preset |
| More aggressive on short/noisy streams | use the `sensitive` preset |

Presets live in `builtin_presets()`; export/import your own with
`save_preset` / `load_preset`.
