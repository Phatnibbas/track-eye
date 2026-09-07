# Track Eye — software-only per-eye pupil tracking

Track Eye captures a UVC camera stream, extracts both iris positions with MediaPipe FaceMesh, normalizes each eye in its own socket, and serves an MJPEG browser view. The stable output is an unscaled per-eye `TrackingResult`.

Servo, mechanical calibration, ESP32 discovery, UDP, and actuator control are intentionally outside this runtime.

## Run

```bash
uv sync --frozen
.venv/bin/python -m track_eye.app \
  --device /dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0 \
  --web-host 0.0.0.0
```

Open `http://<pi-ip>:8080`.

Useful flags: `--width`, `--height`, `--fps`, `--fourcc`, `--no-mirror`, `--ema-alpha`, `--output-horizontal-gain`, `--output-vertical-up-gain`, `--output-vertical-down-gain`, `--max-frames`.

## HTTP surface

- `/` — camera overlay and scaled software output status.
- `/stream.mjpg` — sequenced MJPEG; each client receives each source frame once.
- `/status.json` — camera negotiation, frame age, FPS, raw signals, output signals, and gains.
- `/healthz` — `200` only while capture is alive and the last frame is recent; otherwise `503`.

## Controlled baseline


Output mapping is applied after tracking/filtering, at the output boundary:

```text
left/right:  raw x * 3.0
up:          raw y * 2.5
down:        raw y * 3.75 (2.5 * 1.5 effective)
```

`TrackingResult` remains raw. `/status.json` exposes `raw_left/raw_right` and
`output_left/output_right` separately.
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

## Package layout

| Path | Role |
|------|------|
| `track_eye/camera.py` | by-id V4L2 ownership, negotiated-format validation, read-failure threshold |
| `track_eye/tracker.py` | FaceMesh lifecycle, eye geometry, canonical signal contract, EMA |
| `track_eye/baseline.py` | in-process browser-controlled baseline session |
| `track_eye/rendering.py` | OpenCV overlays and display-only gain |
| `track_eye/web.py` | sequenced MJPEG, status, health, browser page |
| `track_eye/app.py` | single process composition root and signal lifecycle |
| `tools/tracking_baseline.py` | browser-guided quantitative baseline |
| `tests/` | behavioral math, contract, baseline, and stream tests |
| `deploy/track-eye.service` | single systemd owner on Pi |
| `scripts/install_pi.sh` | rollback-backed Pi deployment cutover |

Legacy servo files remain in the repository for a later integration phase but are not imported by `track_eye.app` or the production service.
