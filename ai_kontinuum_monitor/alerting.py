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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

from .history import AnomalyRecord

logger = logging.getLogger("ai_kontinuum_monitor.alerting")


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        f"[{kind}] agent={rec.agent_id} action={rec.action!r} "
        f"score={rec.score:.2f} surprise={rec.surprise:.2f} "
        f"({reason}) @ {rec.ts}"
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
    """Fan a flagged anomaly out to every sink, with per-action rate-limiting.

    Args:
        sinks: Sinks to deliver to.
        cooldown_seconds: Minimum gap between alerts for the *same* action; a
            repeat inside the window is suppressed. ``0`` disables rate-limiting.
    """

    def __init__(self, sinks: Optional[List[AlertSink]] = None, cooldown_seconds: float = 0.0):
        self.sinks: List[AlertSink] = list(sinks or [])
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: Dict[str, datetime] = {}
        self.suppressed = 0

    def add_sink(self, sink: AlertSink) -> None:
        self.sinks.append(sink)

    def _rate_limited(self, action: str, now: datetime) -> bool:
        if self.cooldown_seconds <= 0:
            return False
        last = self._last_sent.get(action)
        return last is not None and (now - last) < timedelta(
            seconds=self.cooldown_seconds
        )

    def route(self, rec: AnomalyRecord, *, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Deliver ``rec`` to all sinks. Returns a per-sink delivery report."""
        now = now or _now()
        if self._rate_limited(rec.action, now):
            self.suppressed += 1
            return {"delivered": False, "reason": "rate_limited", "sinks": {}}
        self._last_sent[rec.action] = now
        results = {sink.name: sink.deliver(rec) for sink in self.sinks}
        return {"delivered": True, "sinks": results}
