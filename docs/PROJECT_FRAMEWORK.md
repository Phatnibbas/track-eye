# Track Eye Project Framework

This is the current operating framework for development agents. It is derived from the tracked repository, the files deployed under `/home/pi5/track-eye`, the live systemd unit, the live HTTP status, the persisted calibration, and the latest available baseline artifact.

## 1. Authority hierarchy

Use evidence in this order:

1. **User-stated installation goal**: authoritative product intent.
2. **Live Pi runtime**: authoritative deployed behavior and runtime-owned state.
3. **Tracked local repository**: authoritative source for the next change.
4. **Tests**: executable contracts, but narrower than the complete product intent.
5. **Generated baseline reports**: historical measurements tied to their recorded configuration and schema.
6. **Historical docs and root-level Pi leftovers**: context only; never treat them as current runtime code.

The Pi deployment directory is not a Git checkout. Never infer deployment identity from Git while logged into Pi. Compare explicit file checksums instead.

## 2. Product invariants

The installation has two operating goals with explicit priority:

1. **Engagement/liveness:** while a visitor is detected, the artwork must keep producing responsive eye targets derived from that visitor. Loss of pupil or face landmarks alone must not make both artwork eyes freeze.
2. **Best available in-scope motion source:** when reliable, mirror independent eye-in-head pupil motion for both eyes. Otherwise degrade to head orientation, then face position; use `INVALID` only after every qualified in-scope source and bounded hold expire.

Required behavior:

- retain two independent horizontal/vertical eye signals in normal pupil mode;
- label the active source so pupil, head, and face signals are never confused;
- switch to the best available visitor-derived fallback when pupil tracking becomes unusable;
- permit both artwork eyes to share a target in degraded modes;
- use `INVALID` because no usable visitor signal exists, not merely because iris or FaceMesh failed;
- bound hold time and transition discontinuity between modes;
- keep camera and tracking usable without servo hardware;
- measure responsiveness, false activation, jitter, latency, and source transitions under installation conditions.

The old appearance-gaze/ONNX direction remains rejected as the normal pupil-mirroring implementation. Explicitly labeled head/face fallback exists to keep the installation responsive. Owner scope as of 2026-09-23 is `PUPIL -> HEAD -> FACE -> HELD -> INVALID`; body/person diagnostics and codec state remain in the codebase but `body_enabled=false` and body is excluded from current validation and rollout.

## 3. Runtime architecture

```text
UGREEN UVC camera (one V4L2 owner)
  -> optional horizontal mirror (enabled on Pi)
  -> one mirrored, pre-render frame
       |-> EyeTracker (legacy FaceMesh) -> raw TrackingResult
       |     |-> OutputTuner -> OutputTrackingResult
       |     |     `-> calibrated pupil targets for shadow selection
       |     `-> PupilQualityMonitor -> per-eye geometry/velocity diagnostics
       |-> HeadPoseShadow (Tasks Face Landmarker transform, synchronous)
       |-> FacePositionShadow (full-range FaceDetection, synchronous)
       |-> BodyPositionWorker (OpenCV HOG, latest-frame queue depth one)
       `-> ValidationSession (explicit-start pre-render JPEG capture only)
  -> FallbackSelector -> labeled shadow decision
  -> existing OutputTrackingResult -> renderer -> FrameHub -> WebUIServer
