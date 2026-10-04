"""Die drei dummen Gegner B0/B1/B2 — als ERKENNUNGS-Gegner (Stufe 1,
Punkt 3 des Tickets).

Nicht dieselben B0/B1/B2 wie in ``kontinuum-core/benchmarks/spur``:
Dort sagen sie das nächste Ereignis voraus, hier urteilen sie je
Ereignis, ob es anomal ist — das Ticket definiert sie so:

* **B0** — die Menge gesehener Aktionen. Nie Gesehenes ist anomal.
* **B1** — B0 + Bigramm. Ein Übergang (Vorgänger → Aktion), der noch
  nie gesehen wurde, ist anomal, sobald der Vorgänger oft genug
  ausgegangen ist (:attr:`B1.min_kontext`, derselbe Wert wie der
  ``min_context`` der ``SequenceStrategy`` — sonst wäre der Gegner
  schwächer als der Kandidat, und der Vergleich sagt nichts).
* **B2** — B1 + Zählfenster: ein Rate-Fenster (Schwall), eine
  Funkstille-Schwelle und ein Stundenprofil (ungewohnte Uhrzeit).

Gemeinsame Ordnung:

* **Erst urteilen, dann lernen.** Ein Ereignis wird NUR mit dem
  gesehen, was VOR ihm kam — es kann nie die eigene Basis verschieben
  (dieselbe Schule, die ``AdaptiveThresholdStrategy`` und die
  ``SequenceStrategy`` im Paket fahren: „Record AFTER evaluating").
* **Kein Zufall, keine Uhr des Prozesses.** Nur Ereigniszeit und
  gezählte Fakten; dieselbe Folge von Ereignissen führt zu derselben
  Folge von Urteilen.
* **Die Funkstille-Schwelle kennt die Ruhezeiten.** Ein Loch zählt
  nur, wenn seine MITTE in einer Stunde liegt, die der Agent schon
  gesehen hat — die Nachtpause zwischen zwei Arbeitstagen liegt in
  nie gesehenen Stunden und ist damit keine Funkstille, sondern der
  Feierabend.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from statistics import median
from typing import Deque, Dict, List, Optional, Set, Tuple


class Gegner:
    """Gemeinsame Form aller Gegner: ``beobachte`` urteilt EIN Ereignis
    und lernt es danach."""

    name = "?"

    def beobachte(
        self, ts: datetime, aktion: str, detail: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError


class B0(Gegner):
    """Die Menge gesehener Aktionen — das trustworthy Minimum."""

    name = "B0"

    def __init__(self) -> None:
        self._gesehen: Set[str] = set()

    def beobachte(
        self, ts: datetime, aktion: str, detail: Optional[str] = None,
    ) -> bool:
        fremd = aktion not in self._gesehen
        self._gesehen.add(aktion)
        return fremd


class B1(Gegner):
    """B0 + Bigramm: nie gesehene Übergänge nach genügend Vorgänger-Evidenz."""

    name = "B1"
    #: Derselbe Wert wie ``SequenceStrategy.min_context`` im Paket —
    #: der dumme Gegner bekommt dieselbe Evidenz-Schwelle.
    min_kontext = 20

    def __init__(self) -> None:
        self._b0 = B0()
        self._uebergaenge: Dict[Tuple[str, str], int] = {}
        self._ausgehend: Dict[str, int] = {}
        self._vorgaenger: Optional[str] = None

    def beobachte(
        self, ts: datetime, aktion: str, detail: Optional[str] = None,
    ) -> bool:
        fremd_aktion = self._b0.beobachte(ts, aktion, detail)
        fremd_uebergang = False
        if (self._vorgaenger is not None
                and self._ausgehend.get(self._vorgaenger, 0)
                >= self.min_kontext):
            paar = (self._vorgaenger, aktion)
            if paar not in self._uebergaenge:
                fremd_uebergang = True
        # Lernen NACH dem Urteil (siehe Modul-Docstring).
        if self._vorgaenger is not None:
            paar = (self._vorgaenger, aktion)
            self._uebergaenge[paar] = self._uebergaenge.get(paar, 0) + 1
            self._ausgehend[self._vorgaenger] = \
                self._ausgehend.get(self._vorgaenger, 0) + 1
        self._vorgaenger = aktion
        return fremd_aktion or fremd_uebergang


class B2(Gegner):
    """B1 + Zählfenster: Rate (Schwall), Funkstille und Stundenprofil.

    Die Schwellen sind absichtlich simpel und stehen mit Namen hier —
    ein Gegner, dessen Einstellung man erraten müsste, wäre ein
    schlechter Maßstab:

    * **Schwall**: Ereignisse im rollierenden 60-s-Fenster; Flag ab
      ``schwall_min`` (10) UND ab dem ``schwall_faktor``-Fachen (5×)
      des Medians aller bisherigen Fensterstände. Ein normaler
      Profil-Takt (Abstände >= 20 s) kommt nie über 4 je Minute.
    * **Funkstille**: Abstand > ``funkstille_s`` (2 h) UND Mitte des
      Lochs in einer bereits gesehenen Stunde (siehe Modul-Docstring).
      Die größten normalen Pausen der Profile bleiben unter 1 h.
    * **Stundenprofil**: nie gesehene Ortsstunde, aber erst, wenn
      mindestens zwei Kalendertage Ereignisse geliefert haben (die
      Tagesform ist dann einmal wiederholt) und der Strom lang genug
      ist (``stunden_warmlauf``). Ein Strom, der nur in seinem
      Aktivfenster lebt, hat danach jede Stunde gesehen — der erste
      Vorfall um 3 Uhr morgens ist damit der erste Stundentreffer.
    """

    name = "B2"

    def __init__(
        self,
        fenster_s: float = 60.0,
        schwall_min: int = 10,
        schwall_faktor: float = 5.0,
        funkstille_s: float = 7200.0,
        stunden_warmlauf: int = 150,
    ):
        self._b1 = B1()
        self.fenster_s = float(fenster_s)
        self.schwall_min = int(schwall_min)
        self.schwall_faktor = float(schwall_faktor)
        self.funkstille_s = float(funkstille_s)
        self.stunden_warmlauf = int(stunden_warmlauf)
        self._im_fenster: Deque[datetime] = deque()
        self._fenster_staende: List[int] = []
        self._letzter_ts: Optional[datetime] = None
        self._stunden: Set[int] = set()
        self._tage: Set[str] = set()

    def beobachte(
        self, ts: datetime, aktion: str, detail: Optional[str] = None,
    ) -> bool:
        fremd_b1 = self._b1.beobachte(ts, aktion, detail)

        # ── Rate-Fenster (Schwall) ────────────────────────────────
        while (self._im_fenster
               and (ts - self._im_fenster[0]).total_seconds()
               > self.fenster_s):
            self._im_fenster.popleft()
        rate = len(self._im_fenster) + 1  # das aktuelle Ereignis zählt mit
        schwall = False
        if (len(self._fenster_staende) >= 100):
            schwelle = max(
                self.schwall_min,
                self.schwall_faktor * median(self._fenster_staende),
            )
            if rate >= schwelle:
                schwall = True
        self._im_fenster.append(ts)
        self._fenster_staende.append(rate)

        # ── Funkstille ────────────────────────────────────────────
        stille = False
        if self._letzter_ts is not None:
            loch = (ts - self._letzter_ts).total_seconds()
            if loch > self.funkstille_s:
                mitte = self._letzter_ts + (ts - self._letzter_ts) / 2
                if mitte.hour in self._stunden:
                    stille = True

        # ── Stundenprofil ─────────────────────────────────────────
        stunde_fremd = False
        if (len(self._tage) >= 2
                and len(self._fenster_staende) >= self.stunden_warmlauf
                and ts.hour not in self._stunden):
            stunde_fremd = True

        # Lernen NACH dem Urteil (siehe Modul-Docstring).
        self._letzter_ts = ts
        self._stunden.add(ts.hour)
        self._tage.add(ts.date().isoformat())

        return fremd_b1 or schwall or stille or stunde_fremd


__all__ = ["Gegner", "B0", "B1", "B2"]
