"""Characterisation tests for the Messstand (Stufe 1, ticket #1).

These tests pin the STRUCTURAL results of the measurement bench — the
rows that follow from build rules, not from tuning: novelty sees new
actions, nobody sees details, B2's own count windows see rate, silence
and hour violations. They deliberately record defeats where they are
structural (``ungewohntes-ziel`` is invisible to every runner by
design); if a future change makes them pass, the test should be
updated together with the table, not silently deleted.

Generator-based tests run one profile on one fixed seed (7) — small,
deterministic, and strictly below the sealed-seed line (saaten < 1000).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from benchmarks.agenten import AgentProfil, profile
from benchmarks.gegner import B0, B1, B2
from benchmarks.kandidaten import kandidaten
from benchmarks.messstand import laufe_messstand
from benchmarks.spur import (
    SpurFehler,
    lies_spur,
    lies_ts,
    schreibe_spur,
    waechterblick,
    MARKE_NORMAL,
)
from benchmarks.vorfaelle import spur_mit_vorfaellen

SAAT = 7  # Entwicklung nur auf Saaten < 1000


def _profil(name: str) -> AgentProfil:
    return next(p for p in profile() if p.name == name)


# ---------------------------------------------------------------------------
# Spurformat
# ---------------------------------------------------------------------------


def test_spur_rundreise_bewahrt_jede_zeile(tmp_path):
    spur = spur_mit_vorfaellen(_profil("eifrig"), SAAT, tage=3)
    pfad = tmp_path / "spur.jsonl"
    schreibe_spur(spur, pfad)
    gelesen = lies_spur(pfad)
    assert gelesen.kopf.als_json() == spur.kopf.als_json()
    assert [(e.ts, e.aktion, e.detail, e.marke) for e in gelesen.ereignisse] \
        == [(e.ts, e.aktion, e.detail, e.marke) for e in spur.ereignisse]


def test_zeitstempel_ohne_zone_wird_mit_namen_verweigert():
    spur = spur_mit_vorfaellen(_profil("eifrig"), SAAT, tage=3)
    naiv = spur.ereignisse[0].ts.replace(tzinfo=None)
    with pytest.raises(SpurFehler, match="Zone"):
        lies_ts(naiv.isoformat())


def test_waechterblick_schneidet_die_marke_ab():
    spur = spur_mit_vorfaellen(_profil("eifrig"), SAAT, tage=3)
    blick, marken = waechterblick(spur)
    assert all(e.marke is None for e in blick)
    assert len(blick) == len(marken) == len(spur.ereignisse)
    assert any(m != MARKE_NORMAL for m in marken), \
        "die Spur muss Vorfall-Marken tragen, sonst misst sie nichts"
    # Und der Blick weiß nichts von Vorfall und Nummer:
    assert all("vorfall" not in (e.detail or "").lower() for e in blick)


def test_gleiche_saat_baut_dieselbe_spur():
    a = spur_mit_vorfaellen(_profil("ruhig"), SAAT, tage=3)
    b = spur_mit_vorfaellen(_profil("ruhig"), SAAT, tage=3)
    assert [(e.ts, e.aktion, e.detail, e.marke) for e in a.ereignisse] \
        == [(e.ts, e.aktion, e.detail, e.marke) for e in b.ereignisse]


# ---------------------------------------------------------------------------
# Gegner-Grundregeln
# ---------------------------------------------------------------------------


def test_b0_flaggt_nur_die_erste_sichtung():
    g = B0()
    ts = datetime(2026, 3, 2, 9, 0, tzinfo=timezone(timedelta(hours=1)))
    assert g.beobachte(ts, "lesen") is True        # nie gesehen
    assert g.beobachte(ts + timedelta(seconds=30), "lesen") is False
    assert g.beobachte(ts + timedelta(seconds=60), "pushen") is True


def test_b1_flaggt_nie_gesehene_uebergaenge_erst_nach_kontext():
    g = B1()
    ts = datetime(2026, 3, 2, 9, 0, tzinfo=timezone(timedelta(hours=1)))
    # min_kontext Durchgänge lesen→suchen: der Übergang ist normal,
    # lesen→committen kommt nie vor.
    for i in range(B1.min_kontext + 2):
        assert g.beobachte(ts + timedelta(seconds=i * 30), "lesen") is \
            (i == 0)
        assert g.beobachte(ts + timedelta(seconds=i * 30 + 10),
                           "suchen") is (i == 0)
    # lesen ist jetzt gut belegt: lesen→committen ist ein nie gesehener
    # Übergang und wird geflaggt, lesen→suchen nicht.
    assert g.beobachte(ts + timedelta(minutes=30), "lesen") is False
    assert g.beobachte(ts + timedelta(minutes=30, seconds=10),
                       "committen") is True


# ---------------------------------------------------------------------------
# Charakterisierung — die strukturellen Zeilen der Tafel
# ---------------------------------------------------------------------------


def test_charakterisierung_des_messstands():
    """Eine Profil-Spur, alle Läufer: die strukturellen Zeilen."""
    profil = _profil("eifrig")
    spur = spur_mit_vorfaellen(profil, SAAT, tage=3)
    blick, marken = waechterblick(spur)

    gegner = [("B0", B0()), ("B1", B1()), ("B2", B2())]
    kands = kandidaten()
    for k in kands:
        k.neu(agent_id=profil.name)
    laeufer = gegner + [(k.name, k) for k in kands]

    flags = {
        name: [l.beobachte(e.ts, e.aktion, e.detail) for e in blick]
        for name, l in laeufer
    }

    def treffer(art: str, name: str) -> bool:
        return any(flags[name][i] for i, m in enumerate(marken)
                   if m.startswith(art))

    # Struktur-Siege:
    assert treffer("neue-aktion", "B0"), \
        "B0 IST die Menge gesehener Aktionen — neue Aktion muss treffen"
    assert treffer("schwall", "B2"), "B2s Ratefenster muss den Schwall sehen"
    assert treffer("funkstille", "B2"), \
        "B2s Funkstille-Schwelle muss die Stille sehen"
    assert treffer("ungewohnte-uhrzeit", "B2"), \
        "B2s Stundenprofil muss die falsche Stunde sehen"
    # Struktur-Niederlage (bewusst in der Tafel und hier festgehalten):
    for name, _ in laeufer:
        assert not treffer("ungewohntes-ziel", name), \
            f"{name} sieht Details strukturell nicht — schlägt die Marke " \
            "jemals an, war die Spur oder der Läufer kaputt"


def test_messstand_ende_zu_ende_liefert_alle_arten():
    bericht = laufe_messstand([SAAT], tage=3,
                              profile_liste=[_profil("eifrig")])
    tafel = bericht["tafel"]
    gefordert = {"neue-aktion", "reihenfolge", "schleife", "schwall",
                 "funkstille", "ungewohnte-uhrzeit", "langsame-drift",
                 "ungewohntes-ziel"}
    assert set(tafel["treffer_je_art"]) == gefordert
    # Fehlalarmraten existieren und sind plausibel (kein Tausenderfestival):
    for name, zahlen in tafel["fehlalarme_je_1000"].items():
        assert 0.0 <= zahlen["mittel"] < 100.0, (name, zahlen)
    # Die gepaarten Differenzen tragen Streuungsfelder:
    for kandidat_name in ("watch-voll", "watch-ohne-kern"):
        differenz = tafel["differenz_gegen_besten_gegner"][kandidat_name]
        assert set(differenz) == gefordert
        assert all("streuung" in z for z in differenz.values())
