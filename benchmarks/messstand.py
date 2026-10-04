"""Der Messlauf, die Maße und die Tafel (Stufe 1, Punkte 4–5 des Tickets).

Ablauf je Saat: für jedes Profil eine Spur erzeugen, ALLE Läufer
(Gegner + Kandidaten) parallel über denselben Blick ohne Marke
laufen lassen, die Flags gegen die Marken wiegen. Jede Spur wird frisch
gebaut — kein Läufer sieht eine Spur zweimal, kein Läufer behält
Zustand über Spuren.

Die Maße, wie das Ticket sie verlangt:

* **Treffer** — ein Vorfall ist getroffen, wenn ein Flag des Läufers
  AUF einem Ereignis seines Vorfallfensters liegt. Gemeldet wird der
  Anteil getroffener Vorfälle je Art (5 Vorfälle je Art und Saat —
  einer je Profil).
* **Fehlalarme je 1000 normale Ereignisse** — Flags auf Ereignissen
  mit Marke ``normal``, hochgerechnet je 1000.
* **Ereignisse bis zur Erkennung** — der Stand des Vorfallfensters,
  an dem das erste Flag fiel (1-basiert; Mittel über die Treffer,
  „—" wenn keiner).
* **Gepaarte Differenz** — je Saat: Kandidat − bester Gegner (bei
  Treffern der beste = höchste Quote, bei Fehlalarmen der beste =
  niedrigste Rate); gemeldet als Mittelwert ± Streuung über die
  Saaten.

Ehrlichkeit als Bau-Regel: Die Tafel enthält die Niederlagen mit —
eine Zeile, die der Kern verliert, bleibt in der Tafel und in den
Charakterisierungstests, genau dafür ist der Messstand da.
"""
from __future__ import annotations

import argparse
import json
import sys
from importlib import metadata
from pathlib import Path
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

from .agenten import AgentProfil, profile
from .gegner import B0, B1, B2
from .kandidaten import kandidaten as baue_kandidaten
from .spur import Spur, MARKE_NORMAL, waechterblick
from .vorfaelle import VORFALLSARTEN, spur_mit_vorfaellen

LAUEFER_GEGNER = ("B0", "B1", "B2")
GEGNER_KLASSEN = {"B0": B0, "B1": B1, "B2": B2}


# ---------------------------------------------------------------------------
# Ein Messlauf über eine Spur
# ---------------------------------------------------------------------------


def laufe_spur(
    spur: Spur, laeufer: List[Tuple[str, object]],
) -> Dict[str, object]:
    """Alle Läufer über eine Spur; liefert Fenster- und Fehlalarm-Zahlen
    je Läufer. Die Läufer müssen frisch sein (``neu`` wurde gerufen bzw.
    die Instanzen sind neu gebaut) — der Aufrufer organisiert das."""
    blick, marken = waechterblick(spur)
    flags: Dict[str, List[bool]] = {name: [] for name, _ in laeufer}
    for ereignis in blick:
        for name, laufer in laeufer:
            flags[name].append(
                bool(laufer.beobachte(ereignis.ts, ereignis.aktion,
                                      ereignis.detail))
            )

    # Vorfallfenster: zusammenhängende Blöcke derselben Vorfall-Marke.
    fenster: Dict[Tuple[str, int], List[int]] = {}
    normale: List[int] = []
    for index, marke in enumerate(marken):
        if marke == MARKE_NORMAL:
            normale.append(index)
            continue
        art, nr = marke.split("/", 1)
        fenster.setdefault((art, int(nr)), []).append(index)

    ergebnis: Dict[str, object] = {
        "normale_ereignisse": len(normale),
        "fenster": {},
        "fehlalarme": {},
    }
    for name, _ in laeufer:
        spur_flags = flags[name]
        falsch = sum(1 for i in normale if spur_flags[i])
        ergebnis["fehlalarme"][name] = falsch
    for (art, nr), indizes in fenster.items():
        zeile: Dict[str, object] = {}
        for name, _ in laeufer:
            spur_flags = flags[name]
            treffer_pos = None
            for stand, index in enumerate(indizes, start=1):
                if spur_flags[index]:
                    treffer_pos = stand
                    break
            zeile[name] = treffer_pos
        ergebnis["fenster"][f"{art}/{nr}"] = zeile
    return ergebnis


# ---------------------------------------------------------------------------
# Der ganze Messstand
# ---------------------------------------------------------------------------