```

`track_eye.app` owns composition and lifecycle. The selector consumes monotonic timestamps after synchronous candidate inference, so newly produced candidates are not rejected as “future” samples. Pupil targets entering the selector are the calibrated `OutputTrackingResult` coordinates; raw pupil geometry remains diagnostic.

The deployed runtime is still **shadow-only**. The fallback decision is visible in status, overlays, and validation artifacts, but does not replace `OutputTrackingResult`, invoke the 20-byte encoder, or send data to hardware. Configuration rejects `emission_enabled=true` until an output integration exists.

## 4. Module boundaries

| Layer | Files | Owns | Must not own |
|---|---|---|---|
| Capture | `track_eye/camera.py` | device open/read/close, negotiation checks, read-failure threshold | tracking, output gain, web state |
| Pupil measurement | `track_eye/tracker.py` | FaceMesh lifecycle, local eye axes, raw normalized signal, EMA, eye geometry | user neutral, fallback selection, servo mapping |
| Output mapping | `track_eye/output.py`, `output_tuning.py` | neutral, directional gain, soft limit, persistence | mutation of raw `TrackingResult` |
| Pupil quality | `track_eye/pupil_quality.py` | per-eye geometry and velocity observations | claiming usability before labeled thresholds |
| Degraded candidates | `track_eye/shadow.py` | pinned head transform, full-range face box, asynchronous body candidate, candidate diagnostics | source priority, transport, mechanical mapping |
| Source selection and payload | `track_eye/fallback.py` | source/state enums, config validation, monotonic selector, 20-byte codec | detector inference, transport, ESP32 mechanics |
| Validation capture | `track_eye/validation.py` | explicit-start pre-render JPEGs, manifest, decision rows, retention cleanup | a second camera handle, automatic gate approval |
| Measurement protocol | `track_eye/baseline.py`, `tools/tracking_baseline.py` | timed pupil phases and historical evidence | silent algorithm changes |
| Presentation | `track_eye/rendering.py` | OpenCV overlays and gauges | changing signal semantics |
| HTTP/UI | `track_eye/web.py` | bounded latest-frame delivery, status, health, action dispatch | camera ownership or tracking math |
| Composition | `track_eye/app.py` | ordering, state publication, shutdown | hidden alternate pipelines |
| Deployment | `deploy/`, `scripts/` | one systemd service and cutover | runtime feature logic |
| Legacy hardware | `servo_link.py`, `tools/servo_link_test.py` | isolated UDP/servo bring-up | production imports without an explicit integration decision |

## 5. Signal contracts

### Raw pupil tracking

`TrackingResult` remains raw and unscaled. It contains a wall-clock timestamp, `face_detected`, exactly two `EyeSignal` values or `None`, and inference time. `face_detected == False` implies `eyes is None`; stale eyes are never published. EMA state survives temporary face loss, so reacquisition can initially blend with pre-loss state.

Each `EyeSignal` contains canonical `x/y`, local `raw_h/raw_v`, contour, eye/iris centers, iris radius, eye width, eyelid aperture, iris-inside-lid ratio, lid overflow, and local axes.

### Calibrated output

`OutputTrackingResult` is derived in this order:

1. subtract the saved per-eye neutral;
2. apply sign-dependent horizontal and vertical gains;
3. apply smooth soft limiting.

The selector's pupil coordinates now use this calibrated output domain. Pupil geometry and normalized local displacement remain raw diagnostic fields. Degraded head/face/body targets are also expressed in the output target domain, but their mappings and usable range are not calibrated.

### Fallback observations and decisions

Every degraded `Candidate` carries source, monotonic timestamp, target, validity, latency, and Pi-internal quality fields. The selector rejects stale, future, non-finite, and source-key-mismatched candidates. Current pupil compatibility mode requires both output eyes; independent quality observations exist, but no accepted per-eye usability gate exists.

Priority is fixed:

```text
TRACKED_PUPIL
  -> HEAD_POSE_DEGRADED
  -> FACE_POSITION_DEGRADED
  -> BODY_POSITION_DEGRADED
  -> HELD_TARGET
  -> INVALID
