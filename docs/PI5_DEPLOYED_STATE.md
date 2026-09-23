# Pi5 Deployed State

## 2026-09-23 fallback mechanism validation

Authoritative observations after deploying the initial-promotion fix:

- `track-eye.service` active and enabled; PID `2838` was the single canonical
  process and sole `/dev/video0` owner;
- `/healthz` returned HTTP 200 with fresh capture;
- fallback config checksum remained `33c86e3c36ab90f7`;
- output calibration checksum remained
  `8782caf8391b6dd3e9f8321d09b818f537293bb7d571e95ed5a75b045ebb4a2f`;
- emission remained `disabled-shadow-only`; calibration, head sign, and body
  selection remained disabled;
- fallback source SHA-256:
  `8c4ddfd34c6932750e8c7e73ed35e392073392465e3b882799ed3ccf426aa5ab`;
- fallback test SHA-256:
  `1e4d34fc8eae8aa2136e4b36d7d7431dd50c9c97ce4c9b1c7577683fc683ec9f`;
- 27/27 focused fallback tests and 47/47 full tests passed locally and on Pi;
- a deterministic property probe passed 20,000 randomized selector steps and
  20,000 codec cases identically on local and Pi;
- a 600-read, 29.95-second live empty-scene sample had zero HTTP/invariant
  failures, 476 source frames, 600 `NONE/INVALID` decisions, no future
  candidate timestamps, and 15.03/16.21/16.87 minimum/median/maximum reported
  fps;
- production `face_detected=false` implied all raw/output eyes were absent in
  all 600 samples; shadow decisions never replaced production output;
- HOG body remained invalid and unselected;
- `validation_data/` remained empty.

The audit found one selector defect: source `promote_s` was enforced only when
replacing an existing source, not during initial acquisition from `NONE`.
`FallbackSelector` now gates initial pupil and degraded candidates as well.
The regression failed before the fix and passes after it. Active-age
diagnostics are also clamped nonnegative for synthetic and live clocks.

No accepted timing value changed; `fallback-config.json` was not modified.
The service was intentionally recycled to load the corrected selector. No
post-restart service errors were present.

Rollback:
`/home/pi5/track-eye-rollbacks/20260923-161342-fallback-validation/`.

Decision: fallback priority, state, codec, freshness, hold, and transition
mechanisms pass software validation. Behavioral source validity, mappings,
timings, multi-person behavior, effective emission, transport, and rig remain
blocked.

## 2026-09-16 shadow deployment and post-deployment audit

Deployed shadow components:

- `track_eye/fallback.py`: six-state selector, strict schema-1 config, monotonic timing, bounded slew/hold machinery, tested 20-byte codec;
- `track_eye/shadow.py`: pinned Tasks Face Landmarker, full-range FaceDetection, HOG latest-frame body worker;
- `track_eye/pupil_quality.py`: per-eye geometry and calibrated-output-domain velocity diagnostics;
- `track_eye/validation.py`: explicit mirrored pre-render JPEG capture, manifest, decision rows, summary, cleanup;
- `track_eye/app.py`: shadow composition, status, overlay, validation endpoints;
- `fallback-config.json`: `emission_enabled=false`, `calibrated=false`, checksum `c79127d8a2f23827`;
- `models/face_landmarker.task`: SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`, 3,758,596 bytes.

The audit found and corrected defects that the initial 34-test report missed:

1. synchronous head/face candidates were timestamped after the selector's `now`, so they were rejected as future samples;
2. pupil loss collapsed independent left/right held targets onto one coordinate;
3. losing the old source while a better source was inside its promotion gate could transiently emit `INVALID`;
4. malformed config types could escape safe fallback, string booleans were coerced, and the checksum omitted `pupil_quality`;
5. the codec accepted non-finite coordinates and non-positive soft limits;
6. selector pupil targets used raw rather than calibrated output coordinates;
7. out-of-frame face boxes lacked separate raw/clipped diagnostics;
8. validation rows omitted selected targets, shutdown did not finalize active capture, and same-second sessions could collide.
9. status snapshots were assembled from separate tracking/output/shadow generations, so published face/output/shadow fields could belong to different frames; publication is now atomic under one lock with same-frame tracking/output/shadow and a published FrameHub sequence.

Post-fix evidence:

- local/Pi SHA-256 matched for the seven corrected source/test files (`track_eye/fallback.py`, `track_eye/pupil_quality.py`, `track_eye/shadow.py`, `track_eye/validation.py`, `track_eye/app.py`, `tests/test_fallback.py`, `tests/test_shadow_math.py`); `track_eye/tracker.py`, `track_eye/rendering.py`, `fallback-config.json`, and the pinned model also matched their deployed hashes;
- health returned 200 with one app process, one camera owner, and steady ~13.6–13.9 fps;
- live status selected real `FACE_POSITION_DEGRADED` and used `HELD_TARGET` across intermittent face-detector misses;
- visual browser smoke showed the live frame and shadow overlay;
- repeated samples showed `frame_sequence == sample_id` and internally consistent face/pupil/shadow fields (for example `FACE_POSITION_DEGRADED` while pupils were absent);
- saved output calibration `8782caf…` and benchmark artifacts remained unchanged;
- rollback: `/home/pi5/track-eye-rollbacks/20260916-084439-fallback-audit/`.

This proves shadow execution and mechanism safety checks only. Effective fallback emission remains disabled, the codec is not called by `track_eye.app`, and no ESP32 transport exists.

Release blockers:

- head axis/sign/neutral/range and pupil-quality thresholds require labeled participant data;
- face ROI/gain/direction and transition timing require labeled installation data;
- HOG body detection produced score `0.0` on observed visitor and empty frames, so detector suitability—not only calibration—is unresolved;
- multi-person continuity/handoff is absent;
- validation captures are JPEG, omit exposure/lighting metadata, and use unauthenticated LAN controls;
- ESP32 parser/transport/watchdog and mechanical direction/slew/safe-state require hardware-in-loop validation.

## Prior snapshot validated on 2026-09-15

## Authority and paths

- SSH: `ssh pi5` (`pi5.local`, user `pi5`, key authentication).
- Deployment root: `/home/pi5/track-eye`.
- Production package: `/home/pi5/track-eye/track_eye`.
- Runtime calibration: `/home/pi5/track-eye/output-calibration.json`.
- Baseline artifacts: `/home/pi5/track-eye/benchmark_data`.
- Installed unit: `/etc/systemd/system/track-eye.service`.
- The deployment root has no `.git`; use checksums, not Git commands, to identify deployed files.

The canonical source, tests, tools, service template, install script, packaging files, README, and `servo_link.py` matched their local checksums at validation time.

## Live service

`track-eye.service` is enabled and has been active since 2026-09-11.

```ini
[Service]
Type=simple
User=pi5
WorkingDirectory=/home/pi5/track-eye
ExecStart=/home/pi5/track-eye/.venv/bin/python -u -m track_eye.app --device /dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0 --web-host 0.0.0.0 --web-port 8080
Restart=on-failure
RestartSec=5
```

Observed live status:

- process listening on `0.0.0.0:8080`;
- `/healthz` returned HTTP 200;
- `capture_alive=true`, `healthy=true`;
- last-frame age about 3 ms at inspection;
- observed processing rate about 14.2–14.4 fps;
- baseline state `idle`;
- output tuner `dirty=false`, `load_error=null`.
- all 13 current unit tests passed on the Pi;
- HTTP smoke verified a fresh JPEG with a positive frame sequence while health remained 200.

Face state was false at inspection because no face was present. Face absence is not a camera health failure.

## Camera and runtime dependencies

- Stable device: `/dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0`.
- Resolved device: `/dev/video0`.
- Negotiated format: MJPG 1280x720 at 30 fps.
- Python 3.11.15.
- MediaPipe 0.10.14.
- OpenCV 4.13.0.
- NumPy 2.4.6.
- protobuf 4.25.9.

## Persisted output calibration

The live file is valid schema version 1 and is loaded cleanly:

```json
{
  "schema_version": 1,
  "gain": {
    "left": 4.0,
    "right": 4.0,
    "up": 3.5,
    "down": 3.45,
    "soft_limit": 1.5
  },
  "neutrals": [
    {
      "name": "eye_33_133",
      "x": -0.0727347096868543,
      "y": -0.17152310101834134
    },
    {
      "name": "eye_362_263",
      "x": -0.06194965835146265,
      "y": -0.16536567220835988
    }
  ]
}
```

These are runtime-owned values, not the code defaults. Ordinary source deployment must preserve this file.

## Latest inspected baseline evidence

Artifact: `tracking-baseline-20260907-141514.json`.

- tracking: 1134/1134 frames, 100%;
- camera read failures: 0;
- average processing rate: 16.94 fps;
- p95 frame time: 63.37 ms;
- eye `33_133`: minimum horizontal separation 1.59, minimum vertical separation 1.75;
- eye `362_263`: minimum horizontal separation 0.55, minimum vertical separation 1.37;
- normalized head drift for eye `362_263` was unavailable because its horizontal separation gate failed.

Interpretation: acquisition reliability was strong for that run. Robust directional separation and head-motion rejection were not fully validated for both eyes.

The artifact's gain section uses an older report shape and predates current output tuning. It is historical measurement evidence, not the source of the live calibration above.

## Legacy files on Pi

Root-level `rendering.py`, `web.py`, `tracking_baseline.py`, `test_rendering.py`, and `test_web.py` are older leftovers. The installed unit runs `track_eye.app`, so production imports the `track_eye/` package. Do not use the root-level copies as current source.

`pupil.log` is an old/non-UTF-8 artifact. Read current service output through `journalctl`.

## Operational checks

```bash
ssh pi5
sudo systemctl --no-pager --full status track-eye.service
sudo journalctl -u track-eye.service -n 100 --no-pager
curl -s http://127.0.0.1:8080/status.json
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/healthz
```

Run current tests without releasing the camera:

```bash
cd /home/pi5/track-eye
.venv/bin/python -m unittest discover -s tests -v
```

Do not run `tools/tracking_baseline.py` while the service owns the camera. For an explicitly requested standalone baseline, stop the service, run the baseline, then restart and revalidate service health.

## Deployment protocol

1. Change tracked local source first.
2. Run focused tests and a behavioral smoke path.
3. Sync only intended files.
4. Preserve `output-calibration.json` and `benchmark_data/`.
5. Compare checksums for deployed files.
6. Restart only when intentionally deploying runtime changes.
7. Check service status, startup journal, `/healthz`, `/status.json`, and changed behavior.
8. Update this snapshot.

Never store the Pi password in the repository or agent docs.
