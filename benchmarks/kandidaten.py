"""Die Kandidaten des Messstands (Stufe 1, Punkt 3 des Tickets).

Zwei Kandidaten, wie das Ticket sie nennt:

* **watch-voll** — ``AnomalyWatch`` mit der vollen Shipped-Signalmenge:
  ``sequence_aware_strategy()`` (Neuheit + adaptiver Schwellwert +
  Sequenz). Der adaptive Schwellwert ist der EINZIGE Pfad, der die
  Kern-Überraschung aus kontinuum-core liest (dokumentiert in der
  Gegenprobe des Leit-Tickets).
* **watch-ohne-kern** — die Abschaltprobe: dieselbe Komposition ohne
  ``AdaptiveThresholdStrategy``. Der gepaarte Unterschied der beiden
  Kandidaten ist genau der Beitrag des Kern-Pfads.

Beide sind reine Adapter: Sie füttern ``AnomalyWatch.observe(aktion,
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
    """Die zwei Kandidaten des Tickets, frisch und benannt."""
    return [
        WatchKandidat("watch-voll", sequence_aware_strategy),
        WatchKandidat(
            "watch-ohne-kern",
            lambda: CompositeStrategy(
                [NoveltyStrategy(), SequenceStrategy()], mode="or",
            ),
        ),
    ]


__all__ = ["WatchKandidat", "kandidaten"]
