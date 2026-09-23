# Track Eye — software-only per-eye pupil tracking

Track Eye captures a UVC camera stream, extracts both iris positions with MediaPipe FaceMesh, applies persisted output calibration, and serves an MJPEG browser view. A deployed shadow pipeline also measures head transform, face position, body/person position, and source transitions; the package includes the accepted 20-byte codec without connecting it to production output or hardware.

Servo mechanics, ESP32 transport/discovery, and actuator control remain outside this runtime. Fallback emission is explicitly disabled.

## Run

```bash
uv sync --frozen
.venv/bin/python -m track_eye.app \
  --device /dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0 \
  --web-host 0.0.0.0
```

Open `http://<pi-ip>:8080`.

Useful flags include `--width`, `--height`, `--fps`, `--fourcc`, `--no-mirror`, `--ema-alpha`, output gain/config flags, `--fallback-config`, `--no-head-shadow`, `--no-face-shadow`, `--no-body-shadow`, `--validation-dir`, `--validation-token`, and `--max-frames`.

## HTTP surface

- `/` — live camera, scaled output status, directional gain controls, neutral capture, persistence, and baseline control.
- `/frame.jpg` — long-polled latest JPEG used by the browser to avoid MJPEG backlog latency.
- `/stream.mjpg` — sequenced latest-frame MJPEG; slow clients may skip intermediate source frames.
- `/status.json` — camera, raw/output signals, baseline state, output calibration, shadow candidates/selection, stage timings, and validation status.
- `/healthz` — `200` only while capture is alive and the last frame is recent; otherwise `503`. It does not validate tracking quality.
- `/validation/start`, `/validation/stop`, `/validation/cleanup` — explicit pre-render JPEG validation capture controls. They are disabled unless the process receives `--validation-token`; callers currently supply that token in the JSON body. Run only on an isolated/trusted network and clean participant artifacts deliberately.

## Controlled baseline


Output mapping is applied after tracking/filtering, at the output boundary.
Defaults preserve the original Pi response:

```text
left/right:  raw x * 3.0
up:          raw y * 2.5
down:        raw y * 3.75 (2.5 * 1.5 effective)
soft limit:  1.5
```

The web tuner adjusts left/right/up/down independently. **Set neutral** records
one second of steady forward gaze per eye. **Save** writes
`output-calibration.json`; the service loads it automatically after reboot.
**Reset defaults** changes the live configuration but does not persist until
**Save** is pressed.

`TrackingResult` remains raw. Neutral offsets, directional gains, and soft
saturation exist only in `OutputTrackingResult`.
The production page at `http://<pi-ip>:8080` has a **Start baseline** button.
Press it while `FACE OK` is visible, then follow the on-screen target for all
phases. The production camera/tracker stays in one process; results are written
to `benchmark_data/` and the normal tracker resumes after completion.

For a standalone baseline process, run with the camera free:

```bash
.venv/bin/python tools/tracking_baseline.py \
  --device /dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0 \
  --web-ui-host 0.0.0.0
```

The protocol records adjacent center references before each gaze direction, then reports tracking rate, frame time, separation, center jitter, head drift, and output-gain analysis. JSON and text reports are written under ignored `benchmark_data/`.

A run below the configured per-phase tracking threshold is invalid. Output gain is diagnostic until the directional separation gates pass.

## Project context

- `AGENTS.md` is the mandatory entry point for development agents.
- `docs/PROJECT_FRAMEWORK.md` defines the current product invariant, architecture, contracts, evidence, and deployment protocol.
- `docs/PI5_DEPLOYED_STATE.md` records the validated live Pi service, dependencies, calibration, and baseline evidence.
- `docs/PIVOT_PUPIL_MIRROR_2026-07-02.md` is a historical decision log; its pivot to per-eye pupil mirroring remains valid, but its proposed next steps are stale.
- `docs/OPEN_RESEARCH_PROTOCOL_FALLBACK.md` records the accepted payload and source priority, deployed shadow implementation, and still-open quality, transport, and rig gates.

The local Git repository is the source for changes. `/home/pi5/track-eye` is the deployed runtime and is not a Git checkout. Preserve its `output-calibration.json` and `benchmark_data/` during ordinary source sync.

## Package layout

| Path | Role |
|------|------|
| `track_eye/camera.py` | by-id V4L2 ownership, negotiated-format validation, read-failure threshold |
| `track_eye/tracker.py` | FaceMesh lifecycle, eye geometry, canonical signal contract, EMA |
| `track_eye/baseline.py` | in-process browser-controlled baseline session |
| `track_eye/pupil_quality.py` | per-eye geometry/velocity diagnostics; quality gate remains uncalibrated |
| `track_eye/shadow.py` | pinned head transform, full-range face candidate, HOG body worker |
| `track_eye/fallback.py` | strict shadow config, monotonic source selector, accepted 20-byte codec |
| `track_eye/validation.py` | explicit mirrored pre-render JPEG capture and decision artifacts |
| `track_eye/output_tuning.py` | live gain/neutral state and atomic JSON persistence |
| `track_eye/rendering.py` | OpenCV overlays and display-only gain |
| `track_eye/web.py` | sequenced MJPEG, status, health, browser page |
| `track_eye/app.py` | single process composition root and signal lifecycle |
| `tools/tracking_baseline.py` | browser-guided quantitative baseline |
| `tests/` | behavioral math, contract, baseline, and stream tests |
| `AGENTS.md` | mandatory agent entry point and non-negotiable contracts |
| `docs/PROJECT_FRAMEWORK.md` | current architecture, authority hierarchy, evidence, and change protocol |
| `docs/PI5_DEPLOYED_STATE.md` | validated deployed runtime and calibration snapshot |
| `docs/OPEN_RESEARCH_PROTOCOL_FALLBACK.md` | accepted contract, deployed shadow implementation, open behavioral/transport/rig gates |
| `deploy/track-eye.service` | single systemd owner on Pi |
| `scripts/install_pi.sh` | rollback-backed Pi deployment cutover |

Legacy servo files remain isolated. `track_eye.app` does not call the payload encoder or send fallback targets; status must remain `disabled-shadow-only` until behavioral and hardware gates pass.
