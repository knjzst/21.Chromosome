# Autodarts Desktop 2.1.1 – Strukturanalyse & Ableitungen für eigene Low-HW-Software

Stand: 2026-11-21 · Methode: rein statisch (Entpacken, PE-Metadaten, Strings, RTTI-Klassennamen). Nichts ausgeführt, kein Code dekompiliert oder übernommen.

> **Rechtlicher Rahmen:** Ausgewertet wurde nur, was jede ausgelieferte Datei offen zeigt (Bibliotheken, Klassen-/Routennamen, Konfig-Schlüssel). Das ist Ideen-/Architekturebene (§ 69a Abs. 2 UrhG: Ideen sind nicht geschützt). Für die eigene Software gilt: **keinen Code, keine Modelle, keine Assets übernehmen**, eigene Implementierung und eigenes Trainingsmaterial. Die EULA von Autodarts habe ich nicht geprüft.

Legende: **[B]** = belegt durch String/Symbol im Binary · **[A]** = Ableitung/Interpretation

---

## 1. Paket & Toolchain

| Punkt | Befund | |
|---|---|---|
| Installer | Velopack 1.2.0 (Setup-Stub + eingebettetes `.nupkg`), Delta-Updates `*-delta.nupkg` | [B] |
| Inhalt | `autodarts-desktop.exe` (28 MB), `slint_cpp.dll` (28 MB), `Squirrel.exe`, Stub | [B] |
| Sprache | C++17, Cross-Compile auf macOS arm64 → Windows x64 mit `clang-cl` 21 + `xwin` (MS-SDK) | [B] |
| UI | **Slint** (native, deklarativ, kein Browser/Electron); Schriften Manrope, Bebas Neue, League Spartan | [B] |
| Rust-Anteile | `rustls`, `xml`-Crate im Exe → Slint-Laufzeit / TLS | [B] |
| Bildverarbeitung | **OpenCV 5.0.0 statisch**, nur Module `core dnn features flann geometry imgcodecs imgproc video` | [B] |
| CPU-Baseline | SSE3, Laufzeit-Dispatch SSE4.x/AVX/AVX2/AVX-512 | [B] |
| ML | OpenCV-`dnn` gebaut, **kein ONNX Runtime**, kein MLAS, kein CUDA; Klasse `ad::ml::Inference` | [B] |
| Modell | Kein ONNX-Modell im Binary gefunden → wird geladen/nachgeladen (vermutlich über `releases.autodarts.com/autodarts-x` oder Cloud) | [A] |
| Kamera | Direkt **Media Foundation** (`MsmfEnumerator`, `SourceReaderCallback`, Hotplug-Fenster), MJPEG-Dekodierung über libjpeg-turbo, Orbbec-Support | [B] |
| HTTP | `cpp-httplib` (Klasse `HttplibHttp`), WinHTTP-WebSocket zur Cloud | [B] |

**Kernaussage:** Autodarts hat sich bewusst für *eine* native C++-Binary mit minimalem OpenCV-Subset, nativer UI und CPU-Inferenz entschieden. Kein Python, kein Browser, keine GPU-Pflicht.

## 2. Modulstruktur (aus RTTI-Namespaces)

```
addesk::DesktopHost / App           – Desktop-Shell
ad::ui::slint::Host / Presenter     – UI (MainWindow, CamControl, VisionPanel, DartDot, Toast)
ad::board::model::BoardModel        – UI-Modell, wählt lokales oder entferntes Board
ad::board::engine::Board            – Zustandsautomat: create → setup → start/stop/reset, patch_config, apply_tuning
ad::board::engine::VantageBoard     – Board-Implementierung Pipeline "vantage" (bekommt shared_ptr<Inference>)
ad::board::engine::CameraSet/Sources– Kamerasatz, link_readiness
ad::board::engine::Fits             – Kalibrierungs-Fits speichern/restore
ad::board::engine::Upstream         – Cloud-Anbindung (StartPolicy, Transport)
ad::board::api::server::Server      – lokale REST-/Stream-API (host_routes)
ad::board::api::client::RemoteBoard – gleiche API als Client → UI kann entferntes Board bedienen
ad::camera::graph::{source,decoder,Output} – Frame-Graph: Capture/Link → Codec → FrameGroup<cv::Mat>
ad::detect::Detector / vantage::Detector   – Erkennung, Events, Reports, RenderState
ad::detect::joint_lm_polish(CamFit…)        – Multi-Kamera-Feinausgleich (Levenberg-Marquardt)
ad::ml::Inference                   – NN-Inferenz
ad::link::Server / LinkSession      – "Autodarts Link": eigene Kamera-Hardware (WLAN, Firmware, Licht, Codec, Speedtest)
ad::cloud::Socket / Transport       – WebSocket zu boards.ws.autodarts.com
ad::service::TrackingServer         – Telemetrie/Tracking
```

