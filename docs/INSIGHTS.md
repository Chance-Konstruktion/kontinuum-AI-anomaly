# Field notes: how `kontinuum-core` actually ingests events

These notes come from reverse-engineering core's ingestion path while adapting it
from a home-automation engine into an agent monitor. They are not obvious from
core's public API, and each one cost real debugging time. If you build anything
on core, read this first.

Verified against `kontinuum-core` 0.6.0–0.6.2.

---

## 1. Two silent filters drop your events

`observe()` will accept an event and then quietly learn *nothing* from it if
either condition fails — no error, no warning:

1. **The entity must be registered first** (`register_entity(...)`). An
   unregistered `entity_id` is dropped at the thalamus.
2. **The entity must resolve to a room.** If the room comes back `"unknown"`,
   the event is dropped.

Symptom: `tick_count` climbs but `hippocampus.total_events` stays at 0. If you
see that, you're feeding events that never enter the learning path.

`AgentMonitor` handles both for you (it registers each action with a room), but
if you use core directly, register with a room before you observe:

```python
engine.register_entity("switch.plan", ha_area="plan", domain="switch")
```

Since 0.6.2, `get_diagnostics()` surfaces the drop counters
(`events_dropped_unregistered`, `events_dropped_no_room`) — the fastest way to
confirm this is what's happening.

---

## 2. The learned token is `room.semantic.state`, **not** per-entity

This is the single most surprising property. Core does not learn "entity X did
Y". It learns a token composed of **room × semantic × state**. Two different
entities that share the same room and semantic collapse into the *same* token
and become indistinguishable to the learner.

Consequence for homes: two lights in the same room are one signal, not two.
Consequence for agents: if you naively map every action to `switch.<name>` in one
room, every action becomes the same token and the engine learns nothing useful.

The reliable way to give each action its own token is to give it its own **room**:

```python
register_entity(f"switch.{action}", ha_area=action, domain="switch")
# -> token "<action>.switch.on"
```

There is also a `custom_semantic_rules` path, but it has **no clean public
setter** — rules are only loaded via `load_custom_profiles(path)` from a JSON
file with a `"semantic_rules"` key. Prefer the per-room approach unless you
genuinely need custom profiles. (`AgentMonitor` uses per-room.)

---

## 3. Identical consecutive tokens are de-duplicated

The same token twice in a row is filtered (`entity_last_token`). So if your
agent does the same action twice back-to-back, the second one is dropped. The
fix `AgentMonitor` uses is to **alternate the on/off state** per call for the
same action, which yields a distinct token each time
(`<action>.switch.on` then `<action>.switch.off`).

---

## 4. The reticular gate filters bursts by event timestamp

Rapid bursts of the same entity are dropped based on the **event timestamp you
supply**, not wall-clock time. In tests and replays this bites hard: if you feed
100 events with near-identical timestamps, most get burst-filtered and you'll
think ingestion is broken. Space events realistically on a virtual clock
(90–120 s apart works well). `AgentMonitor` advances a virtual clock for you.

---

## 5. Learning-state thresholds — `cold_start` is normal

`learning_state` is a maturity label, not a health check:

- `< 100` events → `cold_start`
- `< 2000` events → `warming`
- `≥ 2000` events → `mature`

Seeing `cold_start` on a short run is expected, not a bug. Also note
`total_events` is **not** the same as `tick_count` (dropped and de-duplicated
events advance the tick but not the event count). Tests should assert on
thresholds or monotonic growth, never on exact counts.

---

## 6. Novelty is sharp; sequence order is not

Empirically, on short-to-medium runs core reliably flags a **never-seen token**
(high surprise, anomaly trips). It does **not** reliably flag an out-of-order
sequence of otherwise-known tokens — the context vector encodes time, mode, and
location, but not a strong notion of "what came directly before". This is why
this package's scoring is novelty-first, and why `SequenceStrategy` is offered
but not relied upon.

---

## 7. A GitHub release is not a PyPI release

Not a core-internals fact, but it cost this project two rounds of confusion, so
it's worth writing down. Tagging `v0.6.1` on GitHub and clicking "Publish
release" creates a git tag and a GitHub release page — it does **not** upload to
PyPI. A package appears on PyPI only when a separate `twine upload` / publish
workflow actually runs and succeeds. Verify with the authoritative source before
you assume a version is installable:

```python
import urllib.request, json
d = json.load(urllib.request.urlopen("https://pypi.org/pypi/kontinuum-core/json"))
print(d["info"]["version"], sorted(d["releases"]))
```

(0.6.1 was tagged on GitHub but never reached PyPI; 0.6.2 is the first published
build with `get_diagnostics()`. Pin `kontinuum-core >= 0.6.2` if you depend on
diagnostics.)

---

## 8. License propagation

`kontinuum-core` is AGPL-3.0. Anything that imports it inherits the copyleft and
the network-service clause. Choose your own package's license deliberately —
don't default to permissive on top of AGPL by accident.
