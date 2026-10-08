"""Watch real coding agents: feed ZCode's tool calls into kontinuum-AI-anomaly.

ZCode (https://github.com/zai-org/ZCode) logs every tool call its agents make
in a local SQLite database. This example reads those calls (read-only), groups
them per model family (deepseek, kimi, glm, ...) and runs one AnomalyWatch per
family via MultiAgentWatch. Flagged steps go to a JSON-lines log and to an HTML
overview; models that misbehave together show up as correlated clusters.

This is the setup that runs next to our own agent desk: several models working
unattended against a GitLab instance, and a watcher that learns each model's
rhythm and reports when a step doesn't fit.

Privacy rule -- the important part: from a shell command only the PROGRAM
NAME is used ("Bash:git"), never its arguments. Agents do put secrets into
command lines (we found access tokens in plain text there), so arguments must
never reach the monitor, its ledger or its dashboard. Anything that does not
look like a plain program name becomes "Bash:?".

Run:
    python examples/zcode_watch.py --once          # one pass, then exit
    python examples/zcode_watch.py                 # keep watching (every 60 s)
    python examples/zcode_watch.py --db PATH --state-dir DIR --html FILE

The first pass replays the whole history as the learning phase (about 14 000
calls took 24 s on a small VM); after that only new calls are read.
"""
import argparse
import datetime
import json
import logging
import os
import re
import sqlite3
import sys
import time

from kontinuum_ai_anomaly import AlertRouter, CallbackSink, MultiAgentWatch, render_dashboard

DEFAULT_DB = os.path.expanduser("~/.zcode/cli/db/db.sqlite")

PROGRAM = re.compile(r"^[A-Za-z0-9_.+-]{1,24}$")
SKIP = {"cd", "export", "sudo", "timeout", "env", "nohup", "time", "then", "do", "set"}
FAMILIES = ("deepseek", "kimi", "glm", "nemotron", "qwen", "granite", "minimax", "laguna", "gpt")


def model_family(text):
    """Map a provider/model string to a short family name."""
    t = (text or "").lower()
    for name in FAMILIES:
        if name in t:
            return name
    return "other"


def bash_program(command):
    """The first real program name of a shell command -- or '?'.

    Assignments (``T=...``, including ``$( ... )`` on the right-hand side) are
    skipped entirely: that is exactly where secrets tend to sit.
    """
    for segment in re.split(r"&&|\|\||;|\||\n", command or ""):
        depth = 0  # open $( ... ) that still belongs to an assignment
        for word in segment.strip().split():
            if depth > 0 or ("=" in word and not word.startswith("-")):
                depth += word.count("(") - word.count(")")
                continue
            if word.startswith("-") or word in SKIP or word.isdigit():
                if word == "cd":
                    break  # the rest of this segment is cd's target
                continue
            if word in ("for", "while", "until"):
                return "loop"
            if word in ("if", "case"):
                return "branch"
            name = os.path.basename(word.strip("'\"()$`"))
            if "glpat" in name.lower() or "token" in name.lower():
                return "?"
            return name if PROGRAM.match(name) else "?"
    return "?"


def action_name(part):
    """The action string fed to the monitor for one ZCode tool part."""
    tool = part.get("tool") or "?"
    if tool.lower() == "bash":
        command = ((part.get("state") or {}).get("input") or {}).get("command")
        return "Bash:" + bash_program(command)
    return tool if PROGRAM.match(tool) or tool.startswith("mcp__") else "?"


