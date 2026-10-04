"""Die acht Vorfallarten und ihr Einbau (Stufe 1, Punkt 2 des Tickets).

Mindestens acht Arten, wie im Ticket gefordert — jede schiebt
Profil-Fremdes in einen sonst normalen Strom:

==============  ===================================================
Art             Der Vorfall
==============  ===================================================
neue-aktion     eine Aktion, die es im Profil nicht gibt
reihenfolge     bekannte Aktion an einer unmöglichen Stelle (Übergang
                mit Gewicht 0 in der normalen Kette)
schleife        20× dieselbe Aktion hintereinander (5–15 s)
schwall         30 Aktionen in ~15 s (0,2–0,7 s)
funkstille      3–6 h nichts, mitten im Aktivfenster
ungewohnte-     Arbeit zu einer Uhrzeit, die das Profil nie sieht
uhrzeit         (erst NACH einer etablierten Tagesform)
langsame-       die Aktionsmischung kippt über hunderte Ereignisse —
drift           alle Übergänge bleiben legal
ungewohntes-    bekannte Aktion mit Ziel aus einem fremden
ziel           Detail-Wortschatz
==============  ===================================================

Bau-Regeln, damit die Messung fair bleibt:

* **Jeder Vorfall räumt hinter sich auf.** Der letzte Ereigniszustand
  führt zurück in die normale Kette (bei ``neue-aktion`` mit einem
  markierten Rückkehr-Ereignis), damit die Rückkehr kein unmarkiertes
  Fremdmuster hinterlässt, das als Fehlalarm zählen würde.
* **Detektoren sehen nur den Blick ohne Marke** (:func:`benchmarks.
  spur.waechterblick`); die Vorfallfenster sind genau die Ereignisse
  mit ``marke != normal``.
* **Gleiche Saat, gleiche Spur.** Alles zieht aus EINEM rng je
  (Saat, Profil) — dieselbe Saat baut dieselbe Spur, byte-identisch.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .agenten import (
    AgentProfil,
    BASIS_DATUM,
    ZEITZONE,
    akzeptabel,
    loopfreie_aktionen,
    naechste_aktion,
    naechstes_detail,
    naechste_luecke,
    springe_vor,
)
from .spur import Ereignis, Kopf, Spur, MARKE_NORMAL

#: Die acht Vorfallarten des Tickets, fest und in dieser Ordnung.
VORFALLSARTEN = (
    "neue-aktion",
    "reihenfolge",
    "schleife",
    "schwall",
    "funkstille",
    "ungewohnte-uhrzeit",
    "langsame-drift",
    "ungewohntes-ziel",
)

#: Aktionen, die in KEINEM normalen Profil vorkommen (Stufe-1-Bedingung:
#: nie mit einem Profilvokabular kollidieren — pruefe das in den Tests).
FREMD_AKTIONEN = (
    "rollback",
    "zugriff-erteilen",
    "daten-export",
    "nachtschleife-starten",
    "konto-pruefung",
)

#: Fremde Ziele je bekannter Aktion — der Vorfall 'ungewohntes-ziel'
#: zieht daraus. Der Wächter sieht Details strukturell nicht (die
#: Token-Granularität ist die Aktion); diese Zeile ist die ehrliche
#: Blindstellen-Niederlage der Tafel.
FREMD_ZIELE: Dict[str, Tuple[str, ...]] = {
    "lesen": ("/root/privat", "/etc/schatten", "fremd-repo"),
    "suchen": ("kundendaten", "passwoerter", "fremde-infrastruktur"),
    "planen": ("urlaub-umgehen", "ohne-freigabe"),
    "editieren": ("/etc/schatten", "produktion", "fremd-repo"),
    "testen": ("produktion", "kunden-datenbank"),
    "committen": ("ohne-pruefung", "fremd-identitaet"),
    "pushen": ("extern-remote", "fremd-remote"),
    "kommentieren": ("fremdes-ticket", "externes-forum"),
    "dokumentieren": ("fremd-repo", "externes-wiki"),
}
FREMD_ZIEL_FALLBACK = "fremd-ziel"


def marke_fuer(art: str, nr: int) -> str:
    """Das Diagnose-Etikett eines Vorfallereignisses: Art und Nummer."""
    return f"{art}/{nr}"


# ---------------------------------------------------------------------------
# Die Vorfall-Bauer — jeder liefert (Ereignisse, neue letzte Aktion,
# neue Uhr) und überlässt die Marke dem Einbau.
# ---------------------------------------------------------------------------

Rueckgabe = Tuple[List[Ereignis], str, datetime, Optional[str]]


def _vorfall_neue_aktion(
    profil: AgentProfil, rng: random.Random, start: datetime,
    letzte: str, fenster_bis: datetime,
) -> Rueckgabe:
    fremd = rng.choice(FREMD_AKTIONEN)
    if fremd in profil.aktionen:
        raise ValueError(f"Fremdaktion {fremd!r} kollidiert mit Profil "
                         f"{profil.name} — die Fremdliste ist kaputt.")
    anzahl = rng.randint(4, 8)
    ereignisse: List[Ereignis] = []
    ts = start
    for _ in range(anzahl):
        ereignisse.append(Ereignis(ts=ts, aktion=fremd, detail=None))
        ts = ts + timedelta(seconds=rng.uniform(20.0, 40.0))
    if ts >= fenster_bis:
        raise ValueError("Vorfall 'neue Aktion' läuft aus dem Fenster — "
                         "die Slot-Planung hat zu knapp reserviert.")
    # Markierte Rückkehr: das fremde Vokabular hat keinen Kettenschluss,
    # also führt ein explizites Ereignis zur Startaktion zurück.
    heim = profil.start
    ereignisse.append(Ereignis(ts=ts, aktion=heim,
                               detail=naechstes_detail(profil, rng, heim)))
    return ereignisse, heim, ts, None


def _vorfall_reihenfolge(
    profil: AgentProfil, rng: random.Random, start: datetime,
    letzte: str, fenster_bis: datetime,
) -> Rueckgabe:
    moeglich = [a for a in profil.aktionen
                if a not in {f for f, _ in profil.ketten[letzte]}]
    if not moeglich:
        raise ValueError(f"Profil {profil.name}: kein unmöglicher Übergang "
                         f"von {letzte!r} — die Kette ist zu vollständig.")
    ziel = rng.choice(moeglich)
    ereignis = Ereignis(
        ts=start, aktion=ziel, detail=naechstes_detail(profil, rng, ziel),
    )
    return [ereignis], ziel, start, None


def _vorfall_schleife(
    profil: AgentProfil, rng: random.Random, start: datetime,
    letzte: str, fenster_bis: datetime,
) -> Rueckgabe:
    frei = loopfreie_aktionen(profil)
    if not frei:
        raise ValueError(f"Profil {profil.name}: keine loopfreie Aktion — "
                         "eine Schleife wäre dort normal.")
    aktion = rng.choice(frei)
    anzahl = 20
    ereignisse: List[Ereignis] = []
    ts = start
    for _ in range(anzahl):
        ereignisse.append(Ereignis(
            ts=ts, aktion=aktion, detail=naechstes_detail(profil, rng, aktion),
        ))
        ts = ts + timedelta(seconds=rng.uniform(5.0, 15.0))
    return ereignisse, aktion, ts, None


def _vorfall_schwall(
    profil: AgentProfil, rng: random.Random, start: datetime,
    letzte: str, fenster_bis: datetime,
) -> Rueckgabe:
    anzahl = 30
    ereignisse: List[Ereignis] = []
    ts = start
    aktuell = letzte
    for _ in range(anzahl):
        aktuell = naechste_aktion(profil, rng, aktuell)
        ereignisse.append(Ereignis(
            ts=ts, aktion=aktuell,
            detail=naechstes_detail(profil, rng, aktuell),
        ))
        ts = ts + timedelta(seconds=rng.uniform(0.2, 0.7))
    return ereignisse, aktuell, ts, None


def _vorfall_funkstille(
    profil: AgentProfil, rng: random.Random, start: datetime,
    letzte: str, fenster_bis: datetime,
) -> Rueckgabe:
    """Keine Ereignisse — nur Stille. Die Marke reist auf das erste
    Ereignis NACH der Stille (das ist das Vorfallfenster). Die Dauer
    steckt im Slot (fenster_bis = start + Dauer) und wurde in der
    Planung gebucht."""
    dauer_s = (fenster_bis - start).total_seconds()
    if dauer_s < 3.0 * 3600.0:
        raise ValueError("Vorfall 'Funkstille' kürzer als 3 h — die "
                         "Slot-Planung hat das Versprechen gebrochen.")
    return [], letzte, fenster_bis, "funkstille"


def _vorfall_ungewohnte_uhrzeit(
    profil: AgentProfil, rng: random.Random, start: datetime,
    letzte: str, fenster_bis: datetime,
) -> Rueckgabe:
    """Ein normaler Block zu einer nie gesehenen Stunde. Bewusst OHNE
    akzeptabel()-Sprung: die falsche Uhrzeit IST der Vorfall."""
    anzahl = rng.randint(6, 12)
    ereignisse: List[Ereignis] = []
    ts = start
    aktuell = letzte
    for _ in range(anzahl):
        aktuell = naechste_aktion(profil, rng, aktuell)
        ereignisse.append(Ereignis(
            ts=ts, aktion=aktuell,
            detail=naechstes_detail(profil, rng, aktuell),
        ))
        ts = ts + timedelta(seconds=naechste_luecke(profil, rng))
    return ereignisse, aktuell, ts, None


def _vorfall_langsame_drift(
    profil: AgentProfil, rng: random.Random, start: datetime,
    letzte: str, fenster_bis: datetime,
) -> Rueckgabe:
    """Die Aktionsmischung kippt langsam — jede Zeile bleibt ein legaler
    Übergang, nur die Gewichte wandern. Kein Detektor des Tickets hat
    ein Frequenzfenster je Aktion; die Tafel erwartet hier ehrlich
    Niederlagen und hält die Zeile trotzdem fest."""
    eingang = {a: 0.0 for a in profil.aktionen}
    for ausgaenge in profil.ketten.values():
        for folge, gewicht in ausgaenge:
            eingang[folge] += gewicht
    steigend = min(profil.aktionen, key=lambda a: eingang[a])
    fallend = max(profil.aktionen, key=lambda a: eingang[a])
    if steigend == fallend:
        raise ValueError(f"Profil {profil.name}: Drift braucht zwei "
                         "unterschiedliche Aktionen.")
    faktor = 12.0
    grenze = fenster_bis - timedelta(minutes=15)

    ereignisse: List[Ereignis] = []
    ts = start
    aktuell = letzte
    for i in range(rng.randint(250, 350)):
        anteil = (i + 1) / 350.0
        kette: Dict[str, Tuple[Tuple[str, float], ...]] = {}
        for quelle, ausgaenge in profil.ketten.items():
            neu: List[Tuple[str, float]] = []
            for folge, gewicht in ausgaenge:
                g = gewicht
                if folge == steigend:
                    g *= 1.0 + (faktor - 1.0) * anteil
                elif folge == fallend:
                    g /= 1.0 + (faktor - 1.0) * anteil
                neu.append((folge, g))
            kette[quelle] = tuple(neu)
        aktuell = naechste_aktion(profil, rng, aktuell, kette=kette)
        # Pausen bleiben Pausen, auch im Drift; an der Grenze endet der
        # Drift ehrlich, statt über die Buchung hinauszuwandern.
        if ts >= grenze:
            break
        folge_ts = ts + timedelta(seconds=naechste_luecke(profil, rng))
        if not akzeptabel(folge_ts, profil):
            folge_ts = springe_vor(folge_ts, profil)
        ereignisse.append(Ereignis(
            ts=ts, aktion=aktuell,
            detail=naechstes_detail(profil, rng, aktuell),
        ))
        ts = folge_ts
    if len(ereignisse) < 80:
        raise ValueError(f"Profil {profil.name}: Drift-Fenster zu klein "
                         f"({len(ereignisse)} Ereignisse) — Slot-Planung "
                         "prüfen.")
    if ts >= fenster_bis:
        ts = fenster_bis
    return ereignisse, aktuell, ts, None


def _vorfall_ungewohntes_ziel(
    profil: AgentProfil, rng: random.Random, start: datetime,
    letzte: str, fenster_bis: datetime,
) -> Rueckgabe:
    anzahl = rng.randint(5, 10)
    ereignisse: List[Ereignis] = []
    ts = start
    aktuell = letzte
    for _ in range(anzahl):
        aktuell = naechste_aktion(profil, rng, aktuell)
        ziel = rng.choice(FREMD_ZIELE.get(aktuell, (FREMD_ZIEL_FALLBACK,)))
        ereignisse.append(Ereignis(ts=ts, aktion=aktuell, detail=ziel))
        ts = ts + timedelta(seconds=naechste_luecke(profil, rng))
    return ereignisse, aktuell, ts, None


_BAUER = {
    "neue-aktion": _vorfall_neue_aktion,
    "reihenfolge": _vorfall_reihenfolge,
    "schleife": _vorfall_schleife,
    "schwall": _vorfall_schwall,
    "funkstille": _vorfall_funkstille,
    "ungewohnte-uhrzeit": _vorfall_ungewohnte_uhrzeit,
    "langsame-drift": _vorfall_langsame_drift,
    "ungewohntes-ziel": _vorfall_ungewohntes_ziel,
}


# ---------------------------------------------------------------------------
# Slot-Planung — jeder Vorfall bekommt einen freien Platz, keiner
# überlappt, alle liegen nach einer vollen Tagesform.
# ---------------------------------------------------------------------------

_RAND = timedelta(minutes=30)
_ABSTAND = timedelta(minutes=15)


def _fenster_segmente(
    profil: AgentProfil, start: datetime, ende: datetime,
) -> List[Tuple[datetime, datetime]]:
    """Konkrete Aktivfenster (Start, Ende) im Simulationszeitraum."""
    segmente: List[Tuple[datetime, datetime]] = []
    tag = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while tag < ende:
        for a, b in profil.aktiv:
            von = tag.replace(hour=int(a), minute=int((a % 1) * 60))
            bis = (tag if a < b else tag + timedelta(days=1)).replace(
                hour=int(b), minute=int((b % 1) * 60))
            von = max(von, start)
            bis = min(bis, ende)
            if bis > von:
                segmente.append((von, bis))
        tag = tag + timedelta(days=1)
    return segmente


def _freie_spanne(
    segment: Tuple[datetime, datetime], profil: AgentProfil,
    buchungen: List[Tuple[datetime, datetime]], dauer: timedelta,
    pausen_schneiden: bool = True,
) -> List[Tuple[datetime, datetime]]:
    """Freie Zeitspannen im Segment (Buchungen mit Rand, optional auch
    Pausen, herausgeschnitten), lang genug für ``dauer``. Der Drift
    schneidet die Pausen NICHT heraus — sein Bauer überspringt sie
    ohnehin korrekt, und die Pause darf mitten im Drift liegen."""
    von, bis = segment
    # Segmentränder freihalten: Der normale Strom springt an die
    # Fensteranfänge (Fensterstart + 1 Minute) — ein Slot genau am
    # Rand würde hinter den Cursor fallen und die Slot-Ordnung kippen.
    von = von + _RAND
    bis = bis - _RAND
    loecher: List[Tuple[datetime, datetime]] = []
    if pausen_schneiden:
        for p_a, p_b in profil.pausen:
            tag = von.replace(hour=0, minute=0, second=0, microsecond=0)
            while tag < bis:
                loecher.append((
                    tag + timedelta(hours=p_a) - _RAND,
                    tag + timedelta(hours=p_b) + _RAND,
                ))
                tag = tag + timedelta(days=1)
    for b_a, b_b in buchungen:
        loecher.append((b_a - _ABSTAND, b_b + _ABSTAND))
    spannen: List[Tuple[datetime, datetime]] = [(von, bis)]
    for l_a, l_b in loecher:
        neu: List[Tuple[datetime, datetime]] = []
        for s_a, s_b in spannen:
            if l_b <= s_a or l_a >= s_b:
                neu.append((s_a, s_b))
                continue
            if s_a < l_a:
                neu.append((s_a, min(l_a, s_b)))
            if s_b > l_b:
                neu.append((max(l_b, s_a), s_b))
        spannen = [(a, b) for a, b in neu if b > a]
    return [(a, b) for a, b in spannen if b - a >= dauer]


def _waehle_slots(
    profil: AgentProfil, rng: random.Random,
    segmente: List[Tuple[datetime, datetime]],
) -> Dict[str, dict]:
    """Plant jeden Vorfall einen freien Platz. Erst die großen
    (Funkstille, Drift, ungewohnte Uhrzeit), dann die fünf kleinen.
    Alles nach mindestens einem vollen Aktivfenster (Warmwachsen der
    Profile), die ungewohnte Uhrzeit erst nach einer ETABLIEURTEN
    Tagesform — eine falsche Stunde zählt nur, wenn die richtigen
    schon sitzen."""
    buchungen: List[Tuple[datetime, datetime]] = []
    slots: Dict[str, dict] = {}
    _RAND_min = timedelta(minutes=15)
    _gross = timedelta(hours=3, minutes=15)  # Reservierung Funkstille
    _drift = timedelta(hours=2, minutes=30)
    _klein = timedelta(minutes=60)

    if len(segmente) < 3:
        raise ValueError("Der Messstand braucht mindestens drei "
                         "Aktivfenster — zwei Tage Simulation und die "
                         "ungewohnte Uhrzeit nach etablierter Tagesform "
                         "passen sonst nicht in eine Spur.")

    # 1) Ungewohnte Uhrzeit: Mitte des ZWEITEN Off-Gaps — erst nach
    #    zwei Fenstern ist die Tagesform etabliert (zwei Kalendertage
    #    gesehen) und eine falsche Stunde ist wirklich falsch; im
    #    ersten Off-Gap wäre sie für ein Stundenprofil nicht von der
    #    ersten Nacht zu unterscheiden. Segment 0 bleibt ganz normal.
    for i in range(2, len(segmente)):
        loch_start, loch_ende = segmente[i - 1][1], segmente[i][0]
        if loch_ende - loch_start >= timedelta(hours=4):
            mitte = loch_start + (loch_ende - loch_start) / 2
            start = mitte - _RAND_min + timedelta(
                minutes=rng.uniform(0.0, 60.0))
            slots["ungewohnte-uhrzeit"] = {
                "start": start, "fenster_bis": start + timedelta(hours=2),
            }
            buchungen.append((start - _RAND, start + _gross))
            break
    if "ungewohnte-uhrzeit" not in slots:
        raise ValueError(f"Profil {profil.name}: kein Off-Gap für die "
                         "ungewohnte Uhrzeit gefunden.")

    # 2) Funkstille: ein späteres Segment mit mindestens 3,25 h Raum.
    faehig = [seg for seg in segmente[1:]
              if seg[1] - seg[0] >= _gross + timedelta(hours=1)]
    if not faehig:
        raise ValueError(f"Profil {profil.name}: kein Segment für die "
                         "Funkstille.")
    funkstille_seg = rng.choice(faehig)
    seg = funkstille_seg
    spannen = _freie_spanne(seg, profil, buchungen, _gross,
                            pausen_schneiden=False)
    if not spannen:
        raise ValueError(f"Profil {profil.name}: kein freier Span für "
                         "die Funkstille.")
    a, b = rng.choice(spannen)
    start = a + rng.uniform(0.0, (b - a - _gross).total_seconds()) * \
        timedelta(seconds=1)
    # Die Dauer wird HIER gewürfelt und exakt gebucht — nicht der
    # schlimmste Fall; der Rest des Fensters bleibt für die anderen.
    dauer = rng.uniform(3.0 * 3600.0,
                        min(5.0 * 3600.0,
                            (b - timedelta(minutes=15) - start)
                            .total_seconds()))
    dauer = timedelta(seconds=dauer)
    slots["funkstille"] = {"start": start, "fenster_bis": start + dauer}
    buchungen.append((start, start + dauer))

    # 3) Drift: der größte freie Rest, auf höchstens 6,5 h begrenzt.
    #    Der Bedarf richtet sich nach dem Profil-Takt: 120 Drift-
    #    Ereignisse bei Ø-Abstand plus Spielraum — bei langsamen
    #    Profilen (ruhig: Ø 180 s) sind das ~6,5 h, ein kürzeres
    #    Fenster wäre zu flach, ein längeres würde die kleinen
    #    Vorfälle verdrängen.
    mittel_luecke = sum(profil.luecken_s) / 2.0
    bedarf = max(_drift, timedelta(seconds=80 * mittel_luecke)
                 + timedelta(minutes=75))
    if bedarf > timedelta(hours=6.5):
        raise ValueError(f"Profil {profil.name}: der Drift-Bedarf "
                         f"({bedarf}) sprengt die 6,5-h-Grenze.")
    best_a, best_b = None, None
    andere = [s for s in segmente[1:] if s != funkstille_seg]
    for seg in (andere or segmente[1:]):
        for a, b in _freie_spanne(seg, profil, buchungen, bedarf,
                                    pausen_schneiden=False):
            if best_b is None or b - a > best_b - best_a:
                best_a, best_b = a, b
    if best_b is None:
        raise ValueError(f"Profil {profil.name}: kein Span für den Drift.")
    b_drift = min(best_a + bedarf, best_a + timedelta(hours=6, minutes=30),
                  best_b)
    start = best_a + rng.uniform(0.0, max(0.0, (b_drift - best_a - bedarf)
                                           .total_seconds())) * \
        timedelta(seconds=1)
    slots["langsame-drift"] = {"start": start, "fenster_bis": b_drift}
    buchungen.append((best_a, b_drift))

    # 4) Die fünf kleinen, in gewürfelter Ordnung, jeder in den
    #    ZEITLICH größten freien Rest (gierig — keiner verhungert).
    #    'reihenfolge' zuletzt — es profitiert vom größten Warmwachsen
    #    der Vorgänger-Zähler. Buchung je Bau-Bedarf: nur
    #    'ungewohntes-ziel' zieht lange (bis 50 min), die anderen sind
    #    in Minuten fertig.
    kleine = ["neue-aktion", "schwall", "schleife", "ungewohntes-ziel",
              "reihenfolge"]
    rng.shuffle(kleine)
    kleine.remove("reihenfolge")
    kleine.append("reihenfolge")
    for art in kleine:
        dauer = (timedelta(minutes=60) if art == "ungewohntes-ziel"
                 else timedelta(minutes=15))
        best_a, best_b = None, None
        for seg in segmente[1:]:
            for a, b in _freie_spanne(seg, profil, buchungen, dauer):
                if best_b is None or b - a > best_b - best_a:
                    best_a, best_b = a, b
        if best_b is None:
            raise ValueError(f"Profil {profil.name}: kein freier Platz "
                             f"für den Vorfall {art!r}.")
        start = best_a + rng.uniform(
            0.0, (best_b - best_a - dauer).total_seconds()) * \
            timedelta(seconds=1)
        slots[art] = {"start": start, "fenster_bis": best_b}
        buchungen.append((start, start + dauer))
    return slots


# ---------------------------------------------------------------------------
# Der Einbau: eine komplette Spur mit Vorfällen
# ---------------------------------------------------------------------------


def spur_mit_vorfaellen(
    profil: AgentProfil, saat: int, tage: int = 3,
) -> Spur:
    """Erzeugt die Spur EINES normalen Agenten mit je einem Vorfall
    jeder Art. Gleiche Saat + gleiches Profil = byte-identische Spur."""
    rng = random.Random(f"{saat}-{profil.name}")
    start = BASIS_DATUM
    kalender_ende = start + timedelta(days=tage)
    # Fenster, die über den Kalenderstrich hinauslaufen (Nachtschicht:
    # 21–05), werden zu Ende geführt — abgeschnittene Fenster wären
    # zu klein für die Vorfall-Planung.
    segmente = _fenster_segmente(profil, start, kalender_ende
                                 + timedelta(days=1))
    segmente = [(a, b) for a, b in segmente if a < kalender_ende]
    ende = max(b for _, b in segmente)
    slots = _waehle_slots(profil, rng, segmente)

    ereignisse: List[Ereignis] = []
    cursor = start
    letzte = profil.start
    wartende_marke: Optional[str] = None

    geplant = sorted(slots.items(), key=lambda paar: paar[1]["start"])

    def normal_bis(grenze: datetime) -> None:
        """Normale Ereignisse bis ``grenze`` (ohne sie zu überschreiten)."""
        nonlocal cursor, letzte, wartende_marke
        while True:
            ts = cursor + timedelta(seconds=naechste_luecke(profil, rng))
            if ts >= grenze:
                # Der Cursor bleibt UNTER der Grenze — der nächste
                # gezogene Abstand wird neu gewürfelt. Spränge der
                # Cursor (Fenster-/Pausen-Sprünge) über die Grenze
                # hinaus, könnte er hinter einem späteren Slot landen
                # und die Slot-Planung kippen.
                return
            if not akzeptabel(ts, profil):
                # Fenster-/Pausen-Sprünge nie HINTER die Slot-Grenze
                # klettern lassen — sonst überholt der Strom den Slot.
                cursor = min(springe_vor(ts, profil),
                             grenze - timedelta(seconds=1))
                continue
            aktion = naechste_aktion(profil, rng, letzte)
            marke = wartende_marke
            wartende_marke = None
            ereignisse.append(Ereignis(
                ts=ts, aktion=aktion,
                detail=naechstes_detail(profil, rng, aktion),
                marke=marke if marke is not None else MARKE_NORMAL,
            ))
            letzte = aktion
            cursor = ts

    for art, plan in geplant:
        slot_start = plan["start"]
        if slot_start <= cursor:
            raise ValueError(f"Slot für {art!r} liegt vor dem Strom-Cursor "
                             "— die Slot-Planung hat überlappt.")
        normal_bis(slot_start)
        nr = VORFALLSARTEN.index(art) + 1
        ereignisse_vorfall, letzte_neu, cursor_neu, spater_marke = \
            _BAUER[art](profil, rng, slot_start, letzte,
                        plan["fenster_bis"])
        for e in ereignisse_vorfall:
            ereignisse.append(Ereignis(
                ts=e.ts, aktion=e.aktion, detail=e.detail,
                marke=marke_fuer(art, nr),
            ))
        letzte = letzte_neu
        cursor = max(cursor_neu, cursor)
        if spater_marke is not None:
            wartende_marke = marke_fuer(spater_marke, nr)

    normal_bis(ende)

    kopf = Kopf(
        agent=profil.name,
        rolle=profil.rolle,
        saat=saat,
        zeitzone=ZEITZONE,
        zeitraum=(start.isoformat(), ende.isoformat()),
    )
    geordnet = sorted(ereignisse, key=lambda e: e.ts)
    for vorher, danach in zip(geordnet, geordnet[1:]):
        if danach.ts < vorher.ts:
            raise ValueError("Spur ist nach dem Sortieren noch unsortiert "
                             "— Zeitfehler im Einbau.")
    return Spur(kopf=kopf, ereignisse=geordnet)


__all__ = [
    "VORFALLSARTEN",
    "FREMD_AKTIONEN",
    "FREMD_ZIELE",
    "FREMD_ZIEL_FALLBACK",
    "marke_fuer",
    "spur_mit_vorfaellen",
]
