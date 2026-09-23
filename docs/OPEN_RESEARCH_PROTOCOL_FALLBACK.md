# Open Research: Pi5→ESP32 Protocol and Tracking Fallback

Status: **OUTPUT PAYLOAD AND FALLBACK PRIORITY ACCEPTED; CODEC + SHADOW PIPELINE DEPLOYED 2026-09-16; BEHAVIORAL GATES, EFFECTIVE EMISSION, TRANSPORT, AND RIG OPEN**

This document records the accepted Pi5→ESP32 output boundary, accepted pupil → head pose → face position → body/person priority, deployed shadow implementation, and still-open behavioral validation plus transport/framing work. Separate accepted contract, mechanism tests, live shadow execution, labeled behavioral validation, and hardware validation.

## Research discipline

- Treat the section labeled `Owner decision — transport-independent output contract` and the explicitly accepted fallback source priority as product decisions. They do not approve unvalidated thresholds, mappings, models, implementation, hardware, transport, or deployment changes.
- Do not silently promote any remaining proposal into a contract.
- Do not claim head pose is pupil tracking.
- Do not claim a fallback works at 2 m or in low light without measurements under those conditions.
- Do not infer behavior from the circular UI gauge; it is presentation only.
- Do not use historical baseline results as proof of current long-distance or low-light behavior.
- Record commands, source paths, hardware conditions, sample counts, failure modes, latency, and raw artifacts.
- Preserve the deployed pupil output and keep fallback emission disabled during research. Shadow deployment is reversible and must not be confused with production acceptance.
- Avoid ESP32/rig or effective-output changes until behavioral gates are reviewed and explicitly accepted.

## Question A — Pi5 to ESP32 output payload and transport

### What is known

The current production pipeline produces `OutputTrackingResult` with two per-eye `(x, y)` values. These values are dimensionless normalized coordinates after neutral subtraction, directional gains, and soft limiting. They are not radians, degrees, pixels, servo angles, velocity, or deltas.

The current UI gauge is a Cartesian visualization. Its circle does not define a polar protocol or an angular output.

`servo_link.py` contains an older UDP text packet:

```text
EYES,<Lpan>,<Ltilt>,<Rpan>,<Rtilt>,<gate>\n
```

That packet carries integer actuator angles and is hardware-specific legacy material. It is not yet the approved contract for the current output pipeline.

The production `track_eye.app` does not currently send anything to an ESP32.

### Owner decision — transport-independent output contract

Accepted by the project owner on 2026-09-16. This decision fixes what the Pi publishes and the canonical payload representation. It does **not** select UDP, TCP, USB CDC, UART, or any other transport; it does not define servo geometry or motor control.

The boundary is:

```text
Pi camera/tracking/calibration
  -> final normalized desired position for two display eyes
  -> EyeTargetFrame
  -> transport/framing layer
  -> ESP32 mechanical mapping and actuator control
```

The ESP32 must not need camera coordinates, face landmarks, neutral offsets, gain values, MediaPipe state, or knowledge of how the Pi produced the target.

#### Logical content

Each `EyeTargetFrame` is one atomic snapshot containing:

- `schema_version`;
- `message_type`;
- monotonically incrementing `sample_id`;
- `left_slot` state plus `(x, y)`;
- `right_slot` state plus `(x, y)`.

Channel identity is fixed at the Pi boundary, but the terms `left` and `right` below mean **processed-image/display slots**, not anatomical eye names:

- `left_slot` is current `OutputTrackingResult.eyes[0]`, sourced from tracker channel `eye_33_133`;
- `right_slot` is current `OutputTrackingResult.eyes[1]`, sourced from tracker channel `eye_362_263`.

The deployed app horizontally mirrors the camera frame before FaceMesh. MediaPipe identifies landmark group `33/133` as the subject's anatomical right eye and `362/263` as the subject's anatomical left eye. Therefore the current `left_slot` is the processed-image-left/display-left channel and is **not** the subject's anatomical left eye. The ESP32 payload must preserve these two logical slots; the mechanical left/right correspondence is a separate installation mapping and is not validated by the Pi software.

The ESP32 sees only `left_slot` and `right_slot`; MediaPipe landmark identities remain Pi-internal.

Coordinates are final desired positions in the two processed-image/display slots:

- `x = 0`, `y = 0`: calibrated neutral;
- `x = -1`: logical full-scale toward processed/display-left;
- `x = +1`: logical full-scale toward processed/display-right;
- `y = -1`: logical full-scale up;
- `y = +1`: logical full-scale down.

“Full-scale” describes the normalized command boundary only. It does not define a physical angle, travel limit, linkage position, or motor endpoint.

The range is fixed independently of live Pi calibration. The Pi converts each valid `OutputTrackingResult` coordinate with:

```text
wire_value = clamp(output_value / active_soft_limit, -1, +1)
scaled = wire_value * 1000
encoded_value = floor(scaled + 0.5) if scaled >= 0 else ceil(scaled - 0.5)
```

