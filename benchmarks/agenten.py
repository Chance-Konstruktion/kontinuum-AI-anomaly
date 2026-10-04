"""Die normalen Agenten — der Generator des Messstands (Stufe 1, #1).

Mehrere Normal-Agenten, nicht nur einer: Jedes Profil hat ein eigenes
Aktionsvokabular als Markov-Kette, einen eigenen Rhythmus
(Zwischenereignis-Abstände), ein eigenes Aktivfenster (Tageszeit,
in Ortsstunden) und eigene Details (Ziele). Der normale Strom bleibt
im Profil: legaler Übergang an legaler Stelle zu legaler Uhrzeit mit
bekanntem Ziel.

Zwei bewusste Bau-Regeln, damit die Messung fair bleibt:

* **Alle Kettengewichte >= 0,05.** Die ``SequenceStrategy`` des Pakets
  flaggt gelernte Übergänge mit p <= 0.02; ein normales Profil mit
  selteneren legalen Übergängen würde den Kandidaten Fehlalarme
  einimpfen, die am Verhalten des Profils liegen, nicht am Wächter.
* **Pausen bleiben unter einer Stunde.** Die Funkstille-Schwelle von
  B2 (gegner.py) liegt mit Absicht klar darüber; ein normales Profil
  mit halbtägigen Pausen wäre ein versteckter Vorfall.

Die Uhr läuft in einer FESTEN Zone (UTC+01:00, keine Sommerzeit) —
die Ortsstunde entspricht damit immer der Stunde im Zeitstempel.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

#: Fester Zeitanker der Simulation: Montag, 02.03.2026, UTC+01:00.
BASIS_DATUM = datetime(2026, 3, 2, 0, 0, 0, tzinfo=timezone(timedelta(hours=1)))
ZEITZONE = "UTC+01:00"
#: Kleinste erlaubte Übergangswahrscheinlichkeit einer normalen Kette
#: (siehe Modul-Docstring).
MIN_GEWICHT = 0.05


@dataclass(frozen=True)
class AgentProfil:
    """Ein normaler Agent: Vokabular, Kette, Rhythmus, Tageszeit, Details."""

    name: str
    rolle: str
    aktionen: Tuple[str, ...]
    #: Aktion -> ((Folgeaktion, Gewicht), ...); Gewichte werden beim
    #: Ziehen normalisiert, müssen aber jede >= MIN_GEWICHT sein.
    ketten: Dict[str, Tuple[Tuple[str, float], ...]]
    start: str
    #: Min/Max-Abstand zwischen zwei Ereignissen in Sekunden.
    luecken_s: Tuple[float, float]
    #: Aktivfenster in Ortsstunden; (21.0, 5.0) läuft über Mitternacht.
    aktiv: Tuple[Tuple[float, float], ...]
    #: Tägliche Pausen in Ortsstunden — bleiben unter einer Stunde.
    pausen: Tuple[Tuple[float, float], ...]
    #: Aktion -> ((Ziel, Gewicht), ...) — die Details der Aktion.
    details: Dict[str, Tuple[Tuple[str, float], ...]]


def pruefe_profil(profil: AgentProfil) -> None:
    """Benannte Selbstprüfung: Jede Aktion hat Ausgänge, jedes Gewicht
    bleibt über MIN_GEWICHT, Start und Details liegen im Vokabular.
    Ein Profil, das dagegen verstößt, ist ein Generatorfehler — nie
    ein stiller Messfehler."""
    for aktion in profil.aktionen:
        ausgaenge = profil.ketten.get(aktion)
        if not ausgaenge:
            raise ValueError(f"Profil {profil.name}: Aktion {aktion!r} hat "
                             "keine Kettenausgänge.")
        for folge, gewicht in ausgaenge:
            if folge not in profil.aktionen:
                raise ValueError(
                    f"Profil {profil.name}: Übergang {aktion!r}→{folge!r} "
                    "verlässt das Vokabular."
                )
            if gewicht < MIN_GEWICHT:
                raise ValueError(
                    f"Profil {profil.name}: Gewicht {aktion!r}→{folge!r} = "
                    f"{gewicht} unter MIN_GEWICHT ({MIN_GEWICHT}) — solche "
                    "seltenen legalen Übergänge würde die SequenceStrategy "
                    "als Fehlalarm lesen."
                )
    if profil.start not in profil.aktionen:
        raise ValueError(f"Profil {profil.name}: Startaktion {profil.start!r} "
                         "fehlt im Vokabular.")
    for aktion in profil.details:
        if aktion not in profil.aktionen:
            raise ValueError(f"Profil {profil.name}: Detail-Vokabular für "
                             f"fremde Aktion {aktion!r}.")
    for aktion in profil.aktionen:
        if aktion not in profil.details:
            raise ValueError(f"Profil {profil.name}: Aktion {aktion!r} ohne "
                             "Detail-Vokabular — der Vorfall 'ungewohntes "
                             "Ziel' braucht einen Normalzustand zum Vergleichen.")


def in_fenster(fenster: Tuple[Tuple[float, float], ...], stunde: float) -> bool:
    """Liegt die Ortsstunde in einem der Fenster (Über-Mitternacht-Fenster
    erlaubt)?"""
    for a, b in fenster:
        if a < b:
            if a <= stunde < b:
                return True
        elif stunde >= a or stunde < b:
            return True
    return False


def _ortsstunde(ts: datetime) -> float:
    return ts.hour + ts.minute / 60.0 + ts.second / 3600.0


def akzeptabel(ts: datetime, profil: AgentProfil) -> bool:
    """Ereigniszeit im Aktivfenster und nicht in einer Pause?"""
    stunde = _ortsstunde(ts)
    if not in_fenster(profil.aktiv, stunde):
        return False
    return not in_fenster(profil.pausen, stunde)


def springe_vor(ts: datetime, profil: AgentProfil) -> datetime:
    """Die nächste akzeptable Ereigniszeit NACH ``ts``. Zwei Fälle:
    Innerhalb eines Aktivfensters wird eine Pause zum PAUSENENDE
    gesprungen (die Nachtschicht verliert sonst ihre eigene Nacht);
    außerhalb aller Fenster springt die Uhr zum nächsten Fensteranfang
    (heute danach oder, wenn keiner mehr kommt, morgen)."""
    kandidat = ts + timedelta(minutes=1)
    for _ in range(3 * 24 * 60):  # nie länger als drei Tage suchen
        if akzeptabel(kandidat, profil):
            return kandidat
        stunde = _ortsstunde(kandidat)
        if in_fenster(profil.aktiv, stunde):
            # In einer Pause (Pausen laufen nie über Mitternacht —
            # Bau-Regel dieses Moduls): ans Pausenende springen.
            ende = max(b for a, b in profil.pausen
                       if a <= stunde < b)
            kandidat = kandidat.replace(
                hour=int(ende), minute=int((ende % 1) * 60),
                second=0, microsecond=0,
            ) + timedelta(minutes=1)
        else:
            starts = sorted(a for a, _ in profil.aktiv)
            spaeter = [a for a in starts if a > stunde]
            if spaeter:
                ziel = spaeter[0]  # heute
            else:
                ziel = starts[0]  # morgen
                kandidat = kandidat + timedelta(days=1)
            kandidat = kandidat.replace(
                hour=int(ziel), minute=int((ziel % 1) * 60),
                second=0, microsecond=0,
            ) + timedelta(minutes=1)
    raise ValueError(f"Profil {profil.name}: kein akzeptabler Zeitpunkt "
                     f"nach {ts.isoformat()} gefunden.")


def naechste_luecke(profil: AgentProfil, rng: random.Random) -> float:
    """Zwischenereignis-Abstand in Sekunden, gleichverteilt im Profilband
    (dieselbe ehrliche Einfachheit wie die Gegenprobe: 30–120 s)."""
    unten, oben = profil.luecken_s
    return rng.uniform(unten, oben)


def naechste_aktion(
    profil: AgentProfil, rng: random.Random, aktuell: str,
    kette: Optional[Dict[str, Tuple[Tuple[str, float], ...]]] = None,
) -> str:
    """Der nächste Kettenschritt (normalisiert); ``kette`` erlaubt dem
    Drift-Vorfall, mit veränderten Gewichten zu ziehen — der Strom bleibt
    legal, nur die Mischung kippt."""
    tabelle = (kette or profil.ketten)[aktuell]
    gesamt = sum(g for _, g in tabelle)
    los = rng.uniform(0.0, gesamt)
    for folge, gewicht in tabelle:
        los -= gewicht
        if los <= 0.0:
            return folge
    return tabelle[-1][0]


def naechstes_detail(
    profil: AgentProfil, rng: random.Random, aktion: str
) -> str:
    """Ein normales Ziel für die Aktion — gewichtet, aus dem Profil."""
    tabelle = profil.details[aktion]
    gesamt = sum(g for _, g in tabelle)
    los = rng.uniform(0.0, gesamt)
    for ziel, gewicht in tabelle:
        los -= gewicht
        if los <= 0.0:
            return ziel
    return tabelle[-1][0]


def profile() -> List[AgentProfil]:
    """Die fünf normalen Agenten des Messstands — verschiedene Rhythmen,
    Tageszeiten, Wortschätze (Stufe 1, Punkt 2 des Tickets)."""
    lesen = (("src/engine.py", 3.0), ("docs/SPEC.md", 2.0), ("issues/1", 1.5),
             ("logs/waechter.log", 2.0), ("src/spur.py", 1.5))
    suchen = (("symbol:observe", 2.0), ("text:threshold", 2.0),
              ("datei:tests", 1.5), ("symbol:score", 1.5), ("text:novelty", 1.0))
    planen = (("sprint-7", 2.0), ("bugfix-12", 1.5), ("refactor-kern", 1.5),
              ("messstand", 2.0), ("release", 1.0))
    editieren = (("src/engine.py", 3.0), ("src/thalamus.py", 2.0),
                 ("tests/test_core.py", 2.5), ("src/watch.py", 2.0),
                 ("docs/USAGE.md", 1.0))
    testen = (("tests/test_core.py", 2.5), ("suite-voll", 2.0),
              ("tests/test_watch.py", 2.0), ("rauch-test", 1.0))
    committen = (("main", 3.0), ("klaer-font", 1.5), ("messstand-zweig", 1.5),
                 ("bugfix-12", 1.0))
    pushen = (("origin/main", 2.5), ("origin/messstand-zweig", 1.5))
    kommentieren = (("issue-1", 2.0), ("issue-14", 1.5), ("mr-6", 1.5),
                    ("issue-3", 1.0))
    dokumentieren = (("docs/USAGE.md", 2.0), ("docs/API.md", 1.5),
                     ("CHANGELOG.md", 1.5), ("docs/MESSSTAND.md", 1.0))
    details: Dict[str, Tuple[Tuple[str, float], ...]] = {
        "lesen": lesen, "suchen": suchen, "planen": planen,
        "editieren": editieren, "testen": testen, "committen": committen,
        "pushen": pushen, "kommentieren": kommentieren,
        "dokumentieren": dokumentieren,
    }

    def detail_slice(aktionen) -> Dict[str, Tuple[Tuple[str, float], ...]]:
        """Das gemeinsame Detail-Vokabular, zugeschnitten auf die
        Aktionen des Profils — jedes Profil kennt nur seine eigenen."""
        return {a: details[a] for a in aktionen}

    eifrig_aktionen = ("lesen", "suchen", "planen", "editieren", "testen",
                       "committen", "pushen", "kommentieren")
    eifrig = AgentProfil(
        name="eifrig",
        rolle="Commit-Schmied, 07–19 Uhr, enger Takt",
        aktionen=eifrig_aktionen,
        ketten={
            "lesen": (("suchen", 0.35), ("planen", 0.25), ("editieren", 0.20),
                      ("kommentieren", 0.10), ("testen", 0.10)),
            "suchen": (("lesen", 0.30), ("planen", 0.30), ("editieren", 0.25),
                       ("kommentieren", 0.15)),
            "planen": (("editieren", 0.45), ("suchen", 0.20), ("lesen", 0.15),
                       ("kommentieren", 0.10), ("testen", 0.10)),
            "editieren": (("testen", 0.40), ("editieren", 0.20),
                          ("committen", 0.20), ("planen", 0.10),
                          ("lesen", 0.10)),
            "testen": (("committen", 0.35), ("editieren", 0.35),
                       ("kommentieren", 0.10), ("pushen", 0.10),
                       ("suchen", 0.10)),
            "committen": (("pushen", 0.50), ("testen", 0.20),
                          ("kommentieren", 0.15), ("editieren", 0.15)),
            "pushen": (("kommentieren", 0.30), ("lesen", 0.30),
                       ("planen", 0.20), ("suchen", 0.20)),
            "kommentieren": (("lesen", 0.30), ("planen", 0.25),
                             ("editieren", 0.25), ("suchen", 0.20)),
        },
        start="lesen",
        luecken_s=(30.0, 120.0),
        aktiv=((7.0, 19.0),),
        pausen=((12.0, 12.75),),
        details=detail_slice(eifrig_aktionen),
    )

    ruhig_aktionen = ("lesen", "planen", "editieren", "testen", "kommentieren")
    ruhig = AgentProfil(
        name="ruhig",
        rolle="Nachlässiger Maintainer, 08–22 Uhr, weiter Takt",
        aktionen=ruhig_aktionen,
        ketten={
            "lesen": (("planen", 0.35), ("editieren", 0.30),
                      ("kommentieren", 0.20), ("testen", 0.15)),
            "planen": (("editieren", 0.50), ("lesen", 0.25),
                       ("kommentieren", 0.15), ("testen", 0.10)),
            "editieren": (("testen", 0.40), ("editieren", 0.15),
                          ("kommentieren", 0.25), ("lesen", 0.20)),
            "testen": (("kommentieren", 0.35), ("editieren", 0.35),
                       ("lesen", 0.30)),
            "kommentieren": (("lesen", 0.40), ("planen", 0.35),
                             ("editieren", 0.25)),
        },
        start="lesen",
        luecken_s=(60.0, 300.0),
        aktiv=((8.0, 22.0),),
        pausen=((18.5, 19.25),),
        details=detail_slice(ruhig_aktionen),
    )

    nacht_aktionen = ("lesen", "suchen", "editieren", "testen", "committen",
                      "pushen")
    nachtschicht = AgentProfil(
        name="nachtschicht",
        rolle="Nacht-Wächter, 21–05 Uhr, über Mitternacht",
        aktionen=nacht_aktionen,
        ketten={
            "lesen": (("suchen", 0.30), ("editieren", 0.35), ("testen", 0.20),
                      ("committen", 0.15)),
            "suchen": (("lesen", 0.30), ("editieren", 0.40), ("testen", 0.30)),
            "editieren": (("testen", 0.45), ("committen", 0.25),
                          ("lesen", 0.15), ("suchen", 0.15)),
            "testen": (("committen", 0.40), ("testen", 0.10),
                       ("editieren", 0.30), ("pushen", 0.20)),
            "committen": (("pushen", 0.55), ("testen", 0.25),
                          ("lesen", 0.20)),
            "pushen": (("lesen", 0.45), ("suchen", 0.30), ("editieren", 0.25)),
        },
        start="lesen",
        luecken_s=(45.0, 180.0),
        aktiv=((21.0, 5.0),),
        pausen=((1.0, 1.5),),
        details=detail_slice(nacht_aktionen),
    )

    sprint_aktionen = ("lesen", "suchen", "planen", "editieren", "testen",
                       "committen", "pushen", "kommentieren", "dokumentieren")
    sprint = AgentProfil(
        name="sprint",
        rolle="Sprint-Arbeitstier, 09–18 Uhr, zwei Pausen, kein Selbstgang",
        aktionen=sprint_aktionen,
        ketten={
            "lesen": (("suchen", 0.25), ("planen", 0.25), ("editieren", 0.25),
                      ("dokumentieren", 0.15), ("kommentieren", 0.10)),
            "suchen": (("lesen", 0.25), ("planen", 0.30), ("editieren", 0.25),
                       ("kommentieren", 0.20)),
            "planen": (("editieren", 0.40), ("dokumentieren", 0.20),
                       ("lesen", 0.20), ("suchen", 0.20)),
            "editieren": (("testen", 0.45), ("committen", 0.25),
                          ("dokumentieren", 0.15), ("lesen", 0.15)),
            "testen": (("committen", 0.30), ("editieren", 0.30),
                       ("dokumentieren", 0.15), ("pushen", 0.15),
                       ("kommentieren", 0.10)),
            "committen": (("pushen", 0.50), ("testen", 0.20),
                          ("dokumentieren", 0.15), ("kommentieren", 0.15)),
            "pushen": (("kommentieren", 0.30), ("lesen", 0.25),
                       ("planen", 0.25), ("dokumentieren", 0.20)),
            "kommentieren": (("lesen", 0.30), ("planen", 0.25),
                             ("editieren", 0.25), ("suchen", 0.20)),
            "dokumentieren": (("testen", 0.25), ("lesen", 0.25),
                              ("planen", 0.25), ("kommentieren", 0.25)),
        },
        start="lesen",
        luecken_s=(20.0, 90.0),
        aktiv=((9.0, 18.0),),
        pausen=((10.5, 11.0), (12.25, 12.75)),
        details=detail_slice(sprint_aktionen),
    )

    schreiber_aktionen = ("lesen", "planen", "dokumentieren", "kommentieren",
                          "testen")
    schreiber = AgentProfil(
        name="schreiber",
        rolle="Doku-Schreiber, 07–16 Uhr, sehr weiter Takt",
        aktionen=schreiber_aktionen,
        ketten={
            "lesen": (("planen", 0.35), ("dokumentieren", 0.35),
                      ("kommentieren", 0.20), ("testen", 0.10)),
            "planen": (("dokumentieren", 0.50), ("lesen", 0.25),
                       ("testen", 0.25)),
            "dokumentieren": (("dokumentieren", 0.25), ("kommentieren", 0.25),
                              ("lesen", 0.25), ("testen", 0.25)),
            "kommentieren": (("dokumentieren", 0.40), ("lesen", 0.35),
                             ("planen", 0.25)),
            "testen": (("dokumentieren", 0.40), ("kommentieren", 0.35),
                       ("lesen", 0.25)),
        },
        start="lesen",
        luecken_s=(90.0, 240.0),
        aktiv=((7.0, 16.0),),
        pausen=((11.75, 12.5),),
        details=detail_slice(schreiber_aktionen),
    )

    liste = [eifrig, ruhig, nachtschicht, sprint, schreiber]
    for p in liste:
        pruefe_profil(p)
    return liste


def loopfreie_aktionen(profil: AgentProfil) -> List[str]:
    """Aktionen ohne Selbstübergang im NORMALen Profil — nur die sind
    Kandidaten für den Schleifen-Vorfall; eine Schleife über eine Aktion,
    die sich im Normalen manchmal folgt, wäre kein Profil-Fremdes."""
    frei = []
    for aktion in profil.aktionen:
        self_gewicht = sum(g for f, g in profil.ketten[aktion]
                           if f == aktion)
        if self_gewicht == 0.0:
            frei.append(aktion)
    return frei


__all__ = [
    "BASIS_DATUM",
    "ZEITZONE",
    "MIN_GEWICHT",
    "AgentProfil",
    "pruefe_profil",
    "in_fenster",
    "akzeptabel",
    "springe_vor",
    "naechste_luecke",
    "naechste_aktion",
    "naechstes_detail",
    "profile",
    "loopfreie_aktionen",
]