**Muster [A]:** Engine und UI sind über dieselbe API entkoppelt (`IBoard` lokal ↔ `RemoteBoard` über HTTP). Die Erkennung kann also headless auf einem kleinen Gerät laufen, UI woanders.

## 3. Erkennungs-Pipeline

### 3.1 Zweistufig: billige Bewegung → teure Inferenz [B/A]

Konfig-Schlüssel des Bewegungsdetektors (Werte nicht ermittelt):

| Schlüssel | Bedeutung [A] |
|---|---|
| `motion_min_change` | Mindest-Pixeländerung im Differenzbild |
| `motion_min_contour_area` | Mindestfläche einer Kontur |
| `motion_min_dart_frames` | so viele ruhige Frames, bis ein Dart als "gelandet" gilt |
| `motion_min_dart_pixels` | Pixelmenge, die ein Dart mindestens ändert |
| `motion_min_hand_foreground_pixels` / `..._background_pixels` | Hand-/Großobjekt-Erkennung (→ Takeout) |
| `diff_threshold`, `detection_hough_threshold` | Schwelle Differenzbild, Hough-Linien (Dartschaft) |
| `takeout_wait_frames`, `takeout_min_hand_frames`, `takeout_min_coverage`, `takeout_min_completed_frames`, `takeout_completed_stable_multiplier`, `slow_takeout_frames` | Takeout-Zustandsautomat |
| `board_confidence`, `dart_confidence` | Schwellen der NN-Ausgabe |
| `handheld_threshold_px` | Dart in der Hand vs. steckend |

Zustände/Events: `ThrowDetected`, `TakeoutStarted`, `TakeoutInProgress`, `TakeoutFinished`, `is_takeout_partial/full`. UI-Texte bestätigen die Logik: *„Gray stayed still, red moved, yellow is a dart that was already there, green the one that just landed."* und *„each cell shows the whole dart and no background around it"* → **Inferenz läuft auf Crops pro Kamera**, nicht auf dem Vollbild.