The resulting signed integer range is `[-1000, +1000]` with resolution `0.001` and maximum quantization error `0.0005`. The rounding rule is round-to-nearest with exact half values away from zero; language-default `round()` behavior is not part of the contract. Decoding is `wire_value = encoded_value / 1000`. Neutral subtraction, directional gain, and soft limiting remain Pi responsibilities. Mechanical center, travel, sign, gearing, linkage, actuator limits, slew, and current control remain ESP32/mechanics responsibilities.

#### Per-eye state

| Value | Name | Meaning | Emission status |
|---:|---|---|---|
| 0 | `INVALID` | No usable target for this eye; coordinates must be zero | Active |
| 1 | `TRACKED_PUPIL` | Coordinates come from accepted pupil tracking | Active |
| 2 | `HELD_TARGET` | Last accepted target from any source during a bounded transition/absence hold | Allocated; hierarchy accepted, thresholds pending |
| 3 | `HEAD_POSE_DEGRADED` | Shared target derived from head orientation | Allocated; primary fallback, quality gates pending |
| 4 | `FACE_POSITION_DEGRADED` | Shared target derived from face position | Allocated; secondary fallback, quality gates pending |
| 5 | `BODY_POSITION_DEGRADED` | Shared target derived from body/person position | Allocated; tertiary fallback, quality gates pending |
| 6–255 | — | Reserved | Must not be emitted |

The deployed app still renders its original pupil `OutputTrackingResult`; it does not emit this payload. A tested codec and six-state shadow selector now exist, and shadow decisions may use all fallback states, but the encoder is not connected to application output or transport.

`face_detected` is deliberately absent. Per-eye state is the actionable contract and supports future partial validity without exposing Pi implementation details. Confidence scores are deliberately absent: the Pi owns quality decisions and must not delegate interpretation of tracker confidence to the ESP32.

#### Canonical binary representation

All multi-byte fields use network byte order. The canonical payload is exactly 20 bytes:

| Offset | Field | Type | Required value or meaning |
|---:|---|---|---|
| 0 | `magic` | `uint16` | `0x4559` (`EY`) |
| 2 | `schema_version` | `uint8` | `1` |
| 3 | `message_type` | `uint8` | `1` (`EYE_TARGETS`) |
| 4 | `sample_id` | `uint32` | Increment once per fresh output snapshot, including `INVALID`; wraps modulo 2³² |
| 8 | `left_state` | `uint8` | Per-eye state enum |
| 9 | `right_state` | `uint8` | Per-eye state enum |
| 10 | `reserved` | `uint16` | Must be zero |
| 12 | `left_x` | `int16` | Final normalized x multiplied by 1000 |
| 14 | `left_y` | `int16` | Final normalized y multiplied by 1000 |
| 16 | `right_x` | `int16` | Final normalized x multiplied by 1000 |
| 18 | `right_y` | `int16` | Final normalized y multiplied by 1000 |

Equivalent Python layout notation:

```text
!HBBIBBHhhhh
```

An `INVALID` eye must use `(0, 0)`. A structurally invalid frame—wrong size, magic, version, message type, nonzero reserved field, unknown state, or coordinate outside `[-1000, +1000]`—must not produce a target. Both eye channels belong to the same `sample_id`; they must not be sent or applied as unrelated messages.

`sample_id` is freshness metadata, not motion. A receiver compares it with modulo-2³² serial-number arithmetic. Wall-clock timestamps are excluded because the Pi and ESP32 do not share a clock and the ESP32 can measure arrival freshness locally.

#### Pi-side validation status

Validated from source, deployed configuration, live status, and a faithful pack/unpack harness:

| Item | Status |
|---|---|
| Output is after neutral/gain/soft-limit | Confirmed in `track_eye/output.py` and live status |
| Active soft-limit range | Runtime-validates `1.0..3.0`; live value `1.5` |
| Normalized integer bounds | Checked across allowed soft-limit values `1.0, 1.5, 2.0, 3.0`; always `[-1000,+1000]` |
| Quantization rule | Checked at positive/negative half-step boundaries; max error `0.0005` |
| Canonical size/layout | `20` bytes; `!HBBIBBHhhhh`; pack/unpack round-trip verified |
| No-face behavior | 600/600 live status samples had `face_detected=false`, both outputs absent, health still true |
| Live publish cadence during that sample | `14.3059 Hz` from frame sequence delta over `30.8264 s` |
| Eye landmark identity | MediaPipe constants: `33/133 = FACEMESH_RIGHT_EYE`, `362/263 = FACEMESH_LEFT_EYE` |
| Processed mirror state | Confirmed: app flips frame before tracker; deployed command does not pass `--no-mirror` |

This validates Pi-side semantics and representation. It does **not** validate pupil accuracy, anatomical-to-mechanical mounting, or ESP32 reception.

#### Still unknown or blocked

