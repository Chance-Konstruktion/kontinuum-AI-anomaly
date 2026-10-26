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
import math
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import urlsplit
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
        except Exception:  # a sink must never break routing
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
        try:
            parsed = urlsplit(url)
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError("port is outside the valid range")
        except (TypeError, ValueError):
            raise ValueError("url must be an absolute http(s) URL with a host") from None
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise ValueError("url must be an absolute http(s) URL with a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("webhook URL must not embed credentials")
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError):
            raise ValueError("timeout must be a positive finite number") from None
        if not math.isfinite(timeout_value) or timeout_value <= 0:
            raise ValueError("timeout must be a positive finite number")
        self.url = url
        self.template = template
        self.timeout = timeout_value

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
            "threshold": rec.threshold,
            "is_novel": rec.is_novel,
            "reasons": rec.reasons,
            "strategy": rec.strategy,
            "ts": rec.ts,
            "detail": rec.detail,
        }

    def deliver(self, rec: AnomalyRecord) -> bool:
        data = json.dumps(self._payload(rec)).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, OSError, ValueError) as err:
            # Invalid endpoint/request construction is a failed delivery too;
            # it must not escape the sink contract and block other sinks.
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
        cooldown_seconds: Minimum gap per action, severity and successful sink.
            Failed deliveries remain retryable; a more severe escalation is not
            suppressed by a lower-level cooldown. Zero disables rate-limiting.
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
        # Cool down successful repeats per action, severity and sink. A warning
        # must not suppress a critical escalation, and a failed pager must remain
        # retryable even if a log sink succeeded for the same event.
        self._last_sent: Dict[Tuple[str, str, int], datetime] = {}
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

    def _rate_limited(
        self, action: str, level: str, sink: AlertSink, now: datetime
    ) -> bool:
        if self.cooldown_seconds <= 0:
            return False
        last = self._last_sent.get((action, level, id(sink)))
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
        rank = _LEVEL_INDEX[level]
        results: Dict[str, bool] = {}
        seen_sinks: set[int] = set()
        eligible = 0
        rate_limited = 0
        for sink, min_level in self._entries:
            if rank < _LEVEL_INDEX[min_level] or id(sink) in seen_sinks:
                continue
            # Registering one sink at multiple minimum levels expresses
            # multiple eligibility rules, not a request to deliver duplicates.
            seen_sinks.add(id(sink))
            key = sink.name
            if key in results:
                suffix = 2
                while f"{key}#{suffix}" in results:
                    suffix += 1
                key = f"{key}#{suffix}"
            eligible += 1
            if self._rate_limited(rec.action, level, sink, now):
                results[key] = False
                rate_limited += 1
                continue
            try:
                delivered_to_sink = bool(sink.deliver(rec))
            except Exception:
                # A plugin-provided sink must not prevent other sinks from
                # receiving a safety-relevant alert.
                logger.exception("Alert sink %s raised during delivery", sink.name)
                delivered_to_sink = False
            results[key] = delivered_to_sink
            if delivered_to_sink:
                self._last_sent[(rec.action, level, id(sink))] = now
        if not results:
            return {"delivered": False, "reason": "below_sink_levels", "level": level, "sinks": {}}
        delivered = any(results.values())
        if not delivered:
            if rate_limited == eligible:
                self.suppressed += 1
                return {
                    "delivered": False,
                    "reason": "rate_limited",
                    "level": level,
                    "sinks": results,
                }
            # Delivery failures do not arm a cooldown; only successfully
            # delivered (action, level, sink) tuples are rate-limited.
            return {
                "delivered": False,
                "reason": "delivery_failed",
                "level": level,
                "sinks": results,
            }
        return {"delivered": True, "level": level, "sinks": results}
