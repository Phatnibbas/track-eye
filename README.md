# Track Eye — per-eye pupil tracking

Live demo that tracks **both pupils independently** from a USB camera on a
Raspberry Pi 5 and streams the result to a browser. Built for a head-in-box film
installation: a camera inside the box watches the viewer's eyes so that (later)
two servos can mirror each pupil independently, robustly to head movement.

## What it does

- Reads iris landmarks **directly** from MediaPipe FaceMesh (`refine_landmarks=True`),
  so whenever a face is visible **both pupils are always tracked** — no per-eye
  dropout.
- For each eye, computes the pupil offset inside the socket, **head-normalized**
  against that eye's own corners (survives head translation/rotation), then
  EMA-smooths it. Downward gaze gets a 1.5× boost (it reads short otherwise).
- The two eyes stay **independent** (no fusion) — the shape the servo stage needs.
- **No calibration.** Open the camera and go.
- UI: two Rinnegan-style gauges (LEFT / RIGHT EYE) showing where each pupil points,
  plus iris markers on the face, streamed as MJPEG to `http://<pi>:8080`.

## Run (on the Pi)

```bash
python tools/pupil_spike.py --web-ui-host 0.0.0.0
# then open http://<pi-ip>:8080 in a browser
```

Useful flags: `--width/--height`, `--fourcc MJPG`, `--camera-index`,
`--no-mirror`, `--max-frames N`.

## Layout

| File | Role |
|------|------|
| `tools/pupil_spike.py` | the demo (camera → per-eye pupil → Rinnegan UI → stream) |
| `constants.py` | eye-landmark definitions (corners, lids, iris rings) |
| `filters.py` | small numeric helpers (`clamp`) |
| `web_ui_server.py` | MJPEG stream + browser page |
| `docs/PIVOT_PUPIL_MIRROR_2026-07-02.md` | why this approach (pupil mirroring, not gaze direction) |

Servo control, deployment, and any IR upgrade are intentionally out of scope until
the installation spec is settled.