### 3.2 Multi-Kamera-Fusion [B]
- Pro Kamera eigene Lesung („The yellow segment is that one camera's read, not the final score").
- Fusion über `joint_lm_polish` (Levenberg-Marquardt über alle `CamFit`), dazu OpenCV `geometry`: `solvePnP`, `findHomography`, USAC/RANSAC, `triangulate`.
- Ergebnis wird im „board space" dargestellt.

### 3.3 Kalibrierung [B]
- Ringe der Scheibe als **Ellipsen** (`fitEllipse`, `/api/config/calibration/ellipses`), daraus Homographie/Pose (`/geometry`).
- Automatische Kalibrierung je Kamera (`/calibration/auto/(\d+)`), Remote-Kalibrierung (`RemoteCalibration`).
- Linsenverzeichnung umschaltbar (`set_auto_distortion`, „Lens distortion correction").
- Kalibrierung wird abgelehnt, wenn Darts stecken („Clear the board so every camera can see it").

### 3.4 Zwei Pipelines: `pipelines.vantage` und `pipelines.lens` [B]
`vantageConfig` / `lensConfig`, `IVantageBoard` / `ILensBoard`. Lens hat eigene Inferenz-Historie (`/api/lens/inference`, `/img/detection/lens/before-after`). [A] Wahrscheinlich ältere/neuere Detektorgeneration nebeneinander, umschaltbar.

## 4. Lokale API (Auszug, cpp-httplib)

| Bereich | Routen |
|---|---|
| Kameras | `/api/cams/controls[/(\d+)[/reset]]`, `/api/config/cam/resolution` |
| Konfig | `/api/config/{pipeline,dynamic,reset}`, `/api/config/calibration/{auto,ellipses,geometry}` |
| Bilder | `/api/img/{live,cams/N,detection,detection/before,after,movement,inference/N}` |
| Streams | `/api/streams/{live,cams/N,detection,detection/movement,motion,calibration}` |
| Zustand | `/api/state/stats`, `/api/state/motion/history`, `/api/events/system` |
| Debug | `/api/debug/dump/{freeze,thaw}` → Archiv mit Config, Motion-History, Bildern, Nutzerkommentar |
| Setup/Update | `/api/setup/finish`, `/api/update/{check,apply,track}` |
| Link-HW | `/api/link/{wifi/scan,connect,…,update/*,speedtest,screen,source}` |
| User/Cloud | `/api/user/{login/link,login/redirect,logout,boards,boards/claim,avatar}` |

Cloud: `api.autodarts.com` (Device-Token-Flow `/auth/v1/device/token`, `tokens.json`), WebSocket `boards.ws.autodarts.com`. **Erkennung läuft offline weiter** („Darts are still detected, but they are not reaching your account").

---

## 5. Was ich für deine Low-HW-Software daraus übernehmen würde

Zielplattform angenommen: Raspberry Pi 4/5, Intel N100/Celeron, alte i3 – **bitte bestätigen**.

| # | Prinzip (Idee, kein Code) | Konkrete Umsetzung bei dir | HW-Effekt |
|---|---|---|---|
| 1 | **Gating:** Bewegung billig, NN nur bei Ereignis | Graustufen-Diff auf 320×240, Kontur-/Pixelschwellen, Zustandsautomat Idle→Motion→Settled→Infer / Hand→Takeout | CPU im Leerlauf nahe 0, NN-Aufrufe ~3 pro Aufnahme |
| 2 | **Crop statt Vollbild** | ROI um geänderte Kontur (z. B. 128–192 px) ins Modell | Inferenz ×10–30 schneller |
| 3 | **Klassische Geometrie zuerst** | Hough-Linie des Schafts + Spitzenpunkt aus Diff; NN nur als Fallback/Verfeinerung | Läuft auch ganz ohne NN |
| 4 | **Ellipsen-Kalibrierung** | Ringe per `fitEllipse` → Homographie Bild→Board; Ergebnis cachen | Einmalig, kein Laufzeitaufwand |
| 5 | **Multi-Cam-Fusion per kleiner Optimierung** | Pro Kamera Treffpunkt in Board-Koordinaten, dann gewichtetes Mittel / LM über 2–3 Punkte, Ausreißer per RANSAC | Robust ohne Stereo-Rekonstruktion |
| 6 | **Minimal-OpenCV statisch** | Nur `core imgproc video dnn` (+`geometry`/`calib3d`), Baseline SSE3/NEON + Dispatch | kleine Binary, läuft auf alter HW |
| 7 | **MJPEG direkt vom Kamera-Treiber** | V4L2/MSMF MJPEG, libjpeg-turbo, ggf. Dekodierung in reduzierter Auflösung (`IMREAD_REDUCED_*`) | spart Bandbreite und CPU |
| 8 | **Headless-Engine + API, UI getrennt** | Engine als Dienst, REST + WebSocket-Events, MJPEG-Stream; UI im Browser *eines anderen Geräts* oder schlank nativ | Erkennungsgerät braucht keinen Desktop |
| 9 | **Debug-Dump** | Bei Fehlwurf: Config + letzte N Frames + Bewegungsverlauf als Archiv | Tuning ohne Live-Zugriff, Trainingsdaten |
| 10 | **Offline-first** | Cloud nur optional, Scoring lokal | keine Abhängigkeit vom Netz |
| 11 | **Alle Schwellen als Config** | Schlüssel wie in 3.1 in `config.toml`, live per `/config/dynamic` patchbar | Tuning pro Aufbau/Licht |

**Modellwahl Low-HW [A]:** Kleines Keypoint-/Heatmap-Netz (Spitze + Schaftende) auf 128–192-px-Crops, INT8 quantisiert; Laufzeit OpenCV-DNN oder ncnn/onnxruntime (ARM). Eigene Trainingsdaten über die Dump-Funktion (Punkt 9) sammeln.

## 6. Offen

- Wo liegt deine Software, Sprache/Stack, Zielhardware, Kamerazahl/-typ?
- Werte der Schwellen und Modellarchitektur von Autodarts sind nicht ermittelt (dafür wäre Laufzeitanalyse nötig, für dein Ziel nicht erforderlich).

## Artefakte

| Datei | Ort |
|---|---|
| Entpacktes Paket, String-Dump | Scratchpad der Sitzung (temporär) |
| SHA-256 `autodarts-desktop.exe` | `55bfbe532f95fbf798efda64d4f0bc49e337351afa511d907681e2e697f226df` |