```

Pupil mode preserves two independent targets. Degraded sources intentionally share one target. A held pupil target preserves both independent coordinates rather than collapsing them to one eye or their average. Promotion/demotion and hold use monotonic elapsed time. Current numerical timings are placeholders pending participant and rig validation.

### Persisted configuration

`output-calibration.json` is runtime-owned schema 1 state and must be preserved during source deployment.

`fallback-config.json` is schema 1 shadow configuration. Parsing is strict for booleans, numbers, ROI length, bounds, and unknown fields; malformed files fall back to safe shadow defaults. Its checksum includes every serialized field, including `pupil_quality`. Current deployed checksum is `33c86e3c36ab90f7`.

`emission_enabled=true` is rejected because no effective output/transport integration exists. `calibrated=false`, `pupil_mode=compatibility`, and `head_sign_validated=false` remain deployed.

## 6. Frame and health contracts

`FrameHub` stores one JPEG, not a queue. Consumers asking after sequence `N` receive the newest sequence greater than `N`; intermediate frames may be skipped. This is intentional bounded-memory, low-latency behavior.

`/healthz` is healthy only when capture is marked alive and the last successfully published frame is at most two seconds old. Face absence does not make capture unhealthy.

HTTP control bodies are JSON objects capped at 8192 bytes. Invalid values return 400; persistence errors return 500.

## 7. Baseline evidence rules

The 13-phase protocol records adjacent center references before left/right/up/down eye poses, then center plus four head-motion poses. It evaluates:

- per-phase tracking rate;
- camera read failures;
- mean and spread per axis and eye;
- directional separation;
- horizontal/vertical span;
- center jitter relative to span;
- head drift relative to usable gaze span;
- diagnostic vertical gain ratios.

A tracking rate alone does not validate pupil mirroring. Directional separation and head-motion leakage remain independent gates.

Latest inspected historical run (`2026-09-07 14:15:14 +07`):

- 1134/1134 frames tracked;
- zero camera read failures;
- average 16.94 fps, p95 63.37 ms/frame;
- eye `33_133`: minimum horizontal separation 1.59, vertical 1.75;
- eye `362_263`: minimum horizontal separation only 0.55, vertical 1.37;
- normalized head drift could not be computed for `362_263` because its horizontal separation gate failed.

Conclusion: face/iris acquisition was strong in that run, but robust two-eye directional mirroring was not fully proven. The report predates the current output-tuning schema; its gain section must not be interpreted as the current persisted calibration.

## 8. ESP32 boundary and implementation status

The accepted `EyeTargetFrame` is an atomic 20-byte network-order payload with magic/version/type, 32-bit sample ID, independent per-slot states, a zero reserved field, and four signed fixed-point coordinates. `track_eye/fallback.py` now implements and tests the codec, including exact canonical bytes, all six states, malformed-frame rejection, `INVALID` zero enforcement, non-finite input rejection, positive soft-limit enforcement, and modulo-2³² sample IDs.

This is a **library implementation only**:

- `track_eye.app` does not call the encoder;
- no packet is emitted;
- no transport, framing, address, authentication, acknowledgement, restart handshake, cadence, or watchdog is selected;
- no ESP32 parser or firmware exists in this project;
- mechanical side, sign, center, travel, slew, current, and safe state remain ESP32/rig responsibilities.

The Pi boundary remains: final calibrated desired targets plus per-slot state and sample ID. Raw landmarks, detector confidence, calibration values, servo units, and mechanical geometry never enter the payload.

The deployed slot mapping remains `left_slot = eye_33_133`, `right_slot = eye_362_263`. These are processed-image/display slots, not anatomical eye names. Mechanical correspondence is unvalidated.

## 9. Deployed state

Revalidated on 2026-09-23:

- host `pi5`, deployment `/home/pi5/track-eye`;
- service active and enabled with one app process and one `/dev/video0` owner;
- `/healthz` reported `healthy=true` with a fresh frame;
- UGREEN camera negotiated MJPG 1280×720 at 30 fps;
- recent journal output showed about 13.3–14.5 application fps while shadow stages were active;
- Python 3.11.15, MediaPipe 0.10.14, OpenCV 4.13.0, NumPy 2.4.6, protobuf 4.25.9;
- pinned `models/face_landmarker.task`, SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`, size 3,758,596 bytes;
- fallback configuration checksum `33c86e3c36ab90f7`, emission disabled, calibration false, body selection disabled;
- 46/46 tests passed locally and on the Pi;
- critical runtime source, tests, config, model, and framework files matched local/Pi checksums except a one-line wording drift in this research document, which this audit reconciles;
- `validation_data/` was empty; the deployed unit does not pass `--validation-token`, so validation endpoints are intentionally disabled;
- rollback: `/home/pi5/track-eye-rollbacks/20260916-094907-blocker-sweep/`.