class ZCodeWatch:
    def __init__(self, db, state_dir, html):
        self.db = db
        self.state_dir = state_dir
        self.html = html
        self.state_file = os.path.join(state_dir, "state.json")
        self.alert_log = os.path.join(state_dir, "alerts.jsonl")
        os.makedirs(state_dir, exist_ok=True)
        self.multi = MultiAgentWatch(
            window_seconds=120,
            router=AlertRouter([CallbackSink(self._log_alert)]),
            brain_dir=os.path.join(state_dir, "brain"),
            history_dir=os.path.join(state_dir, "ledger"),
        )
        # After a restart, load the known agents right away so they show up
        # on the overview before they act again.
        ledger_dir = os.path.join(state_dir, "ledger")
        if os.path.isdir(ledger_dir):
            for name in os.listdir(ledger_dir):
                if name.endswith(".json"):
                    self.multi.watch_for(name[:-5])
        self.state = self._load_state()

    def _load_state(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"time": 0, "id": "", "seen": 0, "flagged": 0}

    def _save_state(self):
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)
        os.replace(tmp, self.state_file)

    def _log_alert(self, rec):
        with open(self.alert_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec.as_dict(), ensure_ascii=False, default=str) + "\n")

    def poll(self):
        """Read new tool calls once; return how many were observed."""
        con = sqlite3.connect("file:" + self.db + "?mode=ro", uri=True, timeout=30)
        try:
            # Fallback when a message names no model: the session's most
            # frequent model according to model_usage.
            session_model = {}
            for sid, model, _n in con.execute(
                    "select session_id, model_id, count(*) from model_usage "
                    "group by 1, 2 order by 3"):
                session_model[sid] = model
            rows = con.execute(
                "select p.id, p.time_created, p.session_id, p.data, m.data from part p "
                "join message m on m.id = p.message_id "
                "where p.data like '%\"tool\"%' "
                "and (p.time_created > ? or (p.time_created = ? and p.id > ?)) "
                "order by p.time_created, p.id",
                (self.state["time"], self.state["time"], self.state["id"])).fetchall()
            observed = 0
            for pid, ms, sid, data, mdata in rows:
                try:
                    part, msg = json.loads(data), json.loads(mdata)
                except ValueError:
                    continue
                self.state["time"], self.state["id"] = ms, pid
                if part.get("type") != "tool":
                    continue
                model = msg.get("modelId") or session_model.get(sid) or ""
                agent = model_family("%s %s" % (msg.get("providerId"), model))
                ts = datetime.datetime.fromtimestamp(ms / 1000)
                verdict = self.multi.observe(agent, action_name(part), detail=sid, ts=ts)
                self.state["seen"] += 1
                self.state["flagged"] += int(bool(verdict.is_anomaly))
                observed += 1
            if rows:
                self.multi.save()
                self._save_state()
                self.write_overview()
            return observed
        finally:
            con.close()

    def write_overview(self):
        pages = os.path.join(self.state_dir, "dashboard")
        os.makedirs(pages, exist_ok=True)
        rows = []
        for agent, w in sorted(self.multi.watches.items()):
            page = os.path.join(pages, agent + ".html")
            with open(page, "w", encoding="utf-8") as f:
                f.write(render_dashboard(w.history, title="Agent watch: " + agent,
                                         days=None, metrics=w.metrics()))
            rows.append("<tr><td><a href='file://%s'>%s</a></td><td>%d</td><td>%d</td></tr>"
                        % (page, agent, len(w.history.recent(days=36500)),
                           len(w.history.recent(days=1))))
        clusters = self.multi.correlated_clusters()
        html = (
            "<!doctype html><meta charset='utf-8'><title>Agent watch</title>"
            "<style>body{font-family:sans-serif;margin:2em}td,th{padding:.3em .8em;"
            "border-bottom:1px solid #ccc;text-align:left}</style>"
            "<h1>Agent watch</h1><p>%s &middot; %d tool calls read, %d flagged. "
            "Shell commands count by program name only.</p>"
            "<table><tr><th>Model family</th><th>flagged (all)</th><th>last 24 h</th></tr>%s</table>"
            "<h2>Correlated clusters</h2><pre>%s</pre>"
            % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), self.state["seen"],
               self.state["flagged"], "".join(rows),
               json.dumps(clusters[-20:], ensure_ascii=False, indent=1, default=str)))
        with open(self.html, "w", encoding="utf-8") as f:
            f.write(html)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--state-dir", default=os.path.expanduser("~/zcode-watch"))
    p.add_argument("--html", default=None, help="overview page (default: STATE_DIR/overview.html)")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--once", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    watch = ZCodeWatch(args.db, args.state_dir,
                       args.html or os.path.join(args.state_dir, "overview.html"))
    while True:
        try:
            n = watch.poll()
            if n:
                logging.info("%d new calls, %d total, %d flagged",
                             n, watch.state["seen"], watch.state["flagged"])
        except sqlite3.OperationalError as e:
            logging.warning("database busy: %s", e)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