| Item | Why it remains open | Required evidence |
|---|---|---|
| Anatomical eye ↔ mechanical eye mapping | No servo/rig is connected; current software slots are image-side | Labelled rig test with known left/right installation |
| Pupil direction accuracy | Historical baseline did not pass both-eye separation gates | Controlled gaze/head-motion baseline |
| Partial-eye validity | Current tracker emits two eyes or none | Per-eye quality metrics and one-eye occlusion run |
| `sample_id` restart semantics | No sender/receiver implementation exists | ESP32 parser test across Pi restart/reconnect |
| Transport/framing | No ESP32 hardware path exists | Hardware-in-loop loss/jitter/latency test |
| Watchdog threshold | Depends on actual link and safe mechanical state | Measured outage sweep |
| Checksum/authentication | Depends on link threat model and framing | Select transport and threat model first |

The output content is sufficiently specified for an encoder/decoder implementation, but the Pi cannot close the hardware- and installation-dependent rows.

#### Canonical examples

Current live sample `336941` had calibrated output:

```text
left  = (0.742609, 0.234397)
right = (0.551124, 0.250003)
soft_limit = 1.5
```

Its normalized encoded targets are:

```text
sample_id=336941
left_state=TRACKED_PUPIL,  left=(495, 156)
right_state=TRACKED_PUPIL, right=(367, 167)
```

The exact 20-byte representation is:

```text
45 59 01 01 00 05 24 2d 01 01 00 00 01 ef 00 9c 01 6f 00 a7
```

No usable eyes:

```text
left_state=INVALID,  left=(0, 0)
right_state=INVALID, right=(0, 0)
```

Future partial validity is representable atomically:

```text
left_state=TRACKED_PUPIL, left=(x, y)
right_state=INVALID,      right=(0, 0)
```

The current tracker remains all-or-none and cannot emit this partial case until independent per-eye quality validation exists. The Pi encoder must map channels by the required `OutputEyeSignal.name` values, not silently accept missing, duplicate, or swapped identities.

#### Deliberately excluded

The payload does not carry:

- raw `TrackingResult` coordinates or landmarks;
- `face_detected`, iris radius, eye width, confidence, or inference timing;
- Pi neutral offsets, gains, soft-limit configuration, mirror setting, or camera metadata;
- servo angle, PWM pulse, radians, velocity, acceleration, current, or torque;
- mechanical center, travel, linkage, gearing, limit, or smoothing parameters;
- transport address, port, checksum, retry, acknowledgement, watchdog, or framing bytes.

Those values either belong inside the Pi, inside the ESP32/mechanical layer, in diagnostics/telemetry, or in the still-open transport contract.


### Transport decisions still open

Research must still determine, with ESP32 hardware-in-loop evidence:

- transport: UDP unicast, USB CDC, UART, TCP, or another mechanism;
- whether the canonical binary payload is carried directly or wrapped for a byte stream;
- connection/session establishment and restart behavior;
- checksum/authentication requirements beyond the selected transport;
- packet cadence, loss/reordering behavior, and watchdog interaction;
- discovery/addressing and the trusted-network boundary.

### Transport/framing research retained

The current recommendation, not yet an accepted transport contract, is:

- if a data cable is acceptable, prefer USB CDC carrying the 20-byte payload with CRC and COBS framing;
- if wireless is required, prefer UDP unicast carrying one complete 20-byte snapshot per datagram;
- do not retransmit superseded motion snapshots;
- use TCP for configuration or telemetry rather than the latest-state motion stream;
- keep text encoding only as a bring-up/debug representation.

Representative Pi5 measurements on 2026-09-16:

- text candidate: 47–56 bytes;
- binary float32 candidate: 26 bytes;
- fixed-point binary candidate: 18 bytes; the accepted aligned payload above is 20 bytes;
- fixed binary pack/unpack: approximately 1.92/2.01 µs per operation;
- UDP loopback: 10,000/10,000 ordered datagrams, approximately 76,000 datagrams/s;
- strict harness rejected wrong length, magic/version, reserved flags, and out-of-range coordinates;
- simulated duplicate, stale, out-of-order, and 32-bit wrap handling behaved as required.

These measurements validate a faithful Pi-side harness only. No ESP32 firmware, parser, Wi-Fi path, USB path, loss profile, or hardware watchdog was available, so transport remains open.

### Remaining transport evidence

Before accepting a transport, retain:

1. an independent parser/conformance test on the ESP32;
2. valid, invalid, partial, malformed, duplicate, stale, out-of-order, restart, and sequence-wrap cases;
3. measured latency, jitter, loss, recovery, and watchdog behavior on the actual link;
4. tests with the browser video stream both active and inactive;
5. proof that mechanical mapping remains outside the Pi payload.

## Question B — fallback when eyes are not reliable

### Problem statement and accepted product requirement

At approximately 2 m or in weak/variable light, the current iris/eye output may be missing or inaccurate even while a visitor remains in view.

Owner clarification on 2026-09-16 establishes the governing requirement: **if a visitor is detected, the artwork must continue emitting responsive eye targets derived from that visitor. Losing pupil or face landmarks must not by itself freeze both artwork eyes.** Accurate independent pupil mirroring is the preferred mode, not a prerequisite for all output. Degraded modes may drive both artwork eyes from one shared visitor-derived target, but the source must be labeled honestly.

