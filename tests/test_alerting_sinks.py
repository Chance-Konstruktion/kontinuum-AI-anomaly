"""Tests for the alert sinks — `WebhookSink` in particular.

`WebhookSink` is the only sink that leaves the process, so a bug in it reaches
Slack/Discord in production and fails quietly (its contract is to return `False`
rather than raise). It had no test coverage at all; this file covers the
constructor guard, all three payload templates, and both delivery outcomes,
without touching the network.
"""
from datetime import datetime, timezone

import pytest

from kontinuum_ai_anomaly import (
    AlertRouter,
    AnomalyRecord,
    CallbackSink,
    LogSink,
    WebhookSink,
    format_alert,
)

AWARE = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def _record(action="escalate", *, score=0.9, is_novel=True):
    return AnomalyRecord(
        action=action,
        score=score,
        surprise=score,
        threshold=0.5,
        is_novel=is_novel,
        reasons=["never-seen action"],
        strategy="test",
        ts=AWARE.isoformat(),
        agent_id="agent-7",
    )


class _FakeResponse:
    """Stands in for the object `urllib.request.urlopen` yields."""

    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ----------------------------------------------------------------------
# Constructor
# ----------------------------------------------------------------------
def test_unknown_template_is_rejected():
    with pytest.raises(ValueError, match="template must be"):
        WebhookSink("https://example.invalid/hook", template="teams")


@pytest.mark.parametrize("template", ["generic", "slack", "discord"])
def test_supported_templates_are_accepted(template):
    assert WebhookSink("https://example.invalid/hook", template=template).template == template


# ----------------------------------------------------------------------
# Payload shapes — these are what the receiving service actually renders.
# ----------------------------------------------------------------------
def test_slack_payload_uses_text_key():
    sink = WebhookSink("https://example.invalid/hook", template="slack")
    rec = _record()
    assert sink._payload(rec) == {"text": format_alert(rec)}


def test_discord_payload_uses_content_key():
    sink = WebhookSink("https://example.invalid/hook", template="discord")
    rec = _record()
    assert sink._payload(rec) == {"content": format_alert(rec)}


def test_generic_payload_carries_the_record_fields():
    sink = WebhookSink("https://example.invalid/hook")
    payload = sink._payload(_record())
    assert payload["type"] == "anomaly"
    assert payload["agent_id"] == "agent-7"
    assert payload["action"] == "escalate"
    assert payload["is_novel"] is True
    assert payload["reasons"] == ["never-seen action"]
    assert payload["ts"] == AWARE.isoformat()


def test_generic_payload_is_json_serializable():
    import json

    json.loads(json.dumps(WebhookSink("https://example.invalid/h")._payload(_record())))


# ----------------------------------------------------------------------
# Delivery
# ----------------------------------------------------------------------
def test_deliver_posts_json_and_reports_success(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = req.data
        seen["headers"] = req.headers
        seen["timeout"] = timeout
        return _FakeResponse(200)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sink = WebhookSink("https://example.invalid/hook", timeout=2.5)
    assert sink.deliver(_record()) is True
    assert seen["url"] == "https://example.invalid/hook"
    assert seen["timeout"] == 2.5
    # urllib title-cases header names.
    assert seen["headers"]["Content-type"] == "application/json"
    import json

    assert json.loads(seen["body"].decode())["action"] == "escalate"


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_2xx_counts_as_delivered(monkeypatch, status):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=None: _FakeResponse(status)
    )
    assert WebhookSink("https://example.invalid/h").deliver(_record()) is True


@pytest.mark.parametrize("status", [301, 400, 404, 500])
def test_non_2xx_counts_as_not_delivered(monkeypatch, status):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=None: _FakeResponse(status)
    )
    assert WebhookSink("https://example.invalid/h").deliver(_record()) is False


@pytest.mark.parametrize(
    "err",
    [
        __import__("urllib.error", fromlist=["URLError"]).URLError("unreachable"),
        OSError("connection reset"),
        TimeoutError("timed out"),
    ],
)
def test_network_failure_returns_false_instead_of_raising(monkeypatch, err):
    def boom(req, timeout=None):
        raise err

    monkeypatch.setattr("urllib.request.urlopen", boom)
    # The sink contract: never raise, so routing to other sinks continues.
    assert WebhookSink("https://example.invalid/h").deliver(_record()) is False


def test_a_failing_webhook_does_not_stop_other_sinks(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("down")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    delivered = []
    router = AlertRouter(
        [WebhookSink("https://example.invalid/h"), CallbackSink(delivered.append)]
    )
    report = router.route(_record(), now=AWARE)
    assert report["sinks"]["webhook"] is False
    assert report["sinks"]["callback"] is True
    assert len(delivered) == 1


# ----------------------------------------------------------------------
# Router surface that had no coverage
# ----------------------------------------------------------------------
def test_add_sink_rejects_an_unknown_level():
    router = AlertRouter()
    with pytest.raises(ValueError, match="min_level must be one of"):
        router.add_sink(LogSink(), min_level="urgent")


def test_unsnooze_reenables_delivery():
    delivered = []
    router = AlertRouter([CallbackSink(delivered.append)])
    router.snooze("escalate", 3600, now=AWARE)
    assert router.route(_record(), now=AWARE)["reason"] == "snoozed"
    router.unsnooze("escalate")
    assert router.route(_record(), now=AWARE)["delivered"] is True
    assert len(delivered) == 1


def test_unsnooze_of_an_unknown_action_is_a_noop():
    AlertRouter().unsnooze("never-snoozed")  # must not raise


def test_snooze_expires_on_its_own():
    from datetime import timedelta

    delivered = []
    router = AlertRouter([CallbackSink(delivered.append)])
    router.snooze("escalate", 60, now=AWARE)
    assert router.route(_record(), now=AWARE + timedelta(seconds=30))["reason"] == "snoozed"
    assert router.route(_record(), now=AWARE + timedelta(seconds=61))["delivered"] is True


def test_log_sink_delivers():
    assert LogSink().deliver(_record()) is True
