"""Der Messstand des Wächters (Stufe 1, kontinuum-ai-anomaly #1).

Erst messen, dann bauen: Dieses Paket misst, was der Wächter gegen
dumme Gegner wirklich sieht. Die Teile:

* :mod:`benchmarks.spur` — die Agenten-Spur (JSONL), angelehnt an das
  Spurformat v1 aus ``kontinuum-core/benchmarks/spur``.
* :mod:`benchmarks.agenten` — mehrere normale Agenten als Profile
  (Markov-Ketten, Rhythmen, Tageszeiten, Details).
* :mod:`benchmarks.vorfaelle` — die acht Vorfallarten und ihr Einbau
  in die normale Spur.
* :mod:`benchmarks.gegner` — die dummen Gegner B0/B1/B2.
* :mod:`benchmarks.kandidaten` — die AnomalyWatch-Kandidaten (voll und
  ohne Kern-Pfad).
* :mod:`benchmarks.messstand` — der Messlauf, die Maße und die Tafel.

Nur synthetische Daten in diesem Repo — die Spuren werden erzeugt,
nie importiert. Entwicklung nur auf Saaten < 1000; der versiegelte
Prüfsatz fährt getrennt (Claude).
"""