### Required fallback hierarchy

The implementation target is a best-available-source state machine:

1. **Tracked pupil:** retain independent per-eye motion while iris quality is usable.
2. **Brief transition hold:** bridge isolated missed frames only; continue evaluating every lower-fidelity source during the hold.
3. **Head-pose fallback:** when non-iris face landmarks remain usable, map yaw/pitch into a shared normalized target for both artwork eyes. This is the primary degraded mode for a seated visitor who turns, raises, or lowers their head without translating through the frame. Roll is metadata/quality evidence, not an eye target axis.
4. **Face-position fallback:** when stable head orientation is unavailable but a face box remains usable, map face-center displacement into a shared target.
5. **Body/person-position fallback:** when the face is unavailable but a person detector or body pose remains usable, map the selected visitor's upper-body/person center into a shared target.
6. **`INVALID`:** only when no usable visitor-derived spatial signal exists, or after the presence detector declares the scene empty. Pupil or FaceMesh iris loss alone is insufficient.

Crop/retry, higher capture resolution, classical pupil detection, and IR illumination are recovery improvements for higher-fidelity modes. They do not replace the head/face/body continuity hierarchy.

### Recommended source and transition policy

The current evidence supports validating this implementation order:

1. separate pupil validity from non-iris face-landmark validity;
2. extract yaw/pitch from the existing face landmarks and validate sign, neutral, range, jitter, and seated head motion;
3. add full-range face detection and a filtered face-center target;
4. add a person/body detector for frames where no usable face exists;
5. run pupil/FaceMesh recovery opportunistically and promote back to tracked-pupil mode only after a stability gate;
6. use bounded hold plus promotion/demotion hysteresis to prevent one-frame source flapping;
7. keep the last degraded source active while it still detects the selected visitor;
8. emit `INVALID` only after all visitor-derived sources fail for a measured absence timeout.

Normal pupil mode preserves independent eyes. Head/face/body degraded modes intentionally permit both eyes to share a target; that is correct fallback behavior for this installation rather than a violation.

On one production-rendered `NO FACE` frame containing a deeply pitched/partly occluded face, the short-range and full-range face detectors both returned zero detections. Median detector cost over 20 repetitions was 6.14 ms short-range and 12.79 ms full-range; full-range p95 was 17.53 ms. This single frame shows that full-range detection is not a universal pose/occlusion fallback. It does not measure 2 m or low-light reliability.

The current FaceMesh graph already detects a face, crops it, and resizes the crop for landmark inference. External interpolation cannot restore optical detail absent from the source image. The Blendshape model also consumes FaceMesh landmarks, so its `eyeLook*` outputs are not an independent fallback when FaceMesh is absent. Classical pupil literature inspected during research primarily uses close-up eye/iris inputs and does not establish performance for this installation.

### Additional fallback validation on 2026-09-16

These experiments used `/frame.jpg`, the production-rendered JPEG, not raw camera frames. They validate candidate compute paths on the deployed Pi5, not target-distance accuracy.

#### Full-range detector plus external crop

On 60 samples where production reported `face_detected=true`:

- full-range detector detected a face on `60/60` samples;
- external 25%-margin crop followed by static refined FaceMesh produced landmarks on `54/60` samples (`90%`);
- full-range detector median/p95: `13.713/18.513 ms`;
- cropped static FaceMesh median/p95 when attempted: `12.613/16.587 ms`;
- combined model work median is approximately `26.326 ms`, excluding JPEG fetch and crop bookkeeping.

This is evidence that the candidate path is computationally feasible as an **on-demand pupil-recovery probe**. It is not evidence that it improves 2 m, low-light, one-eye, or pupil accuracy. The 10% crop-mesh misses also show why the installation needs a coarse visitor-position fallback instead of relying on crop/retry alone.

#### Detector disagreement during production no-face

During a separate 300-attempt window, production reported `face_detected=false` on 40 sampled frames. The full-range detector returned a detection on `40/40` of those frames. This is a **100% disagreement rate**, not a measured false-positive rate: the rendered frames may still contain a person that production FaceMesh rejected, and rendered overlays are present. No ground-truth label or raw frame was available. Therefore full-range detection cannot be treated as proof of a valid face or pupil signal.

#### Temporal hold arithmetic

The measured production cadence was `14.3059 Hz`, or `69.901 ms/frame`. A semantic-only sweep gives these stale bounds:

| Hold frames | Maximum held duration |
|---:|---:|
| 1 | 69.9 ms |
| 2 | 139.8 ms |
| 3 | 209.7 ms |
| 4 | 279.6 ms |

For the historical synthetic example, linear release over 1/2/3/4 frames gives per-step magnitudes `0.7/0.35/0.233/0.175`. The deployed selector now has time-based hold/demotion/slew machinery, but these values still do not establish perceptual acceptability, servo safety, or a correct duration.

#### Candidate decisions after requirement correction

