"""Alerting & routing — get an anomaly *out* of the process.

Core has no notion of notifying anyone. This module routes a flagged anomaly to
one or more sinks — a log line, a webhook (Slack/Discord/generic JSON), or a
Python callback to feed the verdict back into openclaw — with per-action
rate-limiting so a flapping stream can't spam. Third reason the package earns
its own existence.

The stdlib is the only hard dependency; the webhook sink uses ``urllib``.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from ._timeutil import as_utc, now_utc
from .history import AnomalyRecord

logger = logging.getLogger("kontinuum_ai_anomaly.alerting")

_now = now_utc  # backwards-compatible alias


# Escalation levels, ordered least → most severe. A record's level is derived
# from its severity ``score`` (0-1) via :func:`escalation_level`; sinks can
# subscribe to a minimum level so a noisy log sink and a page-the-human sink can
# share one router.
LEVELS: List[str] = ["info", "warning", "critical"]
_LEVEL_INDEX: Dict[str, int] = {name: i for i, name in enumerate(LEVELS)}

# Default score cut-points. A novel action (no learned baseline) always lands at
# least at ``warning`` regardless of its raw score.
DEFAULT_LEVEL_THRESHOLDS: Dict[str, float] = {"warning": 0.4, "critical": 0.75}


def escalation_level(
    rec: AnomalyRecord,
    thresholds: Optional[Dict[str, float]] = None,
) -> str:
    """Map an anomaly's severity ``score`` to an escalation level.

    ``score >= critical`` → ``"critical"``; ``>= warning`` → ``"warning"``;
    otherwise ``"info"``. A novel action is floored to ``"warning"`` because a
    never-seen action is always worth a human's attention even when its raw
    score is modest.
    """
    th = thresholds or DEFAULT_LEVEL_THRESHOLDS
    if rec.score >= th.get("critical", 0.75):
        return "critical"
    if rec.is_novel or rec.score >= th.get("warning", 0.4):
        return "warning"
    return "info"


class AlertSink(Protocol):
    """A sink delivers one anomaly somewhere. Must not raise on delivery
    failure — return ``False`` instead so routing to other sinks continues."""

    name: str

    def deliver(self, rec: AnomalyRecord) -> bool: ...


def format_alert(rec: AnomalyRecord) -> str:
    """Human-readable one-liner for an anomaly."""
    kind = "NOVEL" if rec.is_novel else "ANOMALY"
    reason = "; ".join(rec.reasons) or "flagged"
    return (
        f"[{escalation_level(rec).upper()}][{kind}] agent={rec.agent_id} "
        f"action={rec.action!r} score={rec.score:.2f} "
        f"surprise={rec.surprise:.2f} ({reason}) @ {rec.ts}"
    )


class LogSink:
    """Emit alerts to the Python logging system."""

    name = "log"

    def __init__(self, level: int = logging.WARNING):
        self.level = level

    def deliver(self, rec: AnomalyRecord) -> bool:
        logger.log(self.level, format_alert(rec))
        return True


class CallbackSink:
    """Feed the anomaly back into caller code (e.g. report to openclaw).

    ``callback`` receives the :class:`AnomalyRecord`. Any exception it raises is
    swallowed and logged so one bad handler can't break routing.
    """

    name = "callback"

    def __init__(self, callback: Callable[[AnomalyRecord], Any]):
        self.callback = callback

    def deliver(self, rec: AnomalyRecord) -> bool:
        try:
            self.callback(rec)
            return True
        except Exception:  # noqa: BLE001 — a sink must never break routing
            logger.exception("CallbackSink handler raised")
            return False


class WebhookSink:
    """POST a JSON payload to a webhook URL (Slack/Discord/generic).

    Args:
        url: Target URL.
        template: ``"generic"`` sends the full record as JSON; ``"slack"`` /
            ``"discord"`` send a ``{"text"/"content": <one-liner>}`` body those
            services render.
        timeout: Per-request timeout in seconds.
    """

    name = "webhook"

    def __init__(self, url: str, template: str = "generic", timeout: float = 5.0):
        if template not in ("generic", "slack", "discord"):
            raise ValueError("template must be 'generic', 'slack' or 'discord'")
        self.url = url
        self.template = template
        self.timeout = timeout

    def _payload(self, rec: AnomalyRecord) -> Dict[str, Any]:
        if self.template == "slack":
            return {"text": format_alert(rec)}
        if self.template == "discord":
            return {"content": format_alert(rec)}
        return {
            "type": "anomaly",
            "agent_id": rec.agent_id,
            "action": rec.action,
            "score": rec.score,
            "surprise": rec.surprise,
            "is_novel": rec.is_novel,
            "reasons": rec.reasons,
            "ts": rec.ts,
        }

    def deliver(self, rec: AnomalyRecord) -> bool:
        data = json.dumps(self._payload(rec)).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, OSError) as err:
            logger.warning("WebhookSink delivery failed: %s", err)
            return False


class AlertRouter:
    """Fan a flagged anomaly out to every sink, with rate-limiting, per-sink
    escalation levels, and snooze.

    Args:
        sinks: Sinks to deliver to. Each may be a bare sink (receives every
            level) or a ``(sink, min_level)`` pair — that sink then only fires
            for anomalies at or above ``min_level`` (one of :data:`LEVELS`), so a
            chatty ``LogSink`` and a page-someone ``WebhookSink`` can share a
            router.
        cooldown_seconds: Minimum gap between alerts for the *same* action; a
            repeat inside the window is suppressed. ``0`` disables rate-limiting.
        level_thresholds: Score cut-points passed to :func:`escalation_level`.
    """

    def __init__(
        self,
        sinks: Optional[List[Any]] = None,
        cooldown_seconds: float = 0.0,
        *,
        level_thresholds: Optional[Dict[str, float]] = None,
    ):
        # Sinks and their minimum levels are held as parallel entries rather than
        # keyed by ``id(sink)``: identity keying silently collapsed the same sink
        # instance registered twice at two different levels.
        self._entries: List[Tuple[AlertSink, str]] = []
        self.cooldown_seconds = cooldown_seconds
        self.level_thresholds = level_thresholds or DEFAULT_LEVEL_THRESHOLDS
        self._last_sent: Dict[str, datetime] = {}
        self._snoozed: Dict[str, datetime] = {}
        self.suppressed = 0
        for entry in sinks or []:
            if isinstance(entry, tuple):
                self.add_sink(entry[0], min_level=entry[1])
            else:
                self.add_sink(entry)

    @property
    def sinks(self) -> List[AlertSink]:
        """The registered sinks, in registration order.

        A fresh list each time — register through :meth:`add_sink` so the sink's
        minimum level is recorded alongside it.
        """
        return [sink for sink, _level in self._entries]

    def add_sink(self, sink: AlertSink, *, min_level: str = "info") -> None:
        if min_level not in _LEVEL_INDEX:
            raise ValueError(f"min_level must be one of {LEVELS}")
        self._entries.append((sink, min_level))

    # ------------------------------------------------------------------
    # Snooze
    # ------------------------------------------------------------------
    def snooze(self, action: str, seconds: float, *, now: Optional[datetime] = None) -> None:
        """Mute alerts for ``action`` until ``seconds`` from ``now``.

        Snoozing suppresses routing for that action's alerts until the window
        expires (an on-call human silencing a known-flapping stream). Distinct
        from ``cooldown_seconds``, which is automatic per-action rate-limiting.
        """
        base = as_utc(now) if now is not None else _now()
        self._snoozed[action] = base + timedelta(seconds=seconds)

    def unsnooze(self, action: str) -> None:
        self._snoozed.pop(action, None)

    def _is_snoozed(self, action: str, now: datetime) -> bool:
        until = self._snoozed.get(action)
        if until is None:
            return False
        if now >= until:
            del self._snoozed[action]
            return False
        return True

    def _rate_limited(self, action: str, now: datetime) -> bool:
        if self.cooldown_seconds <= 0:
            return False
        last = self._last_sent.get(action)
        return last is not None and (now - last) < timedelta(
            seconds=self.cooldown_seconds
        )

    def route(self, rec: AnomalyRecord, *, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Deliver ``rec`` to eligible sinks. Returns a per-sink delivery report."""
        now = as_utc(now) if now is not None else _now()
        level = escalation_level(rec, self.level_thresholds)
        if self._is_snoozed(rec.action, now):
            self.suppressed += 1
            return {"delivered": False, "reason": "snoozed", "level": level, "sinks": {}}
        if self._rate_limited(rec.action, now):
            self.suppressed += 1
            return {"delivered": False, "reason": "rate_limited", "level": level, "sinks": {}}
        rank = _LEVEL_INDEX[level]
        results: Dict[str, bool] = {}
        for sink, min_level in self._entries:
            if rank < _LEVEL_INDEX[min_level]:
                continue
            results[sink.name] = sink.deliver(rec)
        if not results:
            # Nothing went out, so nothing may start the cooldown clock. Arming
            # it here used to swallow the *next* alert for this action: a
            # below-threshold info event would rate-limit a genuine critical one
            # arriving inside the window, even though no sink had ever fired.
            return {"delivered": False, "reason": "below_sink_levels", "level": level, "sinks": {}}
        self._last_sent[rec.action] = now
        return {"delivered": True, "level": level, "sinks": results}
