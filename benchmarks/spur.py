"""Die Agenten-Spur (Stufe 1, kontinuum-ai-anomaly #1).

JSONL mit einer Kopf-Zeile und einem Ereignis je Zeile. Angelehnt an
das Spurformat v1 aus ``kontinuum-core/benchmarks/spur``
(kontinuum-spur/1) — wo es passt übernommen, statt ein zweites zu
erfinden:

* **Kopf-Zeile vor allen Ereignissen** — mit Format-Marke, Quelle,
  Zeitzone und Zeitraum, wie in kontinuum-spur/1.
* **Zeit ist Pflicht mit Zone** (ISO-8601 mit Offset). Eine naive Zeit
  ist ein Fehler: die Stunde steckt im Stundenprofil der Gegner, eine
  UTC-Umrechnung würde den Arbeitstag verschieben.
* **``marke`` ist NUR Diagnose.** Sie trägt ``"normal"`` oder
  ``Vorfallart/Nummer`` und ist die Wahrheit, gegen die der Messstand
  wiegt. Kein Detektor sieht sie — :func:`waechterblick` liefert
  genau den Blick ohne Etikett, und nichts anderes geht in einen
  Gegner oder Kandidaten.
* **Ordnung wird geprüft** (nicht absteigend), **Fehler haben Namen**
  (:class:`SpurFehler`), beides wie in kontinuum-spur/1.

Wo die Welt anders ist, trägt das Format das auch: Ein Agent handelt
in Aktionen (``aktion`` mit optionalem ``detail`` als Ziel), nicht in
``Raum.Semantik.Zustand``-Tokenn. Die Tokenisierung des Thalamus
bleibt im Kern-Repo; hier gibt es keine und deshalb auch keine
Entitätentabelle im Kopf.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

SPUR_FORMAT = "kontinuum-agent-spur/1"
#: Das Format, von dem dieses hier abgeleitet ist (kontinuum-core,
#: benchmarks/spur). Es steht im Kopf, damit die Verwandtschaft
#: lesbar bleibt und nicht als zweite Wahrheit durchgeht.
SPUR_BASIS = "kontinuum-spur/1"
QUELLE = "simulation"
#: Der Kopf nennt die Rolle der Marke selbst — wer sie liest, ohne zu
#: werten, weiß wenigstens, dass sie nicht zur Eingabe gehört.
MARKE_ROLLE = "nur-diagnose"
#: Etikett für alles Normale; alles andere ist ``Vorfallart/Nummer``.
MARKE_NORMAL = "normal"


class SpurFehler(ValueError):
    """Format-, Ordnungs- oder Zeitfehler — mit Namen, nie still."""


# ---------------------------------------------------------------------------
# Datentypen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Kopf:
    """Der Kopf der Spur: WER (Agent, Rolle), WIE ERZEUGT (Saat) und
    WIE LANGE (Zeitraum)."""

    agent: str
    rolle: str
    saat: int
    zeitzone: str
    zeitraum: Tuple[str, str]

    def als_json(self) -> dict:
        return {
            "format": SPUR_FORMAT,
            "basis": SPUR_BASIS,
            "agent": self.agent,
            "rolle": self.rolle,
            "quelle": QUELLE,
            "saat": self.saat,
            "zeitzone": self.zeitzone,
            "marke_rolle": MARKE_ROLLE,
            "zeitraum": list(self.zeitraum),
        }


@dataclass(frozen=True)
class Ereignis:
    """Eine Agenten-Handlung. ``marke`` ist NUR Diagnose
    (:data:`MARKE_NORMAL` oder ``Vorfallart/Nummer``) und darf keinem
    Detektor gezeigt werden."""

    ts: datetime
    aktion: str
    detail: Optional[str] = None
    marke: Optional[str] = None

    def als_json(self) -> dict:
        daten = {
            "ts": self.ts.isoformat(),
            "aktion": self.aktion,
            "detail": self.detail,
            "marke": self.marke,
        }
        return daten


@dataclass
class Spur:
    kopf: Kopf
    ereignisse: List[Ereignis]


# ---------------------------------------------------------------------------
# Zeit
# ---------------------------------------------------------------------------


def lies_ts(text: str) -> datetime:
    """ISO-8601 MIT Zone (oder ``Z``). Eine naive Zeit ist ein Fehler:
    Ortszeit ohne Zone ist nicht eindeutig, und das Stundenprofil der
    Gegner hängt an der Ortszeit (dieselbe Regel wie kontinuum-spur/1,
    Protokoll § 2)."""
    if not isinstance(text, str) or not text:
        raise SpurFehler(f"Zeitstempel fehlt oder ist kein Text: {text!r}")
    roh = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        zeit = datetime.fromisoformat(roh)
    except ValueError as problem:
        raise SpurFehler(
            f"Zeitstempel nicht lesbar: {text!r} ({problem})"
        ) from problem
    if zeit.tzinfo is None or zeit.tzinfo.utcoffset(zeit) is None:
        raise SpurFehler(
            f"Zeitstempel ohne Zone: {text!r} — Ortszeit braucht ein Offset "
            "(z. B. +01:00); das Stundenprofil hängt an der Ortszeit."
        )
    return zeit


# ---------------------------------------------------------------------------
# Lesen / Schreiben
# ---------------------------------------------------------------------------


def lies_spur(pfad) -> Spur:
    """Liest eine Agenten-Spur (JSONL). Erste Zeile Kopf, danach ein
    Ereignis je Zeile. Ordnung wird geprüft: nicht absteigend."""
    text = Path(pfad).read_text(encoding="utf-8")
    zeilen = [z for z in text.split("\n") if z.strip()]
    if not zeilen:
        raise SpurFehler(f"Leere Spur: {pfad}")
    try:
        kopf_roh = json.loads(zeilen[0])
    except json.JSONDecodeError as problem:
        raise SpurFehler(f"Kopfzeile kein JSON: {problem}") from problem
    if kopf_roh.get("format") != SPUR_FORMAT:
        raise SpurFehler(
            f"Kopf trägt {kopf_roh.get('format')!r}, erwartet {SPUR_FORMAT!r}"
        )
    for pflicht in ("agent", "rolle", "zeitzone"):
        if not kopf_roh.get(pflicht):
            raise SpurFehler(f"Kopf unvollständig, es fehlt: {pflicht}")
    if kopf_roh.get("quelle") != QUELLE:
        raise SpurFehler(
            f"quelle unbekannt: {kopf_roh.get('quelle')!r} (erlaubt: {QUELLE})"
        )
    if not isinstance(kopf_roh.get("saat"), int):
        raise SpurFehler("Kopf ohne Saat (int) — die Spur wäre nicht "
                         "reproduzierbar.")
    zeitraum = kopf_roh.get("zeitraum")
    if not isinstance(zeitraum, list) or len(zeitraum) != 2:
        raise SpurFehler(f"zeitraum muss [start, ende] sein: {zeitraum!r}")
    kopf = Kopf(
        agent=kopf_roh["agent"],
        rolle=kopf_roh["rolle"],
        saat=kopf_roh["saat"],
        zeitzone=kopf_roh["zeitzone"],
        zeitraum=(str(zeitraum[0]), str(zeitraum[1])),
    )
    ereignisse: List[Ereignis] = []
    letzte_zeit: Optional[datetime] = None
    for nummer, zeile in enumerate(zeilen[1:], start=2):
        try:
            roh = json.loads(zeile)
        except json.JSONDecodeError as problem:
            raise SpurFehler(
                f"Zeile {nummer} kein JSON: {problem}"
            ) from problem
        for pflicht in ("ts", "aktion"):
            if not roh.get(pflicht) and roh.get(pflicht) != 0:
                raise SpurFehler(f"Zeile {nummer}: '{pflicht}' fehlt")
        zeit = lies_ts(roh["ts"])
        if letzte_zeit is not None and zeit < letzte_zeit:
            raise SpurFehler(
                f"Zeile {nummer}: Zeit fällt ({roh['ts']} nach "
                f"{letzte_zeit.isoformat()}) — die Spur darf nicht "
                "absteigend sortiert sein."
            )
        letzte_zeit = zeit
        detail = roh.get("detail")
        marke = roh.get("marke")
        ereignisse.append(
            Ereignis(
                ts=zeit,
                aktion=str(roh["aktion"]),
                detail=str(detail) if detail is not None else None,
                marke=str(marke) if marke is not None else None,
            )
        )
    return Spur(kopf=kopf, ereignisse=ereignisse)


def schreibe_spur(spur: Spur, pfad) -> None:
    """Schreibt die Spur als JSONL (UTF-8, LF)."""
    ziel = Path(pfad)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    zeilen = [json.dumps(spur.kopf.als_json(), ensure_ascii=False)]
    for e in spur.ereignisse:
        zeilen.append(json.dumps(e.als_json(), ensure_ascii=False))
    ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# Der Blick ohne Etikett
# ---------------------------------------------------------------------------


def waechterblick(spur: Spur) -> Tuple[List[Ereignis], List[str]]:
    """Zerlegt die Spur in das, was ein Detektor sehen darf, und die
    Wahrheit, gegen die gewogen wird.

    Liefert ``(ereignisse, marken)``: Die Ereignisse tragen ts, Aktion
    und Detail — die Marke ist ABGESCHNITTEN (eine frische Ereignisliste
    ohne ``marke``), die Marken laufen parallel als Liste. Ein Detektor,
    der hier drüber läuft, kann die Wahrheit strukturell nicht lesen;
    genau die Schule des Spurformats v1 („Diagnose bleibt dran, Wahrheit
    nicht").
    """
    blick = [
        Ereignis(ts=e.ts, aktion=e.aktion, detail=e.detail, marke=None)
        for e in spur.ereignisse
    ]
    marken = [e.marke or MARKE_NORMAL for e in spur.ereignisse]
    return blick, marken


__all__ = [
    "SPUR_FORMAT",
    "SPUR_BASIS",
    "QUELLE",
    "MARKE_ROLLE",
    "MARKE_NORMAL",
    "SpurFehler",
    "Kopf",
    "Ereignis",
    "Spur",
    "lies_ts",
    "lies_spur",
    "schreibe_spur",
    "waechterblick",
]