def laufe_messstand(
    saaten: List[int], tage: int = 3,
    profile_liste: Optional[List[AgentProfil]] = None,
) -> Dict[str, object]:
    """Fährt Saaten × Profile × Läufer und liefert den vollen Bericht
    (je Saat und die Tafel-Aggregate)."""
    profile_liste = profile_liste if profile_liste is not None else profile()
    kandidaten = baue_kandidaten()
    laeufer_namen = list(LAUEFER_GEGNER) + [k.name for k in kandidaten]

    je_saat: Dict[str, dict] = {}
    for saat in saaten:
        treffer: Dict[str, Dict[str, int]] = {
            art: {name: 0 for name in laeufer_namen} for art in VORFALLSARTEN
        }
        plaetze: Dict[str, int] = {art: 0 for art in VORFALLSARTEN}
        bis_erkennung: Dict[str, Dict[str, List[int]]] = {
            art: {name: [] for name in laeufer_namen}
            for art in VORFALLSARTEN
        }
        fehlalarme: Dict[str, int] = {name: 0 for name in laeufer_namen}
        normale_gesamt = 0

        for profil in profile_liste:
            spur = spur_mit_vorfaellen(profil, saat, tage=tage)
            laeufer: List[Tuple[str, object]] = [
                (name, GEGNER_KLASSEN[name]())
                for name in LAUEFER_GEGNER
            ]
            for kandidat in kandidaten:
                kandidat.neu(agent_id=profil.name)
                laeufer.append((kandidat.name, kandidat))
            spur_ergebnis = laufe_spur(spur, laeufer)

            normale_gesamt += spur_ergebnis["normale_ereignisse"]
            for name in laeufer_namen:
                fehlalarme[name] += spur_ergebnis["fehlalarme"][name]
            for schluessel, zeile in spur_ergebnis["fenster"].items():
                art = schluessel.split("/", 1)[0]
                plaetze[art] += 1
                for name, pos in zeile.items():
                    if pos is not None:
                        treffer[art][name] += 1
                        bis_erkennung[art][name].append(pos)

        fehlalarme_je_1000 = {
            name: (fehlalarme[name] / normale_gesamt * 1000.0
                   if normale_gesamt else 0.0)
            for name in laeufer_namen
        }
        je_saat[str(saat)] = {
            "treffer": treffer,
            "plaetze": plaetze,
            "bis_erkennung": bis_erkennung,
            "fehlalarme": fehlalarme,
            "normale_ereignisse": normale_gesamt,
            "fehlalarme_je_1000": fehlalarme_je_1000,
        }

    tafel = _tafel_aggregate(je_saat, saaten, laeufer_namen, kandidaten)
    return {
        "meta": {
            "saaten": saaten,
            "tage": tage,
            "profile": [p.name for p in profile_liste],
            "laeufer": laeufer_namen,
            "vorfaelle_je_art_und_saat": len(profile_liste),
            "kontinuum_core": _version("kontinuum-core"),
            "kontinuum_ai_anomaly": _version("kontinuum-AI-anomaly"),
            "entwicklungshinweis": "Entwicklung nur auf Saaten < 1000; "
                                   "der versiegelte Prüfsatz fährt getrennt.",
        },
        "je_saat": je_saat,
        "tafel": tafel,
    }


def _version(paket: str) -> str:
    try:
        return metadata.version(paket)
    except metadata.PackageNotFoundError:
        return "unbekannt"


def _mit_streuung(werte: List[float]) -> Dict[str, float]:
    if not werte:
        return {"mittel": 0.0, "streuung": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mittel": mean(werte),
        "streuung": stdev(werte) if len(werte) > 1 else 0.0,
        "min": min(werte),
        "max": max(werte),
    }


