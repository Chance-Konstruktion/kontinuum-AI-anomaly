# kontinuum-AI-anomaly

[![CI](https://github.com/Chance-Konstruktion/kontinuum-AI-anomaly/actions/workflows/ci.yml/badge.svg)](https://github.com/Chance-Konstruktion/kontinuum-AI-anomaly/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/kontinuum-ai-anomaly.svg)](https://pypi.org/project/kontinuum-AI-anomaly/)
[![Python versions](https://img.shields.io/pypi/pyversions/kontinuum-ai-anomaly.svg)](https://pypi.org/project/kontinuum-AI-anomaly/)
[![Downloads](https://img.shields.io/pypi/dm/kontinuum-ai-anomaly.svg)](https://pypi.org/project/kontinuum-AI-anomaly/)
[![kontinuum-core](https://img.shields.io/badge/kontinuum--core-%E2%89%A50.6.3-4c1.svg)](https://github.com/Chance-Konstruktion/kontinuum-core)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)

**Ein Neuheits- und Anomalie-Wächter für den Aktionsstrom von Agenten.**
Richte ihn auf das, was dein Agent *tut* — nicht auf ein Zuhause — und er lernt
den normalen Rhythmus des Agenten, um dir zu melden, wenn ein Schritt nicht passt.

Aufgebaut auf [`kontinuum-core`](https://github.com/Chance-Konstruktion/kontinuum-core),
einer neuro-inspirierten Lern-Engine. Dieses Paket ist die Schicht obendrauf, die
das rohe Signal der Engine in ein brauchbares Urteil verwandelt, eine Historie
führt und dich alarmieren kann.

> 🇬🇧 An English version of this README is available in
> [README.md](README.md).

---

## Warum es das gibt

`kontinuum-core` wurde geschrieben, um das Verhalten eines *Zuhauses* zu lernen —
Lichter, Sensoren, Räume. Aber die Grundidee (einen Ereignisstrom lernen und
flaggen, was überrascht) ist nicht auf Zuhause beschränkt. Auch ein autonomer
Agent — ein Bot, ein Scraper, ein „openclaw"-Worker — erzeugt einen Strom von
Aktionen mit einem normalen Rhythmus. Wenn dieser Rhythmus bricht, willst du das
in der Regel wissen.

Core liefert dir ein rohes „surprise"-Flag pro Ereignis, aber für sich genommen
ist dieses Flag bei kurzen Läufen sprunghaft und hat kein Gedächtnis dafür, *was
letzte Woche auffällig war*. Dieses Paket ergänzt genau die Teile, die Core
bewusst weglässt:

| Schicht | Modul | Was es hinzufügt |
|---|---|---|
| Ingestion | `AgentMonitor` | Speist benannte Agenten-Aktionen in die Engine und versteckt die Token-/Raum-Mechanik, die Core verlangt. |
| Scoring | `scoring` | Macht aus dem sprunghaften Roh-Flag ein stabiles Urteil: Neuheit zuerst, plus adaptiver Schwellenwert für *bekannte* Aktionen, sobald genug Daten da sind. |
| Historie | `history` | Ein Ledger — „was wurde diese Woche geflaggt?" — das Core nicht führt. |
| Alerting | `alerting` | Leitet Anomalien an einen Webhook, ein Log oder einen Callback zurück in deinen Agenten. |
| Korrelation | `correlation` | Beobachtet mehrere Agenten/Ströme gleichzeitig und verknüpft zusammenhängende Anomalien. |
| Feedback | `feedback` | Rendert den Engine-Zustand als Prompt, damit der Agent per eigenem LLM reflektieren kann. |
| Dashboard | `dashboard` | Eine kleine, eigenständige HTML-Ansicht. |
| Orchestrierung | `AnomalyWatch` | Verdrahtet all das hinter einem einzigen `observe()`-Aufruf. |

---

## Installation

```bash
pip install kontinuum-AI-anomaly
```

Benötigt Python ≥ 3.9 und `kontinuum-core >= 0.6.3` (wird automatisch mitgezogen).

---

## Schnellstart

```python
from kontinuum_ai_anomaly import AnomalyWatch

watch = AnomalyWatch(agent_id="openclaw")

# Die Engine den normalen Rhythmus des Agenten lernen lassen.
rhythm = ["plan", "act", "observe", "reflect", "done"]
for _ in range(20):
    for action in rhythm:
        watch.observe(action)

# Ein eingeübter Schritt ist unauffällig ...
watch.observe("plan").is_anomaly        # -> False

# ... ein nie gesehener Schritt wird geflaggt.
verdict = watch.observe("escalate")
print(verdict.is_anomaly, verdict.score, verdict.reasons)
# True 0.72 ['[novelty] never-seen action']
```

Diese Ausgabe ist echt, nicht illustrativ — sie ist das, was das Snippet oben
bei einer frischen Installation ausgibt.

Jedes `observe()` gibt ein `AnomalyScore` zurück mit: `action`, `is_anomaly`,
`score` (Schweregrad 0–1), `surprise`, `threshold`, `is_novel`, `reasons` und
`strategy`. `.as_dict()` liefert eine JSON-freundliche Form.

---

## Alerting in deinen Agenten

```python
from kontinuum_ai_anomaly import AnomalyWatch, AlertRouter, WebhookSink, LogSink

watch = AnomalyWatch(
    agent_id="openclaw",
    history_path="anomaly_history.json",   # Ledger persistieren
    router=AlertRouter([
        LogSink(),
        WebhookSink("https://example.com/hooks/openclaw"),
    ]),
)
```

Nur Aktionen, die die Anomalie-Schwelle überschreiten, werden aufgezeichnet und
geroutet — dein Webhook bleibt im Normalbetrieb also still. Mit `CallbackSink`
gibst du die Anomalie direkt an den Code deines Agenten zurück.

Siehe [`examples/openclaw_demo.py`](examples/openclaw_demo.py) für einen
Ende-zu-Ende-Lauf, der einen Rhythmus einübt, eine Neuheit einstreut, alarmiert
und ein Dashboard rendert.

---

## Worin es gut ist — und worin nicht

Ehrlichkeit hier bewahrt dich davor, dem falschen Signal zu vertrauen:

- **Zuverlässig:** *Neuheit* — eine wirklich nie gesehene Aktion wird sofort und
  sicher geflaggt.
- **Schwächer:** *Reihenfolge-/Sequenz-Anomalien* (richtige Aktionen, falsche
  Reihenfolge). Die Engine braucht viele Ereignisse, bis das schärfer wird, und
  bleibt unter 100 Ereignissen in einer `cold_start`-Lernphase. `SequenceStrategy`
  hilft, aber erwarte bei kurzen Läufen keine Wunder.
- **Was es nicht tut:** Es trainiert oder verändert deinen Agenten **nicht**. Es
  ist ein externer Beobachter, der ein Signal erzeugt; was du mit diesem Signal
  machst, bleibt dir überlassen.
- **Setzt ein begrenztes Aktions-Vokabular voraus.** Zustand pro Aktion
  (Surprise-Historien, Übergangszähler, Alert-Cooldowns) wird für jeden distinkten
  Aktionsnamen gehalten und nie verworfen — die Grenzen `max_records` /
  `max_events` beschränken *Ereignisse*, nicht *Streams*. Für `plan` / `observe` /
  `escalate` ist das genau richtig; steckt aber eine ID im Namen
  (`fetch_user_8123`), entsteht pro Wert ein dauerhafter Stream: Der Speicher
  wächst unbegrenzt, und ein einmal gesehener Stream kann nie eine Baseline
  aufbauen. Pack den variablen Teil in `detail=` — das wird nie zu einem Token.
  Siehe [`docs/API.md`](docs/API.md#memory-what-is-bounded-and-what-is-not).

Das Design spiegelt das wider: Das Scoring ist **neuheit-zuerst**, und der
adaptive Schwellenwert für bekannte Aktionen schaltet sich erst zu, wenn genug
Daten für ein belastbares Urteil vorliegen.

Die mühsam erarbeiteten Details dazu, *wie* Core Ereignisse tatsächlich
aufnimmt — samt der Fallstricke, die echte Debugging-Zeit gekostet haben —
findest du in [`docs/INSIGHTS.md`](docs/INSIGHTS.md). Diese Notizen entstanden
beim Reverse-Engineering von Cores Ingestion-Pfad und sind nirgends sonst
dokumentiert.

---

## Lizenz

AGPL-3.0. `kontinuum-core` ist AGPL-3.0 und dieses Paket importiert es, daher
propagieren die Copyleft- und Netzwerkdienst-Pflichten auch hierher. Wenn du
darauf aufbaust, behalte das im Hinterkopf.
