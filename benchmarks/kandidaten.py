"""Die Kandidaten des Messstands (Stufe 1, Punkt 3 des Tickets;
Stufe 2: der dritte Kandidat).

Drei Kandidaten:

* **watch-voll** — ``AnomalyWatch`` mit der vollen Shipped-Signalmenge:
  ``sequence_aware_strategy()`` (Neuheit + adaptiver Schwellwert +
  Sequenz). Der adaptive Schwellwert ist der EINZIGE Pfad, der die
  Kern-Überraschung aus kontinuum-core liest (dokumentiert in der
  Gegenprobe des Leit-Tickets).
* **watch-ohne-kern** — die Abschaltprobe: dieselbe Komposition ohne
  ``AdaptiveThresholdStrategy``. Der gepaarte Unterschied der beiden
  Kandidaten ist genau der Beitrag des Kern-Pfads.
* **watch-zeit** — der Stufe-2-Kandidat: watch-ohne-kern PLUS die drei
  Zeitmuster-Strategien aus :mod:`kontinuum_ai_anomaly.zeitmuster`
  (Schwall-Fenster, Funkstille-Loch, Stundenprofil — die Hebel, die
  die Stufe-1-Tafel benannt hat, VOR dem Burst-Tor gezählt, denn das
  Burst-Tor des Kerns frisst den Schwall, bevor die Engine ihn sieht).

Alle sind reine Adapter: Sie füttern ``AnomalyWatch.observe(aktion,
detail, ts=...)`` und melden ``is_anomaly`` als Flag. Festgelegte
Randeentscheidungen, damit niemand im Dunkeln tappt:

* **Keine Wiederkehr-Signale.** ``RecurrenceDetector`` ist im Paket
  ausdrücklich außer Band („retrospective evaluations, not per-event
  flags", :mod:`kontinuum_ai_anomaly.recurrence`) — er gehört nicht
  zum Ereignis-Urteil und wird deshalb nicht als Flag gemischt.
  ``track_recurrence=False``.
* **Frische Instanz je Spur.** Kein Gehirn, kein Ledger, kein
  Wiederkehr-Zustand wird zwischen Spuren geteilt — jede Spur misst
  den Kandidaten so, wie er im Neuanlauf laufen würde.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from kontinuum_ai_anomaly import AnomalyWatch
from kontinuum_ai_anomaly.scoring import (
    CompositeStrategy,
    NoveltyStrategy,
    SequenceStrategy,
    sequence_aware_strategy,
)
from kontinuum_ai_anomaly.zeitmuster import (
    FunkstilleStrategy,
    SchwallStrategy,
    StundenprofilStrategy,
)


class WatchKandidat:
    """Ein AnomalyWatch-Kandidat in der Form der Gegner
    (``beobachte(ts, aktion, detail) -> bool``) — der gemeinsame
    Tresor des Messstands für alle Läufer."""

    def __init__(self, name: str, strategie) -> None:
        self.name = name
        self._strategie_bau = strategie
        self._watch: Optional[AnomalyWatch] = None

    def neu(self, agent_id: str) -> None:
        """Frische Instanz für die nächste Spur."""
        self._watch = AnomalyWatch(
            agent_id=agent_id,
            strategy=self._strategie_bau(),
            track_recurrence=False,
        )

    def beobachte(
        self, ts: datetime, aktion: str, detail: Optional[str] = None,
    ) -> bool:
        if self._watch is None:
            raise RuntimeError(
                f"Kandidat {self.name!r}: erst neu(agent_id) rufen — "
                "ohne frische Instanz würde eine Spur in die Geschichte "
                "der vorherigen laufen."
            )
        urteil = self._watch.observe(aktion, detail, ts=ts)
        return bool(urteil.is_anomaly)


def kandidaten() -> "list[WatchKandidat]":
    """Die drei Kandidaten, frisch und benannt.

    Der dritte ist der Stufe-2-Kandidat (claudes drei Punkte, Notiz
    15455): dieselbe volle Shipped-Signalmenge wie ``watch-voll`` PLUS
    die drei Zeitmuster-Strategien — Rate-Fenster (Schwall),
    Funkstille-Loch und Stundenprofil, alle VOR dem Burst-Tor gezählt
    (Monitor-Schicht, Kern unberührt). Die gepaarte Differenz zu B2
    sagt, ob der Wächter die Zeitmuster-Zeilen der Tafel jetzt selbst
    trägt — und was er an Fehlalarmen dafür zahlt.
    """
    return [
        WatchKandidat("watch-voll", sequence_aware_strategy),
        WatchKandidat(
            "watch-ohne-kern",
            lambda: CompositeStrategy(
                [NoveltyStrategy(), SequenceStrategy()], mode="or",
            ),
        ),
        WatchKandidat(
            "watch-zeit",
            lambda: CompositeStrategy(
                [
                    NoveltyStrategy(),
                    SequenceStrategy(),
                    SchwallStrategy(),
                    FunkstilleStrategy(),
                    StundenprofilStrategy(),
                ],
                mode="or",
            ),
        ),
    ]


__all__ = ["WatchKandidat", "kandidaten"]