def _tafel_aggregate(
    je_saat: Dict[str, dict], saaten: List[int], laeufer_namen: List[str],
    kandidaten: list,
) -> Dict[str, object]:
    """Aggregiert je Saat zu Tafel-Zahlen: Trefferquoten, Fehlalarmraten,
    Ereignisse bis zur Erkennung und die gepaarten Differenzen der
    Kandidaten gegen den besten Gegner."""
    gegner_namen = list(LAUEFER_GEGNER)
    kandidat_namen = [k.name for k in kandidaten]

    treffer_quote: Dict[str, Dict[str, List[float]]] = {
        art: {name: [] for name in laeufer_namen}
        for art in VORFALLSARTEN
    }
    fehl_rate: Dict[str, List[float]] = {
        name: [] for name in laeufer_namen
    }
    bis_erkennung_mittel: Dict[str, Dict[str, List[float]]] = {
        art: {name: [] for name in laeufer_namen}
        for art in VORFALLSARTEN
    }
    differenz: Dict[str, Dict[str, List[float]]] = {
        name: {art: [] for art in VORFALLSARTEN}
        for name in kandidat_namen
    }
    differenz_fehl: Dict[str, List[float]] = {name: [] for name in kandidat_namen}

    for saat in saaten:
        satz = je_saat[str(saat)]
        for art in VORFALLSARTEN:
            plaetze = satz["plaetze"][art] or 1
            for name in laeufer_namen:
                treffer_quote[art][name].append(
                    satz["treffer"][art][name] / plaetze
                )
                if satz["bis_erkennung"][art][name]:
                    bis_erkennung_mittel[art][name].append(
                        mean(satz["bis_erkennung"][art][name])
                    )
        for name in laeufer_namen:
            fehl_rate[name].append(satz["fehlalarme_je_1000"][name])
        for name in kandidat_namen:
            for art in VORFALLSARTEN:
                bester = max(
                    satz["treffer"][art][g] / (satz["plaetze"][art] or 1)
                    for g in gegner_namen
                )
                eigner = satz["treffer"][art][name] / (satz["plaetze"][art] or 1)
                differenz[name][art].append(eigner - bester)
            bester_fehl = min(satz["fehlalarme_je_1000"][g]
                              for g in gegner_namen)
            differenz_fehl[name].append(
                satz["fehlalarme_je_1000"][name] - bester_fehl
            )

    tafel: Dict[str, object] = {
        "treffer_je_art": {
            art: {
                name: _mit_streuung(treffer_quote[art][name])
                for name in laeufer_namen
            }
            for art in VORFALLSARTEN
        },
        "fehlalarme_je_1000": {
            name: _mit_streuung(fehl_rate[name]) for name in laeufer_namen
        },
        "bis_erkennung": {
            art: {
                name: (mean(werte) if werte else None)
                for name, werte in bis_erkennung_mittel[art].items()
            }
            for art in VORFALLSARTEN
        },
        "differenz_gegen_besten_gegner": {
            name: {
                art: _mit_streuung(differenz[name][art])
                for art in VORFALLSARTEN
            }
            for name in kandidat_namen
        },
        "differenz_fehlalarme": {
            name: _mit_streuung(differenz_fehl[name])
            for name in kandidat_namen
        },
    }
    return tafel


# ---------------------------------------------------------------------------
# Die Tafel
# ---------------------------------------------------------------------------


def _prozent(wert: float) -> str:
    return f"{round(wert * 100)} %"