| Candidate | Evidence status | Role |
|---|---|---|
| Historical pupil-only no-face output | 600/600 no-face samples had no pupil eye values | Empty-scene/error terminal evidence only; shadow fallback now runs separately |
| Head-pose target | Pinned Tasks transform runs and yields proper rotations; target stays invalid until mirrored axis/sign/range validation | **Primary degraded-output candidate** for seated head motion |
| Face-position target | Full-range detector ran at `13.713 ms` median and disagreed with failed production FaceMesh on 40/40 sampled frames | Secondary degraded-output candidate; needs raw-frame target-distance validation |
| Body/person-position target | HOG worker runs at ~30–50 ms but produced score `0.0` on observed visitor and empty frames | Required tertiary mode; current detector has not demonstrated visitor recall |
| Full-range detector + crop/retry | Crop FaceMesh succeeded on 54/60 samples; approximately 26.3 ms model work | Pupil-mode reacquisition aid, not the continuity fallback |
| Short bounded hold | Timing bounds measured; no rig transition evidence | Transition bridge only |
| Classical pupil ROI | Literature/domain does not match this remote installation | Optional fidelity experiment |
| IR hardware | Camera IR behavior and model compatibility unknown | Optional hardware fidelity experiment |

The production design must optimize **visitor-responsive coverage**, not pupil purity: use pupil motion when reliable, then head orientation, then face/body position, and avoid `INVALID` while any usable visitor-derived signal remains.

### Clean validation audit for the head-first hierarchy

#### Evidence hygiene

The following classes must not be mixed:

- **Source fact:** behavior read directly from current source or official model documentation.
- **Deployment fact:** behavior read from the live Pi5 and exact deployed dependency versions.
- **Feasibility measurement:** timing or output shape measured on an inspected frame.
- **Behavioral validation:** result from labeled raw frames under controlled installation conditions.
- **Proposal:** architecture or threshold not yet accepted by measurement.

All experiments below used production-rendered JPEGs because the running app does not expose raw frames. Rendered gauges and text contaminate detector input. These results may inform feasibility and model selection, but **must not** set accuracy, confidence, mapping, or transition thresholds.

#### Current source and deployment facts

- `EyeTracker` still uses legacy MediaPipe FaceMesh with `refine_landmarks=True` and returns either two eye signals or none.
- `pupil_quality.py` now exposes per-eye geometry and output-domain velocity, but its gate is explicitly uncalibrated and does not establish independent usability.
- `shadow.py` now runs the pinned Tasks Face Landmarker transform and full-range FaceDetection synchronously on the mirrored frame, plus OpenCV HOG in a latest-frame worker.
- `fallback.py` now owns source priority, monotonic timing, held targets, slew, strict configuration, and the 20-byte codec.
- `validation.py` captures explicitly started mirrored pre-render JPEGs inside the one production camera loop. It records code/model/config/calibration checksums, caller-supplied lighting/exposure/consent/split metadata, candidates, decisions, targets, and timings. It does not read camera exposure controls, enforce a frozen scenario registry, or identify participant/visit episodes.
- The Tasks transform remains target-invalid until mirrored-path axis/sign validation. A proper transform in diagnostics is not an accepted head target.

#### Feasibility measurements

On one inspected rendered frame containing one seated visitor:

- Tasks Face Landmarker and legacy FaceMesh both returned 478 landmarks;
- Tasks returned a 4×4 transform with last row `[0, 0, 0, 1]`; the orthonormalized rotation determinant was approximately `1.0`;
- Tasks Face Landmarker median/p95 was `22.571/27.149 ms`;
- legacy FaceMesh median/p95 was `8.990/12.314 ms`;
- same-frame landmark displacement between APIs was `3.554 px` median and `6.427 px` p95.

Therefore the Tasks API is a viable head-pose prototype but is not a drop-in replacement for the calibrated pupil path. It requires raw-frame shadow comparison, output recalibration, and an end-to-end frame-rate test.

On 180 rendered frames from one separately inspected empty scene, production FaceMesh, Tasks Face Landmarker, full-range FaceDetection, and legacy Pose at default `0.5` thresholds all returned zero detections. This is one negative scene, not a false-positive-rate claim.

Static detector comparison on the inspected visitor and empty rendered frames produced:

| Candidate | Visitor frame | Empty frame | Median visitor/empty cost |
|---|---:|---:|---:|
| Full-range FaceDetection | score `0.927` | no detection | `12.863/13.490 ms` |
| EfficientDet-Lite0 int8 person | top score `0.832` | top score `0.043` | `91.235/91.545 ms` |
| SSD MobileNetV2 float16 person | top score `0.883` | top score `0.137` | `91.705/91.920 ms` |
| BlazePose Lite with thresholds forced to zero | detected | detected | `101.853/78.520 ms` |

The two object detectors separated these two frames by score but are too expensive to assume per-frame execution, and two frames cannot select a score threshold. Pose with thresholds forced to zero produced a high-visibility result on the empty rendered frame, demonstrating that landmark visibility is not sufficient presence evidence. A separate 120-sample object-detector window mixed visitor-present and empty periods and has no ground-truth timeline; it is excluded from accuracy claims.

