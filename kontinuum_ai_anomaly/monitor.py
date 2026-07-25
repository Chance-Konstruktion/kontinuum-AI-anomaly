"""AgentMonitor — a thin, additive layer that turns kontinuum-core into an
anomaly / novelty monitor over an *agent action stream* (e.g. an openclaw bot).

Core is used unchanged. This module only hides the token-granularity mechanics
of the engine so a caller can just log named actions and read back a verdict.

Honest limitations (SPEC.md §2):

* The reliable signal is **novelty detection** — a never-seen action produces
  high surprise and trips the anomaly flag on its first occurrence.
* **Sequence / order anomalies are weak on short runs.** The engine stays in
  ``cold_start`` under 100 events and the raw per-event ``anomaly`` flag from
  core is jittery below a few hundred events, so it should be treated as an
  advisory signal, not ground truth. The :mod:`kontinuum_ai_anomaly.scoring`
  layer exists to turn that jittery raw signal into a robust verdict.
* This is an **observer, not training** — it never changes the agent's own LLM.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from kontinuum_core import (
    KontinuumEngine,
    build_llm_context,
    render_llm_context,
)

from ._timeutil import as_utc

# Default spacing on the virtual clock. Kept well above the reticular burst
# gate's window (SPEC.md §5.5) so replayed / synthetic streams are never
# silently burst-filtered and mistaken for silent ingestion drops.
DEFAULT_STEP_SECONDS = 100

# Core's circadian curve is a cosine peaking at 08:00, scaled into a
# learning-rate multiplier as ``0.5 + base·0.8`` — 0.5 at 20:00 up to 1.3 at
# 08:00. Hour 13 sits at base 0.629, i.e. a multiplier of 1.004: the phase at
# which the circadian model neither boosts nor damps learning. Anchoring there
# is how :class:`AgentMonitor` opts out of the rhythm without second-guessing
# any of core's other tuning. (Hour 3 is the same point on the rising flank.)
NEUTRAL_CIRCADIAN_HOUR = 13


def slug(action: str) -> str:
    """Normalize an action name into a token-safe slug (``[a-z0-9_]``)."""
    return re.sub(r"[^a-z0-9]+", "_", str(action).lower()).strip("_") or "action"


class AgentMonitor:
    """Log named agent actions; read back surprise / novelty / anomaly.

    Args:
        persist_path: Optional path to a JSON brain file. If it exists it is
            loaded on construction; :meth:`save` writes back to it.
        agent_id: Label for this agent (surfaced in :meth:`diagnostics`).
        circadian_hour: Phase at which core's circadian learning-rate
            multiplier is held. Defaults to :data:`NEUTRAL_CIRCADIAN_HOUR`
            (multiplier 1.0), so the time of day never moves the verdict — an
            agent action stream has no day/night rhythm. Pass ``None`` to let
            core follow the local wall clock as it does by default, which makes
            results depend on when the process runs.

    Each action is given its **own room** (SPEC.md §3) via
    ``register_entity(f"switch.{slug}", ha_area=slug, domain="switch")``, which
    yields the distinct token ``{action}.switch.on|off`` over the stable public
    API — no custom-profile wiring required.
    """

    def __init__(
        self,
        persist_path: Optional[str] = None,
        agent_id: str = "agent",
        *,
        step_seconds: float = DEFAULT_STEP_SECONDS,
        circadian_hour: Optional[int] = NEUTRAL_CIRCADIAN_HOUR,
    ):
        self.persist_path = persist_path
        self.agent_id = agent_id
        # Fixed phase for core's circadian learning-rate multiplier; ``None``
        # restores core's own wall-clock behaviour. See
        # :meth:`_pin_circadian_phase`.
        self.circadian_hour = circadian_hour
        # Spacing on the virtual clock. Callers replaying genuinely
        # high-frequency streams can raise it so consecutive events aren't
        # silently burst-filtered (SPEC.md §5.5). Clamped to the burst-safe
        # default minimum so a too-small value can't reintroduce silent drops.
        self.step_seconds = max(float(step_seconds), DEFAULT_STEP_SECONDS)
        self.engine = KontinuumEngine()
        self._registered: set[str] = set()
        self._state_on: Dict[str, bool] = {}
        self._seen_actions: set[str] = set()
        # action name -> the slug (and hence core token) it owns. Kept explicit
        # because :func:`slug` is lossy: ``"deploy prod"`` and ``"deploy-prod"``
        # both normalize to ``deploy_prod``, which would silently merge two
        # distinct action streams onto one learned token. See :meth:`_slug_for`.
        self._action_slug: Dict[str, str] = {}
        # Monotonic virtual clock so events are spaced realistically even when
        # the caller never supplies a timestamp.
        self._clock = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)

        if persist_path and os.path.exists(persist_path):
            self._load(persist_path)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def _slug_for(self, action: str) -> str:
        """The unique slug owned by ``action``, allocated on first sight.

        :func:`slug` collapses everything outside ``[a-z0-9]`` to ``_``, so
        distinct action names can normalize to the same string. Sharing a slug
        means sharing a core entity — the two streams' surprise histories would
        be pooled and their on/off toggling would interleave, corrupting both.
        A taken slug therefore gets a numeric suffix, which keeps every action
        on its own token while leaving the common (collision-free) case byte-for-
        byte identical to before.
        """
        existing = self._action_slug.get(action)
        if existing is not None:
            return existing
        base = slug(action)
        candidate = base
        n = 2
        taken = set(self._action_slug.values())
        while candidate in taken:
            candidate = f"{base}_{n}"
            n += 1
        self._action_slug[action] = candidate
        return candidate

    def _pin_circadian_phase(self, ts: datetime) -> None:
        """Hold core's circadian learning-rate multiplier at a fixed phase.

        ``Neurorhythms.get_circadian_multiplier()`` falls back to the **local
        wall clock** when no hour is passed, mapping the time of day onto a
        learning-rate multiplier between 0.5 and 1.3 — a 2.6× swing decided by
        when the process happens to run — and then caches it for 60 s, so a
        single clock reading governs a whole batch of events.

        That is a home-automation concept: a household really does have a day
        and a night. An **agent action stream does not**. An agent doing the
        same work at 03:00 is not doing it more sluggishly, so letting the hour
        move the learning rate only adds noise — and made verdicts depend on
        when you ran the process. This package's own quality-gate test passed
        only between 20:00 and 22:59 UTC because of it.

        Anchoring the phase to the *event's* hour instead would be deterministic
        but is worse in practice: the multiplier then drifts across a replay
        that spans hours, and the drifting learning rate produced *more* false
        alarms on a perfectly stable rhythm than any fixed phase did. So the
        monitor pins one neutral phase (:data:`NEUTRAL_CIRCADIAN_HOUR`, where
        the multiplier is 1.0) and opts out of the rhythm altogether. Pass
        ``circadian_hour`` to :class:`AgentMonitor` to choose a different phase,
        or ``None`` to restore core's own wall-clock behaviour.

        Guarded with ``getattr`` like :meth:`diagnostics`, since this reaches
        past the stable public API (SPEC.md §5.1): on a core build without the
        hook, behaviour is simply left as-is.
        """
        if self.circadian_hour is None:
            return
        rhythms = getattr(self.engine, "neurorhythms", None)
        pin = getattr(rhythms, "get_circadian_multiplier", None)
        if pin is None:
            return
        try:
            # Passing `hour` bypasses both the wall-clock fallback and the 60 s
            # cache, so the phase is re-pinned before every ingest.
            pin(hour=self.circadian_hour)
        except TypeError:
            # Older signature without the `hour` parameter: leave core alone.
            pass

    def observe(
        self,
        action: str,
        detail: Optional[str] = None,
        *,
        ts: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Log ONE agent action and return the engine's read on it.

        Returns a dict with ``action``, ``surprise`` (0-1), ``anomaly`` (raw
        core flag — advisory, see the module docstring), ``threshold``,
        ``is_novel`` (True the first time this action is seen) and
        ``learning_state``.

        ``detail`` is accepted for caller ergonomics / logging symmetry; it does
        not change the learned token (the token granularity is the action).
        """
        s = self._slug_for(action)

        # 1) Auto-register each action with its own room so every action gets a
        #    distinct token and is never dropped as unregistered (SPEC.md §5.3).
        if s not in self._registered:
            self.engine.register_entity(f"switch.{s}", ha_area=s, domain="switch")
            self._registered.add(s)

        # 2) Alternate the on/off state per call for the SAME action so that two
        #    consecutive repeats are not lost to core's last-token dedup, which
        #    is keyed per entity (SPEC.md §1).
        new_on = not self._state_on.get(s, False)
        self._state_on[s] = new_on
        new_state = "on" if new_on else "off"
        old_state = "off" if new_on else "on"

        # 3) Realistic timestamp on the virtual clock unless the caller gave one.
        if ts is None:
            self._clock += timedelta(seconds=self.step_seconds)
            ts = self._clock
        else:
            # A caller-supplied timestamp is normalized to UTC first: the virtual
            # clock is UTC-aware, and the most natural call there is —
            # ``observe(action, ts=datetime.now())`` — hands in a *naive*
            # datetime, which used to make this comparison raise TypeError.
            ts = as_utc(ts)
            # Keep the virtual clock monotonically ahead of any supplied ts so a
            # later default-timestamped call never lands "before" this one.
            if ts > self._clock:
                self._clock = ts

        # 4) Pin core's circadian phase to this event's hour, so the verdict is
        #    decided by when the action happened rather than by when this
        #    process happens to be running.
        self._pin_circadian_phase(ts)

        snap = self.engine.observe(
            {
                "entity_id": f"switch.{s}",
                "new_state": new_state,
                "old_state": old_state,
                "timestamp": ts,
            }
        )

        is_novel = action not in self._seen_actions
        self._seen_actions.add(action)

        return {
            "action": action,
            "surprise": round(float(snap.surprise), 4),
            "anomaly": bool(snap.anomaly),
            "threshold": round(float(snap.extra.get("anomaly_threshold", 0.0)), 4),
            "is_novel": is_novel,
            "learning_state": snap.learning_state,
        }

    # ------------------------------------------------------------------
    # Reflection / diagnostics
    # ------------------------------------------------------------------
    def context(self) -> str:
        """Rendered LLM context so the agent's own model can reflect on state."""
        return render_llm_context(build_llm_context(self.engine))

    def diagnostics(self) -> Dict[str, Any]:
        """Registration / ingestion health, guarded for older cores.

        ``get_diagnostics()`` (core PR #35) is absent on some published builds
        (SPEC.md §5.1), so the call is ``hasattr``-guarded; on an older core
        this returns a clear ``{"available": False, ...}`` marker instead of
        raising.
        """
        if not hasattr(self.engine, "get_diagnostics"):
            return {
                "available": False,
                "reason": "kontinuum-core build has no get_diagnostics()",
                "agent_id": self.agent_id,
            }
        diag = dict(self.engine.get_diagnostics())
        diag["available"] = True
        diag["agent_id"] = self.agent_id
        diag["actions_seen"] = len(self._seen_actions)
        return diag

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self) -> None:
        """Persist the brain to ``persist_path``; no-op if none was given."""
        if not self.persist_path:
            return
        payload = {
            "agent_id": self.agent_id,
            "engine": self.engine.to_dict(),
            "monitor": {
                "registered": sorted(self._registered),
                "state_on": self._state_on,
                "seen_actions": sorted(self._seen_actions),
                # Persisted so a reloaded brain keeps every action pointing at
                # the same core token it was learned under.
                "action_slug": dict(self._action_slug),
                "clock": self._clock.isoformat(),
            },
        }
        tmp = f"{self.persist_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, self.persist_path)

    def _load(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self.agent_id = payload.get("agent_id", self.agent_id)
        self.engine.from_dict(payload.get("engine", {}))
        mon = payload.get("monitor", {})
        self._registered = set(mon.get("registered", []))
        self._state_on = dict(mon.get("state_on", {}))
        self._seen_actions = set(mon.get("seen_actions", []))
        # Older brain files predate the explicit map; rebuilding it from the
        # seen actions reproduces exactly what those files assumed.
        stored_slugs = mon.get("action_slug")
        if stored_slugs:
            self._action_slug = dict(stored_slugs)
        else:
            self._action_slug = {}
            for action in sorted(self._seen_actions):
                self._slug_for(action)
        clock = mon.get("clock")
        if clock:
            try:
                self._clock = as_utc(datetime.fromisoformat(clock))
            except ValueError:
                pass