Live shadow evidence establishes execution, not behavioral accuracy. The journal showed pupil, face, held, and none transitions; one inspected status selected `FACE_POSITION_DEGRADED` while production pupil output was absent. This was not a labeled episode and does not validate mapping direction, range, distance, lighting, or multi-person behavior. HOG body detection remained invalid with score `0.0`.

Persisted output calibration remains unchanged: horizontal gain `4.0/4.0`, vertical gain `3.5/3.45`, soft limit `1.5`, two saved neutrals, clean tuner status. See `docs/PI5_DEPLOYED_STATE.md`.

## 10. Canonical tree and legacy files

Canonical authoring paths:

```text
track_eye/          production Python package
tests/              current behavioral tests
tools/              standalone measurement/bring-up tools
deploy/             systemd unit
scripts/            deployment cutover
README.md            operator entry point
AGENTS.md            agent entry point
docs/PROJECT_FRAMEWORK.md
                    architecture, invariants, authority
docs/PI5_DEPLOYED_STATE.md
                    deployed snapshot and operations
docs/OPEN_RESEARCH_PROTOCOL_FALLBACK.md
                    accepted payload, shadow implementation, open gates
```

The Pi contains root-level `rendering.py`, `web.py`, `tracking_baseline.py`, `test_rendering.py`, and `test_web.py`. These are older leftovers. Systemd imports the `track_eye/` package from its working directory, not those root-level files. Do not copy their older display-gain or HTTP behavior back into the package.

`docs/PIVOT_PUPIL_MIRROR_2026-07-02.md` is a historical decision log. Its product correction remains relevant; its proposed next steps and file inventory are stale.

## 11. Safe change and deployment protocol

1. Re-read relevant local source and the live Pi state affected by the change.
2. Preserve the product and signal invariants above.
3. Change tracked local source; do not author only on Pi.
4. Run focused tests plus a behavioral smoke path.
5. Sync only intended files. Preserve `output-calibration.json` and `benchmark_data/` unless explicitly changing them.
6. Compare local/Pi checksums for deployed files.
7. Restart `track-eye.service` only for an intentional deployment.
8. Verify service status, journal startup, `/healthz`, `/status.json`, and the changed behavior.
9. Refresh deployed-state docs after source, unit, dependency, calibration, or hardware changes.

Do not run the standalone baseline while production owns the camera. Stop the service first only when a baseline run is explicitly requested, then restore and verify the service afterward.

## 12. Known structural risks

### Release blockers for fallback emission

- Head target axes/signs, neutral, range, jitter, and responsiveness are unvalidated. The status field `head.valid` currently means a proper transform exists; the corresponding target candidate remains invalid while `head_sign_validated=false`.
- Pupil-quality features are measured, but no thresholds are fitted. `pupil_mode=gated` must not be treated as a calibrated quality gate.
- Face detection visibly flickers in the inspected occluded/downward pose. ROI/gain and direction are uncalibrated despite bounded boxes and targets.
- OpenCV HOG produced score `0.0` on both visitor and empty observations. Body fallback therefore has no demonstrated visitor recall; this is a detector-suitability blocker, not merely a threshold-tuning blocker.
- `TrackedVisitor` only logs the nearest center across already-selected source outputs. Face/body detectors still choose one best detection before that step, so true multi-person acquisition, box continuity, retention, and handoff remain absent.
- `max_held_s` now enforces a software absolute hold bound, but promotion, demotion, hold, slew, and absence values remain unvalidated placeholders.
- Slew limiting is per output slot. After a switch from independent pupil targets to one shared degraded-source target, the two effective outputs can differ transiently while converging; Gate 3 must decide whether that transition is acceptable on the rig.
- No participant-split evaluation exists for distance, dim/backlit/glare, glasses, partial occlusion, facing away, seated/standing posture, entry/exit, or multi-person scenes.
- The codec is not connected to application output, and there is no ESP32 transport, parser, sequence handling, watchdog, or rig test.