A 900-attempt live collection window contained zero production face-positive samples. Consequently yaw/pitch sign, temporal jitter, dynamic range, responsiveness, and head-versus-expression separation remain **unmeasured**. No synthetic rotation is allowed to substitute for real yaw/pitch motion.

#### Algorithm decision for the first implementation candidate

Use the Tasks Face Landmarker transform as the first head-pose candidate because it provides an official canonical transform and avoids embedding an uncalibrated generic 3D face template, guessed camera intrinsics, or ad hoc `solvePnP` landmark constants. Do not permanently run legacy FaceMesh and Tasks Face Landmarker together. Run both only during bounded shadow validation; replace legacy FaceMesh only if pupil equivalence and runtime gates pass.

If the Tasks migration fails those gates, evaluate MediaPipe `FaceGeometryFromLandmarks` on the existing landmarks. Generic `solvePnP` is a last resort and requires measured camera intrinsics plus a documented canonical model; it must not be introduced as a collection of unexplained constants.

### Detailed implementation and validation plan

#### Phase A — acquire clean evidence — **TOOLING PARTIAL**

1. Extend the existing production-owned baseline path to sample the **mirrored, pre-render** frame before `render_frame`; never open a second camera handle.
2. Record a manifest containing code checksum, model checksum, camera negotiation, mirror state, exposure controls, calibration checksum, frame timestamp, and scenario label.
3. For each frame, record raw candidate data: eye geometry, pupil-quality features, face transform, face box, person/body box, candidate targets, active source, transition reason, and per-stage timing.
4. Store raw images only during an explicitly started validation session. Keep them out of normal production logs and delete them after derived artifacts are accepted.
5. Treat prior rendered-JPEG probes only as feasibility baselines; exclude them from all behavioral gates.

#### Phase B — separate measurements from source selection — **PARTIAL**

1. Replace the all-or-none `TrackingResult` with independent observations for:
   - each pupil;
   - non-iris face landmarks and transform;
   - full-range face detection;
   - person/body detection.
2. Keep candidate generation stateless except for model-native tracking. Put smoothing, hysteresis, and source selection in one `fallback.py` state machine rather than scattering fallback branches through `app.py`.
3. Represent every candidate with source, timestamp, normalized target, validity, and diagnostic quality fields. Diagnostic fields remain Pi-internal and never enter the ESP32 payload.
4. Preserve one camera frame and one mirror convention across every candidate.

#### Phase C — validate pupil quality independently — **MEASUREMENTS ONLY**

1. Record per-eye pixel width, eyelid aperture, iris radius, iris-inside-lid geometry, normalized displacement, and temporal velocity.
2. Label pupil output usable/unusable independently for each eye under open eye, blink, glasses reflection, partial occlusion, distance, and low-light cases.
3. Derive deterministic quality gates on a tuning split, freeze them, then evaluate on held-out participants and conditions.
4. Do not use FaceMesh presence as pupil validity and do not tune thresholds on the final validation set.

#### Phase D — validate head pose as the primary fallback — **MATH/SHADOW IMPLEMENTED; BEHAVIOR BLOCKED**

1. Pin the Face Landmarker model file and checksum.
2. Extract the 3×3 rotation from the 4×4 transform, remove uniform scale with SVD, require a proper finite rotation, and retain quaternion/rotation-matrix form internally.
3. Determine yaw/pitch axes and signs from labeled left/right/up/down head movements through the deployed mirrored path. Do not assign semantic axis names from one static matrix.
4. Use roll only for diagnostics/quality unless a separate artistic mapping is accepted.
5. Derive installation-level neutral and full-scale yaw/pitch values from labeled sessions; store them in versioned configuration rather than source constants.
6. Validate that eyes-only motion with a stationary head does not materially move the head candidate, and that yaw/pitch prompts produce monotonic, directionally separated outputs.
7. Compare Tasks pupil measurements against the current tracker on the same raw frames. Any migration requires recalibrating neutral/gain rather than reusing current calibration silently.

#### Phase E — validate face and body fallbacks — **FACE RUNS; BODY MODEL NOT DEMONSTRATED**

1. Use full-range FaceDetection as the first face-position candidate because its measured cost is materially lower than the tested person models.
2. Map the face-box center relative to a measured installation interaction region, not an assumed full-frame range.
3. Benchmark person detectors only on raw frames. Evaluate detector score, box stability, seated/cropped-body recall, empty-scene activation, and CPU contention before choosing a model.
4. Run an accepted person detector in a latest-frame worker with queue depth one so it cannot block or accumulate stale camera frames. Determine worker cadence from measured end-to-end CPU/fps results; do not embed an arbitrary rate.
5. Retain the current visitor by temporal box continuity. Specify and test acquisition/handoff behavior for multiple visitors; do not silently choose by skin tone, apparent identity, or face-recognition features.
6. Reject BlazePose as a presence oracle unless raw-frame validation disproves the rendered-frame false activation and establishes seated/cropped-body reliability.

#### Phase F — implement one time-based selector — **MECHANISM IMPLEMENTED; TIMINGS OPEN**

