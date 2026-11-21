# LowDarts – Auto-Darts mit niedrigen Hardware-Anforderungen

Automatische Steeldart-Erkennung mit 3 USB-Kameras – ausgelegt auf **gleiche Erkennungsleistung bei deutlich geringerer Hardware**.
Reines Python + OpenCV, **kein neuronales Netz, keine GPU, kein Browser auf dem Gerät**.

## Hardware: vorher / nachher

| | Typische Anforderung | LowDarts |
|---|---|---|
| CPU | 4 Kerne ≥ 2,4 GHz empfohlen | 1 Kern reicht (Idle ≈ 1 % eines Kerns, ~30 ms Rechenzeit pro Dart) |
| RAM | 4–8 GB | < 200 MB |
| USB | 2 getrennte Controller/Busse | **1 USB-2.0-Controller** (MJPEG @ 10 FPS) |
| Kamera | 640×480 – 1280×720 @ 30 FPS | 640×480 @ 10 FPS |
| Geräte | Mini-PC / Pi 4/5 | Pi 3B+/4, Pi Zero 2 W (nicht getestet), alter Thin-Client |
| Anzeige | Bildschirm/Touch am Rechner | beliebiges Handy/Tablet/TV-Browser im WLAN |

## Warum das weniger Hardware braucht

1. **Ereignisgesteuert statt Dauerverarbeitung.** Man muss den Dart nicht im Flug sehen – nur „vorher“ und „nachher“. Ruht das Board, wird pro Tick nur ein winziges Graubild verglichen. Die teure Analyse läuft **einmal pro Dart**, nachdem das Bild ruhig ist.
2. **10 statt 30 FPS.** Reicht für ~300 ms Latenz und drittelt Dekodier- und USB-Last.
3. **MJPEG + Teil-Dekodierung.** JPEGs werden für die Bewegungserkennung direkt in 1/4-Größe dekodiert (libjpeg-DCT-Skalierung). Volle Auflösung nur für die paar analysierten Frames.
4. **Klassische Bildverarbeitung statt NN.** Differenzbild → Pfeil-Blob → Linien-Fit → Spitze. Welches Ende die Spitze ist, ergibt sich aus der Kamerapose.
5. **Triangulation per Kovarianz.** Jede Kamera misst quer zur Blickrichtung genau, in der Tiefe ungenau. Die 3 Schätzungen werden nach ihrer Unsicherheit gewichtet (2×2-Gleichungssystem) – mit Ausreißer-Erkennung (z. B. Spitze von anderem Pfeil verdeckt).
6. **Auto-Feinkalibrierung.** Du klickst grob 4 Punkte, danach legt ECC-Bildregistrierung ein Board-Modell sub-pixel-genau auf das Kamerabild. Ungenaue Klicks (±6 px) kosten so keine Genauigkeit.

## Messwerte (Simulator, 3 Kameras, 640×480)

```
python -m lowdarts evaluate --throws 600
score_accuracy  0.975     # exakt richtiges Feld
err_mean_mm     0.46      # mittlerer Positionsfehler
err_p95_mm      0.70
```
Die verbleibenden Fehler liegen fast alle < 0,7 mm neben einem Draht (physikalisch grenzwertig). Etwa 1 von 600 Würfen ist ein grober Fehler, wenn die Spitze in 2 von 3 Kameras verdeckt ist – das UI zeigt dann „bitte prüfen“.

```
python -m lowdarts bench
Basis: 30 FPS voll dekodieren (ohne NN!)  8.3 % eines Kerns
LowDarts: 10 FPS Idle                     1.0 % eines Kerns (+28 ms pro Dart)
```

> **Ehrlicher Hinweis:** Alle Zahlen stammen aus einem synthetischen 3D-Simulator, nicht von einem echten Board. Reale Effekte (Kamera-Rauschen, Linsenverzeichnung, Schatten, Lichtring, echte Pfeilspitzen) sind noch nicht validiert – der erste Test am echten Aufbau ist der nächste Schritt.

## Windows-Programm

**Download:** Auf GitHub unter *Actions → Windows build → LowDarts-Windows* liegen nach jedem Push
`LowDarts-Setup.exe` (Installer) und `LowDarts-portable.zip` (ohne Installation entpacken und `LowDarts.exe` starten).
Das Programm öffnet ein eigenes Fenster (Edge WebView2, ist in Windows 10/11 enthalten). Daten, Sounds und Statistiken liegen in `%APPDATA%\LowDarts`.

