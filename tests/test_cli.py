"""CLI: watch/report/dashboard subcommands over real input."""
import json

import pytest

from kontinuum_ai_anomaly import cli


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_parse_line_variants():
    assert cli._parse_line("plan") == {"action": "plan", "detail": None}
    assert cli._parse_line("  # comment") is None
    assert cli._parse_line("") is None
    assert cli._parse_line("act\tdid a thing") == {"action": "act", "detail": "did a thing"}
    assert cli._parse_line('{"action": "deploy", "detail": "prod"}') == {
        "action": "deploy", "detail": "prod"
    }
    # Malformed JSON degrades to a literal action name rather than crashing.
    assert cli._parse_line("{not json") == {"action": "{not json", "detail": None}


def test_watch_flags_novel_actions_json(tmp_path, capsys):
    src = _write(tmp_path, "stream.txt", "plan\nact\nplan\nescalate\n")
    rc = cli.main(["watch", src, "--json"])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    verdicts = [json.loads(line) for line in out if line.startswith("{")]
    flagged = [v for v in verdicts if v.get("is_anomaly")]
    actions = {v["action"] for v in flagged}
    # Each distinct action is novel exactly once; the repeat of 'plan' is not.
    assert actions == {"plan", "act", "escalate"}


def test_watch_persists_history_and_report_reads_it(tmp_path, capsys):
    src = _write(tmp_path, "stream.txt", "plan\nact\nescalate\n")
    hist = str(tmp_path / "hist.json")
    cli.main(["watch", src, "--history", hist, "--quiet"])
    capsys.readouterr()  # drain

    rc = cli.main(["report", "--history", hist, "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["total"] == 3
    assert report["summary"]["novel"] == 3
    assert report["patterns"]["total"] == 3


def test_report_without_history_errors():
    with pytest.raises(SystemExit):
        cli.main(["report"])


def test_unknown_preset_errors(tmp_path):
    src = _write(tmp_path, "s.txt", "plan\n")
    with pytest.raises(SystemExit):
        cli.main(["watch", src, "--preset", "does-not-exist"])


def test_dashboard_writes_html_file(tmp_path, capsys):
    src = _write(tmp_path, "stream.txt", "plan\nact\n")
    hist = str(tmp_path / "hist.json")
    cli.main(["watch", src, "--history", hist, "--quiet"])
    capsys.readouterr()

    out = str(tmp_path / "dash.html")
    rc = cli.main(["dashboard", "--history", hist, "--out", out])
    assert rc == 0
    html = open(out, encoding="utf-8").read()
    assert html.startswith("<!doctype html>")


def test_report_does_not_rewrite_ledger(tmp_path, capsys):
    src = _write(tmp_path, "stream.txt", "plan\nact\n")
    hist = str(tmp_path / "hist.json")
    cli.main(["watch", src, "--history", hist, "--quiet"])
    capsys.readouterr()
    before = open(hist, encoding="utf-8").read()
    cli.main(["report", "--history", hist])
    capsys.readouterr()
    # A reporting command is read-only.
    assert open(hist, encoding="utf-8").read() == before
