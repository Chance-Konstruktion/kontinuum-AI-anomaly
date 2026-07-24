"""Tests for the `recurrence` CLI subcommand.

The subcommand had no coverage: its guard clause, its JSON mode and its
human-readable report were all unexercised, so a formatting or key error would
only have surfaced in front of a user.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from kontinuum_ai_anomaly.cli import main
from kontinuum_ai_anomaly.recurrence import RecurrenceDetector

BASE = datetime(2025, 3, 1, tzinfo=timezone.utc)


def _state_with_a_finding(path):
    """A detector state that yields exactly one `new_established` finding."""
    det = RecurrenceDetector(new_within_days=7.0, established_min_count=5)
    for i in range(8):
        det.record("deploy", ts=BASE + timedelta(minutes=i))
    path.write_text(json.dumps(det.to_dict()), encoding="utf-8")
    return det


def test_missing_state_path_exits_with_a_useful_message(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["recurrence"])
    assert "--recurrence PATH" in str(exc.value)


def test_nonexistent_state_file_exits(tmp_path):
    with pytest.raises(SystemExit):
        main(["recurrence", "--recurrence", str(tmp_path / "absent.json")])


def test_empty_state_reports_no_findings(tmp_path, capsys):
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(RecurrenceDetector().to_dict()), encoding="utf-8")
    assert main(["recurrence", "--recurrence", str(path)]) == 0
    assert "No recurrence findings." in capsys.readouterr().out


def test_human_readable_report_lists_the_finding(tmp_path, capsys):
    path = tmp_path / "rec.json"
    _state_with_a_finding(path)
    assert main(["recurrence", "--recurrence", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Recurrence report — 1 finding(s)" in out
    assert "[NEW-ESTABLISHED]" in out
    assert "'deploy'" in out
    assert "[recurrence] new action established" in out


def test_json_mode_emits_parseable_findings(tmp_path, capsys):
    path = tmp_path / "rec.json"
    _state_with_a_finding(path)
    assert main(["recurrence", "--recurrence", str(path), "--json"]) == 0
    findings = json.loads(capsys.readouterr().out)
    assert len(findings) == 1
    assert findings[0]["action"] == "deploy"
    assert findings[0]["signal"] == "new_established"
    assert set(findings[0]) == {
        "action", "signal", "reason", "rate_now", "baseline", "severity", "first_seen",
    }


def test_state_round_trips_through_the_file(tmp_path):
    """What the CLI reads back must match what the detector reported in-process."""
    path = tmp_path / "rec.json"
    det = _state_with_a_finding(path)
    expected = [f.as_dict() for f in det.report()]
    reloaded = RecurrenceDetector().from_dict(json.loads(path.read_text()))
    assert [f.as_dict() for f in reloaded.report()] == expected