### Funktionen
* **Spielmodi:** X01 (121–901, Straight/Double/Master In & Out, Legs & Sets, Max. Runden), Cricket & Tactics (Standard, Cut-Throat, ohne Punkte),
  Around the Clock, Bob's 27, Count Up, Shanghai.
* **Computer-Gegner:** 11 Stufen von Ø ~20 bis Ø ~120.
* **Eingabe:** Kameras (automatisch), Klick aufs virtuelle Board oder Tastenfeld; jeden Dart per Klick korrigieren, Rückgängig.
* **Sound & Show:** Sprecher (Windows-Stimmen, offline, deutsch/englisch), eingebaute Effekte (Airhorn bei 180, Sad Trombone beim Bust,
  Grillenzirpen bei 0 Punkten, Fanfare beim Checkout …), **Soundboard** mit 12 Pads + eigenen Sounds (Taste `S`), Einlaufmusik pro Spieler,
  große Animationen und Konfetti.
* **Statistik:** Ø, First 9, Checkout-Quote, 60+/100+/140+/180, Bestes Finish, Match-Historie – alles lokal.
* **Kameras:** 3 USB-Kameras **oder eine einzelne Kamera, z. B. das iPhone** (über eine Webcam-App wie Camo/Iriun oder eine Stream-URL).
  Kalibrierung mit 4 Klicks pro Kamera im Programm.

### Bedienung
| Taste | Aktion |
|---|---|
| `Enter` | nächster Spieler |
| `Backspace` | letzten Dart rückgängig |
| `S` | Soundboard öffnen/schließen |
| `1`–`0`, `Q`, `W` … | Soundboard-Pads (wenn offen) |

## Aus dem Quellcode starten

```bash
pip install -r requirements-desktop.txt
python -m lowdarts                # Desktop-Fenster
python -m lowdarts serve          # nur Server, Bedienung im Browser (http://127.0.0.1:8080)
python -m lowdarts demo           # simuliertes Board mit 3 Kameras, wirft selbst
python -m pytest                  # Tests
```

## Praxis-Hinweise
* **Licht** bleibt wichtig: schattenfreier LED-Ring, keine flackernden Lampen.
* Kameras im 120°-Raster, ca. 30 cm vom Bull, leicht vor der Board-Ebene, Board voll im Bild. Fokus fixieren.
* Bewegt sich eine Kamera, einfach `/setup` für diese Kamera erneut durchlaufen.

## Aufbau
```
lowdarts/
  board.py        Board-Geometrie & Scoring
  geometry.py     Homographie, Brennweiten-/Posen-Schätzung, Unsicherheit
  calibration.py  4-Klick-Kalibrierung + ECC-Feinausrichtung
  camera.py       Kameras (MJPEG, 10 FPS, Teil-Dekodierung)
  detector.py     Pfeilspitzen-Erkennung pro Kamera
  fusion.py       Kovarianz-gewichtete Fusion + Ausreißer
  engine.py       Ereignis-Schleife (Bewegung → Ruhe → Analyse / Pfeile gezogen)
  game.py         Wurf-Eingabe & Checkout-Tipps
  modes.py        Spielmodi (X01, Cricket, Training, Party)
  bot.py          Computer-Gegner
  server.py       App-Server (Spiel, Bots, Einstellungen, Sounds, Kameras)
  desktop.py      Windows-Fenster (pywebview)
  static/         Oberfläche, Sound-Engine & Soundboard
  sim.py          3D-Simulator für Tests & Demo
tests/            pytest
```

## Grenzen / Ideen
* Noch nicht dabei: Killer, Gotcha, Bermuda, 121, Random Checkout, Segment-Training; Ausbullen; Heatmaps.
* Eigener iPhone-Stream per QR-Code (ohne Zusatz-App) ist geplant.
* Linsenverzeichnung wird nicht korrigiert – bei Weitwinkel > 100° ggf. ergänzen.
* Kein Abgleich der Pfeil-Zählung mit Bounce-outs (manuell per Tastenfeld oder Board-Klick).