Priority is:

```text
TRACKED_PUPIL
  -> HEAD_POSE_DEGRADED
  -> FACE_POSITION_DEGRADED
  -> BODY_POSITION_DEGRADED
  -> HELD_TARGET during the measured absence grace
  -> INVALID
```

The selector must:

- use monotonic elapsed time, never frame counts, because production cadence varies;
- keep separate valid-since and invalid-since times per source;
- use independently configured promotion and demotion intervals per source;
- emit the highest-priority source whose quality and stability gates pass;
- interpolate or slew-limit source changes in target space;
- expire every held target after the configured absence grace;
- emit `INVALID` only after all visitor-derived sources have expired;
- expose current source, source age, transition reason, and candidate availability in status;
- define and rig-test whether one valid pupil produces mixed per-eye states or causes both eyes to use shared head pose.

All thresholds and mappings belong in a versioned fallback calibration file. Source code contains validation and bounds, not installation-specific timing, angles, regions, scores, or gains.

The 2026-09-23 mechanism audit corrected one gap: initial acquisition from
`NONE` previously bypassed the configured `promote_s`. Initial pupil and
degraded candidates now use the same continuous-validity gate as source
replacement. This validates enforcement mechanics only; the timing values
remain unaccepted.

#### Phase G — evaluate without leakage or average-only bias — **NOT STARTED**

Use independent visit episodes, not correlated frames, as the statistical unit. Split by participant before tuning so one person's frames never appear in both tuning and validation. Freeze model versions, thresholds, mapping, and source priority before the held-out run.

The scenario matrix must cross:

- seated and standing visitors;
- near, intermediate, and approximately 2 m distance;
- frontal, yaw left/right, pitch up/down, roll, looking away, and head partially occluded;
- eyes-only movement with head still;
- normal, dim, backlit, screen-changing, and glasses-reflection lighting;
- no glasses, clear glasses, sunglasses where appropriate, mask, hat, and varied clothing/background contrast;
- different heights, ages, skin appearances, face shapes, hairstyles, mobility aids, and seated posture, using consented participant metadata rather than inferring sensitive attributes from images;
- empty scene, one visitor, overlapping visitors, and visitor handoff.

Report per-condition and worst-condition results, not only a global mean. Report unavailable strata instead of claiming fairness. Do not use identity recognition.

#### Phase H — measurable gates and rollout — **SHADOW DEPLOYED; ACCEPTANCE/EMISSION BLOCKED**

Before enabling effective output, agree numerical product gates for visitor-present coverage, first-motion latency, maximum frozen interval, jitter, transition step, false activation, source-flap rate, and minimum production fps. Determine sample count from the accepted failure-rate/confidence target; do not pick a convenient frame count.

Then:

1. tune only on the tuning split;
2. freeze configuration and checksums;
3. run held-out software-only validation;
4. run servo-rig validation for motion direction, transition discontinuity, slew, and watchdog behavior;
5. deploy in shadow mode with source decisions visible but not transmitted;
6. compare shadow output with observed visitor behavior;
7. enable ESP32 emission only after every accepted gate passes;
8. keep rollback to the prior service and calibration artifacts.

Failure of a higher source is acceptable only when the next source continues responsive output. A run fails the product requirement if a labeled present visitor moves while all emitted targets remain `INVALID` or frozen beyond the accepted limit.

### Explicitly unresolved after shadow deployment and audit

- Head-pose target axis identity, sign under mirroring, neutral, usable range, dynamic jitter, and responsiveness lack labeled participant evidence.
- Tasks pupil equivalence is not established; the current legacy pupil tracker therefore remains production-authoritative.
- Independent per-eye pupil-quality thresholds do not exist; glasses, blink, partial occlusion, distance, and lighting cases are unlabeled.
- Full-range face recall, false activation, box stability, ROI, gain, and direction are unvalidated. Live shadow data showed frame-to-frame misses and large vertical offsets in an occluded/downward pose.
- OpenCV HOG returned score `0.0` on observed visitor and empty frames. Body fallback model suitability is a blocker before confidence tuning.
- `TrackedVisitor.nearest` is only a logged source-center placeholder; face/body candidate generation still collapses detections before it. Multi-visitor acquisition, box continuity, retention, and handoff remain unimplemented.
- Mixed one-eye pupil plus shared fallback behavior is not selected or rig-tested.
- `max_held_s` enforces a software absolute bound, but promotion, demotion, hold duration, absence timeout, slew, and interpolation limits are not accepted.
- Numerical product gates and participant/episode counts are not accepted.
- Validation captures are JPEG. Lighting/exposure/consent/split fields are caller-supplied, camera exposure is not read back, missing labels can become `"unlabeled"`, participant/visit IDs are absent, and the deployed service leaves token-gated controls disabled.
- Effective output integration, full-system acceptance FPS, Pi-to-ESP32 transport, parser, sequence handling, watchdog, servo motion, and safe mechanical state remain open.

### Required experiment matrix

At minimum, collect separate labeled runs for:

