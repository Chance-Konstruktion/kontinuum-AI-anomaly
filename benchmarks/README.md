# Der Messstand (Stufe 1, Ticket #1)

Erst messen, dann bauen: Dieses Verzeichnis misst, was der Wächter
gegen dumme Gegner wirklich sieht. Kein neues Modul und keine neue
Strategie gilt hier als verbessert, solange sie nicht gegen B0/B1/B2
eine Zahl vorweisen kann.

## Wie eine Messung abläuft

```
python -m benchmarks.messstand --saaten 7,23,42,101,255 --ziel artefakte
```

Für jede Saat und jedes der fünf Normal-Profile (``agenten.py``:
eigene Markov-Kette, eigener Rhythmus, eigene Tageszeiten, eigene
Ziele) wird eine Spur gebaut, in die je ein Vorfall jeder der acht
Arten eingebaut wird (``vorfaelle.py``). Alle Läufer — die Gegner
B0/B1/B2 (``gegner.py``) und die Kandidaten ``watch-voll`` /
``watch-ohne-kern`` (``kandidaten.py``) — laufen parallel über
denselben Blick ohne Etikett; die Marken (``marke`` in der Spur) sieht
kein Läufer, sie sind nur die Wahrheit, gegen die gewogen wird
(``messstand.py``). Heraus kommt ``artefakte/messstand_tafel.md``
und ``artefakte/messstand.json``.

## Was die Tafel ausgesagt hat (Stand der ersten Messung)

* **Neuheit und Bigramm tragen alles**, was die Kandidaten leisten:
  neue Aktionen, unmögliche Reihenfolgen und Schleifen fangen die
  Kandidaten genauso gut wie der beste dumme Gegner.
* **Der Kern-Pfad bringt bisher nichts**: ``watch-voll`` und
  ``watch-ohne-kern`` unterscheiden sich in keinem Maß. Das ist die
  gepaarte Bestätigung der Gegenprobe vom 04.10. — der einzige Pfad,
  der die Kern-Überraschung liest (``AdaptiveThresholdStrategy``),
  schlägt in keiner Zeile an.
* **Zeitmuster sieht nur, wer selbst Fenster zählt**: Schwall,
  Funkstille und ungewohnte Uhrzeit fängt allein B2 (Zählfenster,
  Funkstille-Schwelle, Stundenprofil); die Kandidaten verlieren diese
  drei Zeilen mit 0 % — das Burst-Tor des Kerns (INSIGHTS §4) frisst
  den Schwall, und keine Strategie hat ein Rate- oder Stundenfenster.
* **Zwei Blindstellen bleiben für alle offen**: langsame Drift (kein
  Läufer zählt Frequenzen je Aktion) und ungewohntes Ziel (kein
  Läufer sieht Details — die Token-Granularität ist die Aktion). Die
  Zeilen stehen absichtlich in der Tafel; genau dafür ist der
  Messstand da.

## Regeln

* Entwicklung nur auf Saaten < 1000. Der versiegelte Prüfsatz
  (eigene Saaten und Generator-Parameter) fährt Claude getrennt — wer
  verbessert, sieht ihn nie, sonst misst der Stand nur noch sich
  selbst.
* Nur synthetische Daten in diesem Repo. Die Spuren werden erzeugt,
  nie importiert.
* Ehrliche Charakterisierungstests (``tests/
  test_messstand_charakterisierung.py``) bleiben drin, auch wenn sie
  eine Niederlage festhalten.
* Das Spurformat ist die Agenten-lesbare Ableitung des
  ``kontinuum-spur/1``-Formats aus ``kontinuum-core/benchmarks/spur``
  (Kopf-Zeile, zonenpflichtige Zeit, ``marke`` als reine Diagnose) —
  ein zweites Format wurde nicht erfunden.