### Validation and operational risks

- Validation “raw” frames are mirrored pre-render frames encoded as JPEG, not lossless sensor frames.
- The manifest accepts caller-supplied exposure/lighting metadata, but does not read actual camera exposure controls; missing metadata still defaults to `"unlabeled"`.
- Validation controls require a JSON-body token when configured. The deployed systemd unit provides no token, so controls are disabled rather than operationally authenticated.
- A normal health response proves camera/frame freshness only, not fallback quality, detector availability, or emission safety.
- Tasks Face Landmarker plus full-range FaceDetection lowers production throughput from the historical pupil-only baseline; no accepted minimum FPS gate exists.

### Pre-existing risks

- Baseline analysis is duplicated between integrated and standalone implementations.
- Integrated baseline metadata/analysis does not capture every live CLI value and uses default gain in some analysis paths.
- `draw_face_marker()` calculates a vector tip without drawing it.
- Face loss does not reset EMA.
- Current historical pupil evidence does not fully prove low head coupling and strong horizontal separation for both eyes.

## 13. Current fallback evidence ledger — 2026-09-23

| Capability | State | Evidence | Decision |
|---|---|---|---|
| Accepted priority and six state values | Implemented in selector/codec | permanent 16-combination sweep (`test_full_availability_sweep_follows_priority`) plus targeted priority tests | **PASS for logic** |
| Initial source promotion | Corrected: acquisition from `NONE` now obeys source `promote_s` | regression covers candidate and pupil paths; failed before fix, passed after | **PASS for mechanism; durations unvalidated** |
| Monotonic stale, promotion, demotion, hold, and slew machinery | Implemented | 27 focused tests plus deterministic 20,000-step randomized selector probe on local and Pi | **PASS for mechanism; timings unvalidated** |
| Atomic status publication | Single lock, same-frame tracking/output/shadow | 600 live samples had `frame_sequence == sample_id` | **PASS** |
| Independent pupil targets survive loss/hold | Corrected and tested | regression test with asymmetric left/right targets | **PASS** |
| Better-source promotion while old source disappears | Corrected to hold instead of transient `INVALID` | regression test | **PASS** |
| Synchronous candidate timestamp ordering | Selector clock sampled after inference | 600 live samples had no future candidate ages | **PASS** |
| Candidate/config numeric safety | Strict parsing and finite/source checks | focused failure probes and randomized selector input | **PASS** |
| Config reproducibility | Canonical checksum includes `pupil_quality` | checksum regression test; live `33c86e3c36ab90f7` | **PASS** |
| 20-byte codec | Implemented as a library | canonical vector, all states, malformed/non-finite cases, deterministic 20,000-case codec probe on local and Pi | **PASS; not integrated** |
| Production pupil boundary | Existing render/output path retained | app/output hashes unchanged; 600 no-face live samples published no stale production eyes | **PASS for compatibility smoke** |
| Head transform candidate | Real pinned Tasks model, proper-rotation/quaternion diagnostics | live transform and timing | **FEASIBLE; target gate blocked** |
| Face-position candidate | Real full-range detector, clipped/raw box diagnostics | prior live selection plus validation capture | **RUNS; mapping/accuracy blocked** |
| Body-position candidate | HOG latest-frame worker | live timing but score `0.0`; config and diagnostics keep it unselected | **FAILS suitability evidence** |
| Pre-render validation capture | Implemented and previously smoke-tested | manifest + 156 frames + decision rows, then cleanup | **PASS for mechanism; Gate 1 readiness blocked** |
| Effective fallback emission | Deliberately absent and config-rejected | grep found codec calls only in codec tests; live status `disabled-shadow-only` | **BLOCKED** |
| Transport/ESP32/rig | Absent | no hardware path | **NOT STARTED** |

