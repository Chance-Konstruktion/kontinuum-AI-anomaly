"""The ZCode example must never let a command-line argument reach the monitor.

Agents put secrets into shell commands; the example keeps only the program
name. These tests pin that rule and run one pass against a fake ZCode DB.
"""
import importlib.util
import json
import sqlite3
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "zcode_watch.py"
# Assembled at runtime so the repository's own secret scanner (gitleaks)
# does not mistake the test fixture for a real token.
SECRET = "gl" + "pat-" + "AAAAbbbbCCCCdddd" + "EEEE1234"


def _load():
    spec = importlib.util.spec_from_file_location("zcode_watch", EXAMPLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bash_program_keeps_only_the_program_name():
    zw = _load()
    cases = {
        "cd /repo && git status": "git",
        "T=%s curl -H x https://example" % SECRET: "curl",
        "TOKEN=$(cat ~/.token) && python3 run.py": "python3",
        "sudo -n systemctl restart x": "systemctl",
        "/usr/bin/python3 script.py": "python3",
        "for f in *; do echo $f; done": "loop",
        "if true; then ls; fi": "branch",
        SECRET: "?",
        "cd somewhere": "?",
        "": "?",
    }
    for command, expected in cases.items():
        assert zw.bash_program(command) == expected, command


def test_model_family():
    zw = _load()
    assert zw.model_family("nvidia moonshotai/kimi-k3") == "kimi"
    assert zw.model_family("account:zai-start-plan GLM-5.3-Flash") == "glm"
    assert zw.model_family("deepseek-ai/deepseek-v4.1-flash") == "deepseek"
    assert zw.model_family(None) == "other"


def _fake_db(path):
    con = sqlite3.connect(str(path))
    con.execute("create table message (id text, data text)")
    con.execute("create table part (id text, message_id text, session_id text, "
                "time_created integer, data text)")
    con.execute("create table model_usage (session_id text, model_id text)")
    con.execute("insert into message values ('m1', ?)",
                (json.dumps({"role": "assistant", "modelId": "moonshotai/kimi-k3",
                             "providerId": "nvidia"}),))
    t = 1_790_000_000_000
    for i in range(60):
        cmd = "T=%s git push" % SECRET if i % 3 == 0 else "ls -la /home/x"
        part = {"type": "tool", "tool": "Bash", "callID": "c%d" % i,
                "state": {"input": {"command": cmd}}}
        con.execute("insert into part values (?, 'm1', 's1', ?, ?)",
                    ("p%03d" % i, t + i * 1000, json.dumps(part)))
    con.commit()
    con.close()


def test_one_pass_never_stores_the_secret(tmp_path):
    zw = _load()
    db = tmp_path / "db.sqlite"
    _fake_db(db)
    state = tmp_path / "state"
    watch = zw.ZCodeWatch(str(db), str(state), str(tmp_path / "overview.html"))
    assert watch.poll() == 60
    assert watch.state["seen"] == 60
    assert "kimi" in watch.multi.watches
    # A second pass reads nothing new.
    assert watch.poll() == 0
    for f in list(state.rglob("*")) + [tmp_path / "overview.html"]:
        if f.is_file():
            assert SECRET not in f.read_text(encoding="utf-8"), f
