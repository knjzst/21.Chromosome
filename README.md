# 21.Chromosome

Dart-Erkennungs-Engine für Low-End-Hardware (Zielplattform: **Raspberry Pi 4**, 3× USB-Webcam).
Architektur abgeleitet aus einer statischen Analyse von Autodarts Desktop 2.1.1
(siehe [docs/Autodarts-Analyse.md](docs/Autodarts-Analyse.md)) – **nur Prinzipien übernommen, kein fremder Code**.

## Architektur

```
3× USB-Cam (MJPEG, V4L2)          api.py (Flask, Port 3180)
   │  camera.py: 1 Thread/Cam        ▲  REST + SSE + MJPEG-Streams
   ▼                                 │
motion.py  – Differenzbild 320×180, Zustandsautomat        ← läuft IMMER (billig)
   │  IDLE → MOTION → SETTLED  /  → TAKEOUT
   ▼ nur bei Ereignis:
detect.py  – Crop um Einschlag, Hough-Schaftlinie → Spitze  ← läuft NUR pro Wurf (teuer)
   ▼
calibration.py – Ellipse → Homographie: Bild-px → Board-mm
   ▼
fusion.py  – Lesungen aller Kameras: Ausreißer raus, gewichtet mitteln
   ▼
scoring.py – Boardpunkt → T20/D16/BULL/…  → Event an API-Clients
```

Kernidee (von Autodarts übernommen): Das System ist im Leerlauf fast kostenlos –
pro Kamera nur ein Resize+Diff auf 320×180. Die teure Analyse läuft pro Wurf genau
einmal und nur auf einem kleinen Bildausschnitt. Damit reicht ein Pi 4 für 3×720p30.

v0 arbeitet **komplett ohne neuronales Netz** (klassische Geometrie). Ein
Keypoint-NN kann später in `detect.detect_tip()` als Verfeinerung eingehängt
werden; Trainingsdaten liefern die Debug-Dumps.

## Installation (Raspberry Pi 4, Raspberry Pi OS Bookworm 64-bit)

### Voraussetzungen
- Raspberry Pi 4 (2 GB reichen), 64-bit-OS
- 3 USB-Webcams mit MJPEG-Unterstützung (UVC), möglichst gleiche Modelle
- Python ≥ 3.11

### Schritte
1. System vorbereiten:
   ```bash
   sudo apt update && sudo apt install -y python3-opencv python3-flask python3-numpy git
   ```
2. Repo klonen:
   ```bash
   git clone https://github.com/knjzst/21.Chromosome.git && cd 21.Chromosome
   ```
3. Kamera-Indizes ermitteln und in `config.toml` → `[cameras] indices` eintragen:
   ```bash
   v4l2-ctl --list-devices
   ```
4. Engine starten:
   ```bash
   python3 -m chromosome
   ```
5. Je Kamera kalibrieren: Standbild unter `http://<pi>:3180/api/img/cams/0` ansehen,
   Bildkoordinaten der **Mitte des 20er-Segments** ablesen und senden:
   ```bash
   curl -X POST http://<pi>:3180/api/config/calibration/auto/0 \
        -H "Content-Type: application/json" -d '{"p20": [640, 120]}'
   ```

### Verifikation
- `curl http://<pi>:3180/api/state/stats` → alle Kameras `connected: true`, `calibrated: true`
- Events live: `curl -N http://<pi>:3180/api/events`, dann Dart werfen → `{"kind":"throw","score":{"label":"T20",…}}`
- Fehlerhafte Erkennung? `curl -X POST http://<pi>:3180/api/debug/dump -d '{"comment":"Beschreibung"}' -H "Content-Type: application/json"` → Archiv in `dumps/`

### Rollback
Engine ist zustandslos bis auf `calibration.json` und `dumps/` – Dienst stoppen,
Dateien löschen, neu kalibrieren.

## API (Auszug)

| Methode | Route | Zweck |
|---|---|---|
| GET | `/api/state/stats` | Kamerastatus, Motion-Zustand, aktueller Turn |
| GET | `/api/events` | Server-Sent Events (throw/takeout/status) |
| GET | `/api/img/cams/<n>` · `/api/streams/cams/<n>` | Snapshot / MJPEG-Stream |
| GET/PATCH | `/api/config/dynamic` | Schwellen lesen / zur Laufzeit ändern |
| POST | `/api/config/reset` | `config.toml` neu laden |
| POST | `/api/config/calibration/auto/<n>` | Kamera n kalibrieren (`{"p20":[x,y]}`) |
| POST | `/api/debug/dump` | Debug-Archiv (Config + Frames + Events) |

## Tuning

Alle Schwellen stehen kommentiert in [config.toml](config.toml) und sind per
`PATCH /api/config/dynamic` ohne Neustart änderbar, z. B.:
```bash
curl -X PATCH http://<pi>:3180/api/config/dynamic \
     -H "Content-Type: application/json" -d '{"motion": {"diff_threshold": 25}}'
```

## Roadmap

- [ ] Web-UI (statische Seite gegen die API; Scoring-Anzeige, Kalibrier-Klick auf die 20)
- [ ] Spiellogik (501, Cricket) als eigener Service auf Basis der Events
- [ ] Keypoint-NN (INT8, TFLite/ncnn) als Verfeinerung in `detect.py`, trainiert aus Dumps
- [ ] Autokalibrierung ohne 20er-Klick (Segmentfarben/Spider-Linien)
- [ ] systemd-Unit für Autostart