The 2026-09-23 live shadow sample covered 600 HTTP status reads over 29.95 seconds in an empty scene: 600 `NONE/INVALID`, zero invariant failures, zero HTTP failures, 476 source frames, and 15.03/16.21/16.87 minimum/median/maximum reported fps. It validates empty-scene mechanism behavior only, not visitor coverage or source accuracy.

## 14. Remaining gate framework

Work proceeds in this order. A later gate cannot compensate for a failed earlier one.

### Gate 0 — shadow mechanism and rollback

**State: passed.** Required evidence is now present: one camera owner, pinned model, strict disabled-emission config, source-state diagnostics, selector/codec tests, live shadow execution, explicit capture tooling, matching deployment checksums, and rollback.

### Gate 1 — validation protocol readiness

**State: framework defined; acceptance collection blocked.** Execution contract: `docs/GATE1_PROTOCOL_TEMPLATE.md`.

The current manifest fields and token gate are useful mechanism pieces, not a completed protocol. Required work remains: strict metadata instead of `"unlabeled"` defaults, opaque participant and visit IDs, participant-level split enforcement, actual camera-control readback, operational token configuration, auditable specific-session deletion, and frozen numerical metrics/confidence/sample-count targets. Do not collect acceptance data until every Gate 1 exit criterion passes.

### Gate 2 — source validity

**State: blocked.** Validate the three in-scope sources independently before tuning selector timing:

- **Pupil:** label each eye usable/unusable across gaze, blink, one-eye occlusion, glasses, distance, and lighting. Establish horizontal/vertical separation per eye, head-motion leakage, jitter, latency, false-accept/false-reject behavior, and an explicit one-eye-loss policy. Fit thresholds on `tuning`; freeze and verify on `heldout`.
- **Head:** label neutral and left/right/up/down under the deployed mirrored path. Establish axes/signs, monotonicity, usable range, jitter, eyes-only leakage, transform availability, and response latency. Freeze neutral/scale before setting `head_sign_validated=true`.
- **Face:** measure recall, empty-scene false activation, confidence threshold, box stability, mapping direction, installation ROI/gain, latency, and reacquisition across distance, lighting, pose, and partial occlusion. Specify visitor acquisition/retention/handoff using spatial continuity only.
- **Body:** deferred by owner scope; keep `body_enabled=false`. HOG diagnostics are not a release deliverable for this slice and must not be silently promoted.

### Gate 3 — selector and target calibration

**State: blocked by Gate 2.** Freeze pupil/head/face mappings first, then tune the active priority `PUPIL -> HEAD -> FACE -> HELD -> INVALID`, promotion, demotion, absolute hold bound, absence expiry, and per-slot slew using complete visit episodes. Verify no avoidable `INVALID` while a qualified in-scope source exists, bounded transition discontinuity, bounded frozen duration, no one-frame source flapping, and the accepted one-eye-loss behavior.

### Gate 4 — held-out software shadow acceptance

**State: not started.** Freeze code, models, configuration, checksums, and product thresholds before the held-out run. Report per-condition and worst-condition results. A global average cannot hide a failed distance, lighting, occlusion, or participant stratum. Failure means return to Gate 2 or 3; do not enable emission.

### Gate 5 — ESP32 and rig integration

**State: not started.** Select transport and threat model; implement an independent ESP32 parser; test canonical, malformed, duplicate, stale, out-of-order, wrap, restart, and outage cases; measure link latency/jitter/loss; define watchdog safe state; validate mechanical slot mapping, signs, centers, travel limits, slew, and power-loss behavior.

### Gate 6 — staged production rollout

**State: not started.** Connect the accepted selector decision to the codec only after Gates 1–5 pass. Roll out one degraded source at a time: head, then face. Body remains disabled and outside this rollout. Compare effective output with frozen shadow evidence, preserve rollback, and keep transport/mechanical faults from altering Pi tracking semantics.