- target distance: near validated setup, approximately 2 m, and intermediate distance;
- lighting: normal visible light, dim light, changing screen brightness, and glare/reflection conditions;
- visitor behavior: eyes-only movement, head turn, body translation, facing away, crouching, partial occlusion, and entering/leaving;
- population: no visitor, one visitor, and multiple visitors;
- source availability: pupils, face landmarks, face box only, body/person only, and no detection;
- recorded outputs: selected visitor, active source, both eye targets, detection state, transition reason, timing, and frame rate.

Each run must preserve raw data and record the exact camera configuration, mirror state, EMA, exposure/lighting conditions, and calibration state.

### Acceptance gates before calling the hierarchy validated

The hierarchy is not accepted merely because it produces nonzero numbers or looks smooth in one scene. Evidence must show:

- non-`INVALID` output coverage while a labeled visitor is present;
- time-to-first-motion after visitor entry;
- bounded frozen-output duration while the visitor moves;
- correct mode/source labeling;
- stable visitor selection when multiple people are visible;
- bounded output, jitter, velocity, and transition discontinuity;
- bounded demotion/promotion delay and no one-frame source flapping;
- measured target responsiveness across distance, lighting, facing-away, and occlusion cases;
- quantified false activation when no person is present;
- known latency, CPU cost, and production frame-rate impact;
- defined one-eye-loss behavior;
- `INVALID` only after every visitor-derived source has failed for the declared absence timeout.

## Current decision boundary

As of the post-deployment audit on 2026-09-16:

- the `EyeTargetFrame` content and 20-byte representation are accepted and implemented as a tested library codec;
- the fixed priority is implemented and a permanent 16-combination sweep test covers every source-availability state;
- shadow candidates, selector decisions, status, overlay, and explicit validation capture are deployed;
- production pupil rendering remains unchanged and fallback decisions are not emitted;
- configuration rejects effective emission because no output integration exists;
- head target mapping, pupil-quality gates, face mapping, body detector choice, transition timing, multi-person behavior, and acceptance metrics remain evidence-gated;
- HOG body suitability is an additional technical blocker; participant data alone is not sufficient to approve it;
- transport, framing, addressing, authentication, restart handshake, cadence, watchdog, ESP32 parser, and rig mechanics remain unimplemented.

Owner scope update on 2026-09-23: current validation and rollout work is limited
to pupil, head, and face. The historical payload enum and body candidate remain
implemented for compatibility, but `body_enabled=false`; body detector
selection/tuning is deferred and is not an exit criterion for this slice.
Within the active scope the priority is
`PUPIL -> HEAD -> FACE -> HELD -> INVALID`.

The codec may be connected to application output only in an explicitly scoped integration after the software behavioral gates are frozen. Transport and rig work then require independent conformance and hardware-in-loop evidence.

## Research sources retained

Transport sources:

- [RFC 768 — User Datagram Protocol](https://www.rfc-editor.org/rfc/rfc768.html)
- [RFC 8085 — UDP Usage Guidelines](https://www.rfc-editor.org/rfc/rfc8085.html)
- [RFC 9293 — Transmission Control Protocol](https://www.rfc-editor.org/rfc/rfc9293.html)
- [RFC 1982 — Serial Number Arithmetic](https://www.rfc-editor.org/rfc/rfc1982.html)
- [ESP-IDF lwIP/BSD sockets](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/lwip.html)
- [ESP32-S3 Wi-Fi performance and power save](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/wifi-driver/wifi-performance-and-power-save.html)
- [ESP32-S3 USB CDC device support](https://docs.espressif.com/projects/esp-usb/en/latest/esp32s3/usb_device.html)
- [Consistent Overhead Byte Stuffing](https://www.stuartcheshire.org/papers/COBSforToN.pdf)

Tracking/fallback sources:

- [MediaPipe Face Detection module](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/face_detection/README.md)
- [MediaPipe FaceMesh model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf)
- [MediaPipe Iris paper](https://arxiv.org/html/2006.11341)
- [MediaPipe Blendshape model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf)
- [MediaPipe Face Landmarker Python guide and transformation-matrix option](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python)
- [MediaPipe canonical face pose transform definition](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/face_geometry/protos/face_geometry.proto)
- [MediaPipe Object Detector models and task benchmarks](https://developers.google.com/edge/mediapipe/solutions/vision/object_detector)
- [BlazePose GHUM 3D model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf)
- [Remote eye-region landmarks, Park et al.](https://www.perceptualui.org/publications/park18_etra.pdf)
- [Webcam pupil localization under adverse conditions, Benletaief et al.](https://arxiv.org/html/2002.11674)

## Agent deliverable

The researching agent must return a comparison backed by artifacts, with separate sections:

1. observed facts;
2. experiment setup;
3. measurements;
4. failure cases;
5. candidate comparison;
6. unresolved questions;
7. recommendation, clearly labeled as a recommendation and not an accepted contract.

No effective fallback emission, transport, or hardware approval follows from the shadow deployment. Quality gates, mappings, timings, detector selection, privacy controls, and rig behavior remain evidence-gated.