def tafel_markdown(bericht: Dict[str, object]) -> str:
    """Der Bericht als Markdown-Tafel — Artefakt und Lesefutter."""
    meta = bericht["meta"]
    tafel = bericht["tafel"]
    laeufer = meta["laeufer"]
    zeilen: List[str] = []
    zeilen.append("# Messstand: der Wächter gegen die dummen Gegner (Stufe 1)")
    zeilen.append("")
    zeilen.append(
        f"Saaten: {', '.join(str(s) for s in meta['saaten'])} "
        f"(Entwicklung nur unter 1000) · Tage je Spur: {meta['tage']} · "
        f"Profile: {', '.join(meta['profile'])} · Vorfälle je Art und "
        f"Saat: {meta['vorfaelle_je_art_und_saat']} (einer je Profil) · "
        f"kontinuum-core {meta['kontinuum_core']} · "
        f"kontinuum-AI-anomaly {meta['kontinuum_ai_anomaly']}"
    )
    zeilen.append("")
    zeilen.append("## Treffer je Vorfallart (Anteil der Vorfälle mit Flag im Fenster)")
    zeilen.append("")
    kopf = "| Vorfall | " + " | ".join(laeufer) + " |"
    zeilen.append(kopf)
    zeilen.append("|" + "---|" * (len(laeufer) + 1))
    for art in VORFALLSARTEN:
        zellen = [_prozent(tafel["treffer_je_art"][art][name]["mittel"])
                  for name in laeufer]
        zeilen.append(f"| {art} | " + " | ".join(zellen) + " |")
    zeilen.append("")
    zeilen.append("## Fehlalarme je 1000 normale Ereignisse")
    zeilen.append("")
    zeilen.append("| " + " | ".join(laeufer) + " |")
    zeilen.append("|" + "---|" * len(laeufer))
    zeilen.append("| " + " | ".join(
        f"{tafel['fehlalarme_je_1000'][name]['mittel']:.1f}"
        for name in laeufer
    ) + " |")
    zeilen.append("")
    zeilen.append(
        "## Ereignisse bis zur Erkennung (Mittel über Treffer; '—' wenn nie)")
    zeilen.append("")
    kopf = "| Vorfall | " + " | ".join(laeufer) + " |"
    zeilen.append(kopf)
    zeilen.append("|" + "---|" * (len(laeufer) + 1))
    for art in VORFALLSARTEN:
        zellen = []
        for name in laeufer:
            wert = tafel["bis_erkennung"][art][name]
            zellen.append("—" if wert is None else f"{wert:.1f}")
        zeilen.append(f"| {art} | " + " | ".join(zellen) + " |")
    zeilen.append("")
    zeilen.append(
        "## Gepaarte Differenz Kandidat − bester Gegner, Treffer "
        "(Mittel ± Streuung über Saaten; negativ = Kandidat verliert)")
    zeilen.append("")
    kandidaten = [n for n in laeufer if n not in LAUEFER_GEGNER]
    kopf = "| Vorfall | " + " | ".join(kandidaten) + " |"
    zeilen.append(kopf)
    zeilen.append("|" + "---|" * (len(kandidaten) + 1))
    for art in VORFALLSARTEN:
        zellen = []
        for name in kandidaten:
            d = tafel["differenz_gegen_besten_gegner"][name][art]
            zellen.append(f"{d['mittel']:+.2f} ± {d['streuung']:.2f} "
                          f"({d['min']:+.2f} … {d['max']:+.2f})")
        zeilen.append(f"| {art} | " + " | ".join(zellen) + " |")
    zeilen.append("")
    zeilen.append(
        "Gepaarte Differenz, Fehlalarme je 1000 normale Ereignisse "
        "(Kandidat − bester Gegner; negativ = Kandidat leiser):")
    zeilen.append("")
    zeilen.append("| " + " | ".join(kandidaten) + " |")
    zeilen.append("|" + "---|" * len(kandidaten))
    zeilen.append("| " + " | ".join(
        f"{tafel['differenz_fehlalarme'][name]['mittel']:+.1f} ± "
        f"{tafel['differenz_fehlalarme'][name]['streuung']:.1f}"
        for name in kandidaten
    ) + " |")
    zeilen.append("")
    zeilen.append(
        "Alle Zahlen aus synthetischen Spuren (Saaten siehe oben); "
        "Detektoren sahen nie die Marken — nur den Blick ohne Etikett."
    )
    return "\n".join(zeilen) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.messstand",
        description="Stufe 1 des Leit-Tickets: der Messstand gegen "
                    "die dummen Gegner B0/B1/B2.",
    )
    parser.add_argument(
        "--saaten", default="7,23,42,101,255",
        help="Kommaliste der Saaten. Entwicklung nur unter 1000 — "
             "der versiegelte Prüfsatz fährt getrennt.",
    )
    parser.add_argument(
        "--tage", type=int, default=3,
        help="Simulierte Kalendertage je Spur (Standard: 3).",
    )
    parser.add_argument(
        "--ziel", default="artefakte",
        help="Zielverzeichnis für messstand_tafel.md und messstand.json.",
    )
    args = parser.parse_args(argv)
    saaten = [int(s) for s in args.saaten.split(",") if s.strip()]
    ueber_tausend = [s for s in saaten if s >= 1000]
    if ueber_tausend:
        print(
            "WARNUNG: Saaten >= 1000 gehören dem versiegelten Prüfsatz "
            f"(hier: {ueber_tausend}) — nicht für die Entwicklung "
            "verwenden.",
            file=sys.stderr,
        )
    bericht = laufe_messstand(saaten, tage=args.tage)
    ziel = Path(args.ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "messstand_tafel.md").write_text(
        tafel_markdown(bericht), encoding="utf-8",
    )
    (ziel / "messstand.json").write_text(
        json.dumps(bericht, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(tafel_markdown(bericht), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
