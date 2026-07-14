# Track Eye — per-eye pupil tracking → animatronic eyes

Tracks **both pupils independently** from a USB camera on a Raspberry Pi 5 and drives
**two animatronic eyes (4 servos)** on an ESP32-S3 so each model eye follows the
matching real pupil — robust to head movement, **no calibration**. Built for a
head-in-box film installation: a camera inside the box watches the viewer's eyes and
the servo eyes look where the viewer looks.

---

## System architecture

```
┌──────────────────────── Raspberry Pi 5 ────────────────────────┐
│  USB cam ─► MediaPipe FaceMesh ─► per-eye pupil (h, v)          │
│              (478 landmarks,        head-normalized, EMA)       │
│               refine_landmarks)             │                   │
│                                             ▼                   │
│   MJPEG web UI :8080  ◄─ overlay      servo_link (map → angle)  │
│   (view in browser)                         │                   │
└─────────────────────────────────────────────┼─────────────────┘
                                               │  WiFi UDP :8770
                                  EYES,Lpan,Ltilt,Rpan,Rtilt,gate
                                               ▼
┌──────────────────────── ESP32-S3 (MicroPython) ────────────────┐
│  UDP recv ─► gate + 900 ms watchdog ─► ±3°/loop slew ─► 4× PWM  │
└────────────────────────────────────────────────────────────────┘
                                               ▼
                    L_pan  L_tilt   R_pan  R_tilt   (2 eyes × pan/tilt)
```

- **Perception (Pi5).** Iris landmarks are read **directly** from MediaPipe FaceMesh,
  so whenever a face is visible **both pupils are always tracked** (no per-eye dropout).
  Each pupil offset is measured in that eye's own corner frame → **head-robust**, then
  EMA-smoothed. The two eyes stay **independent**.
- **Mapping (Pi5, `servo_link.py`).** Each eye's `(h, v)` → `(pan, tilt)` angle with a
  dead-zone, response curve, per-direction gain and safety clamp. Pure Python — tune
  without reflashing the ESP.
- **Transport.** One UDP datagram per frame over WiFi (stdlib `socket`, **no extra
  dependency**). Lost packets are harmless — the next frame overwrites.
- **Actuation (ESP32-S3).** Firmware only receives angles, low-pass/slews them for
  smooth motion, and drives 4 servos. A watchdog re-centers the eyes if the feed stops.

Full algorithm & pipeline walkthrough: **`docs/PIPELINE.html`** (open in a browser).

---

## Hardware

| Part | Notes |
|------|-------|
| Raspberry Pi 5 | Debian Trixie; MediaPipe in a `.venv` (Python 3.11). Add a **fan/heatsink** — sustained MediaPipe heats the Pi. |
| USB camera | e.g. UGREEN, `/dev/video0`, MJPG 1280×720 |
| ESP32-S3 | MicroPython; on the same WiFi as the Pi |
| 4× servos | 2 eyes × (pan + tilt). SG90/MG90S class |
| 5 V supply | **Separate 5 V for the servos**, **common ground** with the ESP32 (do not power 4 servos from the board) |

Servo pins (ESP32-S3): `L_pan=11  L_tilt=12  R_pan=13  R_tilt=14`.

---

## Quick start

### A. Pi5 — perception + web UI

```bash
# perception only (browser view, no servos):
python tools/pupil_spike.py --web-ui-host 0.0.0.0
# then open http://<pi-ip>:8080

# perception + servos (send angles to the ESP32):
python tools/pupil_spike.py --web-ui-host 0.0.0.0 --udp-host <esp-ip>
```

Without `--udp-host` the servo output is off and the demo is unchanged.
Deps: `pip install -r requirements.txt` (mediapipe, opencv, numpy).

### B. ESP32-S3 — servos (flash via Thonny)

1. Copy `hardware/secrets.example.py` → `secrets.py`, fill in the WiFi password.
2. Upload `secrets.py` + `hardware/esp32s3_eye_follow.py` to the board, run it (F5).
3. It prints its IP on boot — use that as `<esp-ip>` above.
   (Save the firmware as `main.py` on the board to auto-run on power-up.)

### C. Together

Run the Pi command with `--udp-host <esp-ip>`, sit in front of the camera → the two
model eyes follow both pupils. Watch the overlay at `http://<pi-ip>:8080`.

---

## Bring-up & testing (no camera needed)

`tools/servo_link_test.py` injects synthetic signals to verify the link and directions:

```bash
python tools/servo_link_test.py --udp-host <esp-ip>              # smooth sweep
python tools/servo_link_test.py --udp-host <esp-ip> --mode poses # left/right/up/down
```

Bare servo checks (MicroPython, run on the board):
`hardware/esp32s3_servo_test.py` (manual angle commands) and
`hardware/esp32s3_eye_circle.py` (both eyes roll in a circle).

---

## Configuration / tuning

All knobs are in `servo_link.py` (Pi, no reflash) and `hardware/esp32s3_eye_follow.py` (ESP):

| Knob | Where | Default | Meaning |
|------|-------|---------|---------|
| pan range / center | both | 80, 40–140 | horizontal travel per eye |
| tilt range / center | both | 60, 20–110 | vertical travel (up=110, down=20) |
| pan / up gain | `servo_link.py` | ×1.5 | horizontal & upward responsiveness |
| down gain | `servo_link.py` | ×3 | downward (MediaPipe under-reads down) |
| `pan_sign` / `tilt_sign` | `servo_link.py` | ±1 | flip if an axis moves the wrong way |
| `out_alpha` | `servo_link.py` | 0.5 | output smoothing (lower = smoother) |
| slew, watchdog | ESP firmware | 3°/loop, 900 ms | max servo speed; re-center on signal loss |

**Protocol** (UDP :8770, one line per frame): `EYES,<Lpan>,<Ltilt>,<Rpan>,<Rtilt>,<gate>\n`,
angles 0–180, `gate ∈ {tracking, hold, neutral}`.

---

## Repository layout

| Path | Role |
|------|------|
| `tools/pupil_spike.py` | main runtime: camera → per-eye pupil → web UI → servo emit |
| `servo_link.py` | pupil signal → servo angle mapping + UDP sender (Pi) |
| `constants.py`, `filters.py` | eye-landmark definitions; numeric helpers |
| `web_ui_server.py` | MJPEG stream + browser page |
| `tools/servo_link_test.py` | synthetic bench sender for bring-up |
| `hardware/esp32s3_eye_follow.py` | ESP32 firmware: UDP → 4 servos |
| `hardware/esp32s3_servo_test.py`, `esp32s3_eye_circle.py` | servo bench tests |
| `hardware/secrets.example.py` | WiFi credentials template (copy to `secrets.py`) |
| `docs/PIPELINE.html` | full pipeline & algorithm documentation |
| `docs/PIVOT_PUPIL_MIRROR_2026-07-02.md` | design rationale (pupil mirroring, not gaze) |
| `run_pupil.sh`, `pupil.service`, `install_autostart.sh` | Pi autostart helpers |

---

## Status

- ✅ Per-eye pupil tracking, head-robust, no calibration — live web preview.
- ✅ Pi5 → ESP32 servo mapping over WiFi UDP; 4-servo eye follower with slew + watchdog.
- ✅ Verified end-to-end: link, per-eye mapping, direction, down-gaze emphasis, failsafe.
- 🔜 Field tuning of gains/limits per final mechanism; optional autostart-with-servos;
  active cooling on the Pi for long runs.
