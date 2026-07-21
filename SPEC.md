# ai-kontinuum-monitor — Build Spec

Adapter that uses **kontinuum-core** as an anomaly / novelty monitor over an
**agent action stream** (e.g. an openclaw bot), instead of a smart-home event
stream. Core stays untouched; this repo is a thin, additive layer on top.

---

## 0. Before writing anything — verify against the real code

Do **not** build from these notes alone; read the installed `kontinuum-core`
source first and confirm APIs, since the published version may differ from what
is described here.

- `engine.py` — `KontinuumEngine.observe()`, `register_entity()`, and the
  `EngineSnapshot` fields (`surprise`, `anomaly`, `learning_state`,
  `tick_count`, `predictions`). Also check whether `get_diagnostics()` exists
  in the version actually resolved (see §5.1).
- `thalamus.py` — `process()` and `register_entity()`. Two hard filters that
  silently drop input (both `return None`):
  1. the entity must be **registered** first, and
  2. it must have a **resolvable room**.
  The learned token is `room.semantic.state` (**not** per-entity), and an
  identical token twice in a row is **deduplicated** (`entity_last_token`).
- `llm.py` — `build_llm_context()`, `render_llm_context()`,
  `normalize_proposal()`.

---

## 1. What to build

A module `ai_kontinuum_monitor/monitor.py` exposing an `AgentMonitor` class that
hides the token-granularity mechanics so callers just log named actions.

```
AgentMonitor(persist_path: str | None = None, agent_id: str = "agent")
```
Loads or creates a `KontinuumEngine`; uses `to_dict()` / `from_dict()` for
persistence.

```
observe(action: str, detail: str | None = None, *, ts=None) -> dict
```
Logs ONE agent action and returns:
`{action, surprise, anomaly, threshold, is_novel, learning_state}`.
Internally it must work around the engine filters:
- auto-register each action (**separate room per action** — see §3) so every
  action gets a distinct token,
- **alternate the on/off state per call** for the same action so consecutive
  repeats of the same action are not lost to last-token dedup,
- pass a realistic `ts` (see §5.5) — default to a monotonic virtual clock with
  sane spacing if the caller gives none.

```
context() -> str
```
Returns `render_llm_context(build_llm_context(engine))` so the agent's own LLM
can reflect on its state.

```
diagnostics() -> dict
```
Passes through `engine.get_diagnostics()` **guarded by `hasattr`** (see §5.1);
returns `{}` (or a clear "unavailable" marker) on older cores.

```
save() -> None
```
Persists to `persist_path`; no-op if none was given.

---

## 2. Honest limitations — put these in the docstring and docs

- The reliable signal is **novelty detection**: a never-seen action produces
  high surprise and trips the anomaly flag.
- **Sequence / order anomalies are weak** on short runs. The engine needs many
  events and stays in `cold_start` under 100 events (see §5.4).
- This is an **observer, not training** — it does not change the agent's LLM.

---

## 3. Token distinctness — use the per-room path

To give each action its own token, register it with its own room:
`register_entity(f"switch.{slug(action)}", ha_area=slug(action), domain="switch")`,
which yields the token `{action}.switch.on|off`. This uses **stable public
API**. The alternative — `custom_semantic_rules` — has **no clean public
setter**; it is only loaded via `load_custom_profiles(path)` from a JSON file
with a `"semantic_rules"` key. Prefer per-room unless there is a strong reason
to wire up custom profiles.

---

## 4. Acceptance criterion

A minimal script that feeds the rhythm `plan → act → observe → reflect → done`
about 20 times, then injects a never-seen action `escalate`, must yield
`anomaly=True` for `escalate` and `anomaly=False` for the rehearsed actions.

---

## 5. Verified gotchas (checked against v0.6.0)

### 5.1 Version trap (resolved)
`get_diagnostics()` (from core PR #35) was **not** in the published PyPI
`0.6.0` — only on `main` — so an early build against PyPI `0.6.0` would not have
the function. This is now resolved: **`kontinuum-core` 0.6.2 ships
`get_diagnostics()` on PyPI**, and this repo depends on `kontinuum-core>=0.6.2`.

The diagnostics call in `AgentMonitor.diagnostics()` nonetheless stays
`hasattr`-guarded for robustness (a user could still force-install an older
core), so the monitor never hard-depends on `get_diagnostics()` and degrades to
a clear `{"available": False, ...}` marker on a core that lacks it.

### 5.2 License
Core is **AGPL-3.0** (strong copyleft, network clause). This repo imports it, so
its obligations likely propagate on distribution or when offered as a network
service. Choose this repo's license **deliberately** (most likely AGPL-3.0 too)
— do not default to a permissive license by accident. Not legal advice.

### 5.3 Silent ingestion drops
Unregistered entities and room-less entities are dropped with no signal. If
`total_events` / `hippo_events` stays flat, that is the cause. Where available,
surface `get_diagnostics()` counters (`events_dropped_unregistered`,
`events_dropped_no_room`) to debug this.

### 5.4 Learning-state thresholds
`learning_state` is `cold_start` under 100 events, `warming` under 2000, then
`mature` (verified in `llm.py::_maturity`). `cold_start` is expected on short
runs, **not** a failure. `total_events` is **not** equal to `tick_count`, so
tests should assert on thresholds / monotonic growth, not exact counts.

### 5.5 Reticular burst gate
Rapid bursts of the same entity are dropped based on **event timestamps**, not
wall clock. In tests and replays, space events realistically (e.g. 90–120 s
apart on the virtual clock) or they get burst-filtered and look like silent
drops.

---

## 6. Repo conventions

- pytest tests: registration + dedup behaviour, novelty trips the anomaly flag,
  persistence roundtrip (`save()` → reload → state intact), `context()` shape,
  and `diagnostics()` graceful-degradation on a core without `get_diagnostics()`.
- Short `docs/USAGE.md` with a minimal openclaw example.
- `CHANGELOG.md` entry.
- Additive only: no behavioural change to the core learning path.
