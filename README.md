# Track Eye — pupil tracking and external Delta adapter

Track Eye captures a UVC camera stream, extracts both iris positions with
MediaPipe FaceMesh, applies output calibration and serves an MJPEG browser view.
The canonical `track_eye/` app also measures fallback candidates in shadow mode;
its binary codec is not connected to production output or hardware.

A separate `delta_bridge/` adapter consumes the camera app's HTTP data and sends
text-protocol targets to Delta hardware. Camera and serial have separate unique
service owners; the old sender has been restored under explicit owner approval.

## Current native-ROI acquisition and diagnostics — 2026-10-17

Production is **`b8387c0` plus diagnostic UI and native-ROI acquisition**.
The existing full-range detector guides cold/reacquisition through a selected,
1.8× padded native crop. One FaceMesh call per frame; crop landmarks map back
to original pixels before unchanged aperture-v1 measurement. Healthy tracking
retains its full-frame/ROI path. FACE fallback remains independent of pupil
availability; the0.6s retained box is geometric association, not person identity.

Web separates detector, FaceMesh landmarks and per-display-slot pupil geometry,
then **pre-EMA → raw-after-EMA → tuned output**. Geometry availability and detector
score are not calibrated pupil confidence; internal shadow is not hardware
source. No models/thresholds, calibration units or visitor pipeline changed.
Controlled small-photo replay improves acquisition, not measured2m acceptance.
Vertical mapping remains sensitive to lid aperture.

Saved gain3.9/3/3.45/3.7, limit1.0, two neutrals and sender pin2f797a4c… are
preserved. Both services are running; old sender remains `observe-only-owner-test`,
not unattended fail-closed readiness control. Its existing policy issued one
acknowledged bounded CLEAR after a startup FAULT rejection; final resumed session
was clean. No HOME/reset/flash. Read
[`docs/PI5_DEPLOYED_STATE.md`](docs/PI5_DEPLOYED_STATE.md) for exact identity,
verification, backups and RAM/reboot limitations.

The simplified installation design is in
[`docs/PROJECT_FRAMEWORK.md`](docs/PROJECT_FRAMEWORK.md#installation-redesign--design-only).
It is not the deployed algorithm: the restored app still renders pupil output
and measures internal fallback in shadow mode. Deployment changes must preserve
Pi-owned calibration/data and unique device ownership. Inspect fresh sender
and robot state before any later motion work; stopping a sender is not motor STOP.

## Camera application reference (not a sync/recovery procedure)

The commands below describe a separate camera run, only with the deployed
camera owner stopped under a separately approved operation. Do not run them
against the currently owned device as part of preservation.

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
Press it while FaceMesh shows `Landmarks available`, then follow the on-screen
target for all phases. The production camera/tracker stays in one process; results are written
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

The local Git repository is the source for the next change. `/home/pi5/track-eye`
and `/home/pi5/track-eye-delta` are deployed runtime directories, not Git
checkouts. Preserve runtime-owned calibration, benchmarks, live Delta config,
state and logs rather than overwriting them from historical profiles.

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
| `delta_bridge/` | external HTTP-to-Delta text-protocol adapter, separate from internal fallback |
| `tools/delta_*.py` | Delta validation/runtime tools; presence is not permission to run hardware commands |
| `tests/` | tracker and Delta behavioral tests, protocol tests and fixtures |
| `firmware/` | preserved board-source reference; not an instruction or permission to flash |
| `config/` | named historical Delta JSON profiles, not authoritative deployed config |
| `AGENTS.md` | mandatory agent entry point and non-negotiable contracts |
| `docs/PROJECT_FRAMEWORK.md` | current architecture, authority hierarchy, evidence, and change protocol |
| `docs/PI5_DEPLOYED_STATE.md` | validated deployed runtime and calibration snapshot |
| `docs/OPEN_RESEARCH_PROTOCOL_FALLBACK.md` | accepted contract, deployed shadow implementation, open behavioral/transport/rig gates |
| `deploy/track-eye.service` | canonical camera service unit |
| `deploy/track-eye-delta.service` | external sender service unit |
| `deploy/pi5-snapshot-2026-10-17/` | preserved live configuration/calibration and dated runtime evidence |
| `scripts/install_pi.sh` | rollback-backed Pi deployment cutover |

Legacy servo files remain isolated. `track_eye.app` does not call the payload
encoder or send fallback targets; internal status remains `disabled-shadow-only`.
The separate Delta service does emit hardware data under the recorded external
policy. Neither reference firmware nor successful LOOK echoes certify motor
completion, mechanical direction, tracking accuracy or unattended safety.
