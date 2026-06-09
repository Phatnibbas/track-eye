# ChatGPT Pro Research Context — Track Eye Folder

Created: 2026-05-13  
Purpose: paste this whole file into ChatGPT Pro or another research model to get high-quality external review without making it read stale project history.

---

## 1. What I want from the research model

Please review this project as a **currently-working laptop-first webcam gaze tracking + single-eye ESP32 servo prototype**. Current demo/debug transport is **USB UART**; WiFi/WebSocket remains available for later wireless demos.

I want practical, technically rigorous advice for:

1. stabilizing the current runtime,
2. refactoring safely without breaking manual tuning,
3. maintaining/upgrading the project over time,
4. improving gaze/iris tracking quality,
5. improving USB UART and later WebSocket/ESP32 servo actuation safety,
6. deciding which technical upgrades are worth doing next.

Important: do **not** over-index on old research plans or old docs. The newest runtime code/config is closer to working than the archived docs.

---

## 2. Project summary

This folder is a Python project for real-time eye/gaze tracking using a normal laptop webcam.

Current high-level pipeline:

1. Open webcam or replay video.
2. Run OpenCV + MediaPipe FaceMesh with iris refinement.
3. Extract per-eye iris/eye geometry.
4. Produce normalized control outputs:
   - `x_ctrl` in `[-1, 1]`
   - `y_ctrl` in `[-1, 1]`
   - `confidence` in `[0, 1]`
5. Apply session gating for kiosk/multi-user usage.
6. Map gaze control to one artificial eye with four 180-degree servos:
   - two horizontal-axis servos on GPIO42/GPIO39
   - two vertical-axis servos on GPIO41/GPIO38
7. Send servo commands from laptop to ESP32-S3 over USB UART for the current demo/debug path; WebSocket remains an optional later wireless path.
8. Optionally display OpenCV overlay or browser UI.
9. Optionally log benchmark JSONL and replay sessions.

The current active hardware direction is:

- laptop / PC: vision, calibration, session state, UI, benchmark, command generation
- ESP32-S3: USB UART receiver for current demo/debug; optional WiFi WebSocket client for later wireless demo; servo PWM, watchdog/fail-safe

---

## 3. Current source-of-truth files

Treat these as active/current:

```text
AGENT_CONTEXT.md
README.md
config.yaml
main.py
gaze_estimator.py
calibration.py
calibration_coupled.py
calibration_quality.py
constants.py
filters.py
draw_utils.py
benchmark_utils.py
session_manager.py
servo_mapper.py
servo_serial.py
servo_ws.py
web_ui_server.py
requirements.txt
tests/
tools/
esp32_eye_ws_firmware/
esp32_eye_uart_firmware/
esp32_servo_tester/
calibration_data/
benchmark_data/
```

Do not treat this as current source-of-truth:

```text
archive/legacy_2026-05-13/
```

Archived files are historical and may contain outdated direction.

Do not read or request secrets:

```text
esp32_eye_ws_firmware/secrets.py
```

---

## 4. Current directory structure

Current root entries after cleanup:

```text
AGENT_CONTEXT.md
README.md
CHATGPT_PRO_RESEARCH_CONTEXT.md
archive/
benchmark_data/
benchmark_utils.py
calibration_coupled.py
calibration_data/
calibration_quality.py
calibration.py
config.yaml
constants.py
draw_utils.py
esp32_eye_uart_firmware/
esp32_eye_ws_firmware/
esp32_servo_tester/
filters.py
gaze_estimator.py
main.py
requirements.txt
servo_mapper.py
servo_serial.py
servo_ws.py
session_manager.py
tests/
tools/
web_ui_server.py
```

Archived legacy content:

```text
archive/legacy_2026-05-13/
  BENCHMARK_PROTOCOL.md
  docs-superpowers/
  esp32_eye_firmware_serial_legacy/
  EXTERNAL_AGENT_RESPONSES_PROBLEM_A.md
  NEUTRAL_CONTEXT_FOR_EXTERNAL_AGENTS.md
  planning_debug_legacy/
  PROBLEM_A_SYNTHESIS_PLAN.md
  qwen_settings_legacy/
  README_legacy.md
  test_esp32_eye_firmware_package.py
```

Reason for archiving: old docs/code were stale and caused agents to waste context or follow outdated plans.

---

## 5. Dependencies

From `requirements.txt`:

```text
mediapipe==0.10.14
opencv-python>=4.10,<5
numpy>=1.26,<3
PyYAML>=6.0,<7
pyserial>=3.5,<4
websockets>=12,<16
```

Notes:

- `mediapipe==0.10.14` is pinned to keep FaceMesh behavior/API stable.
- Project is CPU-first.
- No CUDA/TensorRT/ROS path currently active.
- User runs Python via `py -3` on Windows.

---

## 6. Active runtime command examples

Run tests:

```powershell
py -3 -m unittest discover -s tests
```

Run main app:

```powershell
py -3 main.py
```

Smoke run without UI window:

```powershell
py -3 main.py --no-window --max-frames 120
```

Run USB UART servo output for current demo:

```powershell
.\.venv\Scripts\python.exe main.py --servo-port COM5
```

Replace `COM5` with the actual ESP32 serial port.

Run WebSocket servo host for later wireless demo:

```powershell
.\.venv\Scripts\python.exe main.py --servo-ws-host 0.0.0.0 --servo-ws-port 8765
```

Run browser UI:

```powershell
.\.venv\Scripts\python.exe main.py --web-ui-host 0.0.0.0 --web-ui-port 8080
```

Current test result after cleanup/doc update:

```text
py -3 -m unittest discover -s tests
Ran 35 tests in about 1 second
OK
```

Important: unit tests pass, but this does **not** prove camera/hardware/Web UI/physical servo behavior unless those are tested separately.

---

## 7. Current config snapshot

Important values from `config.yaml`:

```yaml
camera_index: 0
camera_fallback_indices: [0, 1, 2, 3]
camera_backends:
  - default
  - dshow
  - msmf
frame_width: 1280
frame_height: 720
mirror: true
window_name: "Gaze Control"

min_detection_confidence: 0.5
min_tracking_confidence: 0.5
smoothing_alpha: 0.55
smoothing_alpha_y: 0.42
dead_zone: 0.03
dead_zone_y: 0.05
control_scale_x: 1.6
control_scale_y: 1.8
min_confidence_for_update: 0.35
min_confidence_for_update_y: 0.45
partial_confidence_threshold: 0.20
partial_confidence_threshold_y: 0.28
low_conf_hold_frames: 6
low_conf_decay: 0.92
head_pose_enabled: false

fusion_strategy: "weighted"
vertical_feature_mode: "current"
vertical_orbital_norm_gain: 0.5
vertical_width_norm_gain: 0.30

session_acquire_frames: 10
session_baseline_hold_s: 1.5
session_lost_face_timeout_s: 1.0
session_min_confidence: 0.35
session_drift_threshold: 0.25
kiosk_quick_calibration_enabled: true

debug: true
autoload_calibration: true
benchmark_protocol_collect_seconds: 7.0
benchmark_autosave: true
benchmark_autosave_dir: "benchmark_data"

servo:
  confidence_min: 0.45
  session_required: true
  smoothing_alpha: 0.20
  max_step_deg: 3.0
  single_eye:
    pan_slot: "lt"
    pan_pin: 5
    pan_neutral_deg: 90
    pan_min_deg: 55
    pan_max_deg: 125
    pan_gain_deg: 35
    pan_invert: true
    tilt_slot: "lp"
    tilt_pin: 4
    tilt_neutral_deg: 80
    tilt_min_deg: 50
    tilt_max_deg: 110
    tilt_gain_deg: 75
    tilt_invert: true

calibration:
  model_path: "calibration_data/calibration.json"
  settle_seconds: 0.8
  sample_seconds: 1.5
  min_confidence: 0.20
  min_samples_per_point: 5
  kiosk_quick_settle_seconds: 0.9
  kiosk_quick_sample_seconds: 1.6
  kiosk_quick_min_samples_per_point: 8
  min_axis_separation_x: 0.03
  min_axis_separation_y: 0.03
  y_fusion_mode: weighted
  ridge_alpha: 0.05
  mode: axis5
  points: axis5
  coupled_basis: affine
```

Current default vertical path is `current`, not `orbital_relative`.

---

## 8. Active runtime flow in `main.py`

Per frame, `main.py` does approximately:

1. Read frame from camera or replay video.
2. Record raw frame if recorder enabled.
3. Flip frame horizontally if `mirror` is true.
4. Call:

```python
last_estimate = estimator.process(frame, calibration_manager.model)
```

5. Update calibration manager:

```python
calibration_manager.update(last_estimate.feature_vector, last_estimate.confidence)
```

6. Update session manager with face/confidence/raw-eye info:

```python
session_snapshot = session_manager.update(
    face_detected=bool(last_estimate.face_detected),
    confidence=float(last_estimate.confidence),
    timestamp_s=float(elapsed_s),
    x_eye=float(last_estimate.x_eye),
    y_eye=float(last_estimate.y_eye),
)
```

7. If session reset required:

```python
estimator.reset_filters()
estimator.reset_raw_center()
session_manager.acknowledge_reset()
```

8. Map gaze to servo command:

```python
servo_command = servo_mapper.update(
    x_ctrl=float(last_estimate.x_ctrl),
    y_ctrl=float(last_estimate.y_ctrl),
    confidence=float(last_estimate.confidence),
    session_ready=bool(session_snapshot.ready),
    output_source=str(last_estimate.output_source),
    calibration_active=bool(calibration_manager.active),
)
```

9. Optionally write serial and/or broadcast WebSocket.
10. Optionally log benchmark frame.
11. Draw overlay.
12. Optionally update browser MJPEG stream.
13. Handle keyboard commands.
14. On exit finalize logs/video/labels and close devices/servers.

Keyboard controls include:

- `q` / ESC: quit
- `c`: start calibration
- `r`: reset calibration model
- `z`: recenter
- `s`: save calibration
- `l`: load calibration
- `h`: toggle head pose compensation
- `d`: toggle debug overlay
- `p`: pause
- `1..6`: benchmark protocol labels
- `0`: clear/stop benchmark label

---

## 9. Gaze estimator details

File: `gaze_estimator.py`

Core class: `GazeEstimator`

Uses:

```python
mp.solutions.face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=...,
    min_tracking_confidence=...,
)
```

`EstimateResult` fields include:

- `x_ctrl`
- `y_ctrl`
- `raw_x`
- `raw_y`
- `fallback_x`
- `fallback_y`
- `x_eye`
- `y_eye`
- `yaw_deg`
- `pitch_deg`
- `head_pose_x`
- `head_pose_y`
- `pose_valid`
- `head_pose_enabled`
- `confidence`
- `feature_vector`
- `eyes`
- `fusion_mode`
- `left_weight`
- `right_weight`
- `eye_disagreement_x`
- `eye_disagreement_y`
- `vertical_reliability`
- `y_confidence`
- `face_detected`
- `valid`
- `output_source`
- `message`

Per-eye `EyeMeasurement` includes:

- contour/corners/top/bottom
- iris center and ring points
- horizontal
- vertical
- raw vertical numerator
- pre/post baseline vertical
- local eye axes
- eyelid-relative vertical
- orbital-relative vertical
- iris ring vertical asymmetry
- openness
- width/height
- iris radius
- clearance metrics
- quality
- tracked flag

Feature vector is currently 4 values:

```text
left_eye_x, left_eye_y, right_eye_x, right_eye_y
```

Vertical feature path:

- `current`: width-normalized iris vertical displacement
- `orbital_relative`: normalized against brow/cheek orbital landmarks

Current default is `current`.

Important: offline logs once suggested `orbital_relative` may help glasses sessions, but current runtime default remains `current`. Do not blindly switch default without live validation.

---

## 10. Calibration system

Files:

```text
calibration.py
calibration_coupled.py
calibration_quality.py
```

Current calibration modes in config/code:

- `axis5`
- `auto`
- `coupled_only`

Current active config:

```yaml
mode: axis5
points: axis5
coupled_basis: affine
```

Axis5 points:

```text
center -> (0, 0)
left   -> (-1, 0)
right  -> (1, 0)
up     -> (0, -1)
down   -> (0, 1)
```

Grid9 points also exist in constants but are not current default.

Calibration manager supports:

- start/update session
- quick kiosk preset
- fit model
- quality evaluation
- save/load JSON
- recenter
- reset model

---

## 11. Session manager

File: `session_manager.py`

Purpose: deterministic state machine for sequential kiosk-style users.

States observed in code:

- `idle`
- `acquire_face`
- `baseline_lock`
- `active`
- `needs_recenter`

Reset reasons include:

- `manual_reset`
- `lost_user`
- `center_drift`

High-level behavior:

- waits for stable face/confidence
- locks baseline for a short time
- marks session ready only when active
- if face lost for timeout, resets
- if drift exceeds threshold, asks recenter / stops ready state

Servo mapper uses `session_ready` as a safety gate.

---

## 12. Servo mapper and command path

File: `servo_mapper.py`

Main config class:

```python
SingleEyeServoConfig
```

Main command class:

```python
SingleEyeServoCommand
```

`SingleEyeServoMapper.update(...)` gates command output:

1. If calibration active -> approach neutral with reason `calibration_active`.
2. If session is required and not ready -> hold with reason `session_not_ready`.
3. If confidence too low -> hold with reason `low_confidence`.
4. If estimator output source is `hold` -> hold with reason `held_gaze_output`.
5. Otherwise apply shaped gaze response and move toward target.

Target mapping:

- x controls pan
- y controls tilt
- both can invert
- range clamped
- smoothing and max-step limit applied

Important current servo safety:

- confidence gate
- session-ready gate
- calibration-active neutral gate
- output hold gate
- clamp min/max angle
- smoothing alpha
- max step degrees

---

## 13. USB UART, WebSocket server, and browser UI

File: `servo_serial.py`

Current demo/default physical connection path:

```text
Laptop Python app -> USB serial COM port -> ESP32-S3 -> servos
```

Packet format:

```text
EYE,pan,tilt,gate\n
```

Laptop command:

```powershell
.\.venv\Scripts\python.exe main.py --servo-port COM5
```

Current active UART firmware folder:

```text
esp32_eye_uart_firmware/
```

Use this first to make the demo run before dealing with WiFi/IP/reconnect issues.

File: `servo_ws.py`

Payload format:

```json
{"type":"eye","pan":90,"tilt":80,"gate":"tracking"}
```

Server behavior:

- background asyncio loop in daemon thread
- tracks connected clients
- broadcasts servo command payloads
- removes failed clients
- shutdown tries to close server and stop loop

File: `web_ui_server.py`

Purpose:

- HTTP server with `/` and `/index.html`
- MJPEG stream at `/stream.mjpg`
- browser HUD connects to WebSocket port and displays pan/tilt/gate/client-ish info

Current UI is simple and should not be treated as primary control logic.

---

## 14. ESP32 active firmware

Current active demo/debug folder:

```text
esp32_eye_uart_firmware/
```

Purpose:

- ESP32-S3 receives newline-terminated USB serial packets.
- Drives one eye / four 180-degree servos.
- Keeps local clamp/rate-limit/watchdog neutral fallback.

UART packet:

```text
EYE,pan,tilt,gate
```

Current UART pins/ranges:

```text
Horizontal axis servos -> GPIO42, GPIO39, neutral 90, range 50..130
Vertical axis servos   -> GPIO41, GPIO38, neutral 0,  range 0..50
```

Optional later wireless folder:

```text
esp32_eye_ws_firmware/
```

Purpose:

- ESP32-S3 connects to laptop WebSocket host.
- Receives JSON eye commands.
- Drives one eye / two servos in the older WebSocket firmware path.

README says upload these to ESP32 via Thonny:

```text
main.py
secrets.py
```

Create board-local `secrets.py` from `secrets_example.py`:

```python
WIFI_SSID = "..."
WIFI_PASSWORD = "..."
SERVER_HOST = "<laptop-ip>"
SERVER_PORT = 8765
SERVER_PATH = "/"
```

Do not expose real credentials.

Servo pins from README:

```text
PAN  lt -> GPIO5
TILT lp -> GPIO4
```

Safety notes:

- Use external 5V servo power.
- Common GND between ESP32 and servo power.
- Watchdog: no packet for about 900ms should return eye to neutral.

---

## 15. Benchmark/logging/tools

File: `benchmark_utils.py`

Benchmark protocol labels:

```text
0 -> none
1 -> center_hold
2 -> horizontal_sweep
3 -> vertical_sweep
4 -> diagonal_sweep
5 -> head_motion
6 -> blink_degrade
```

Logger persists rich per-frame JSONL fields including:

- frame index/time/fps
- protocol label
- session state/ready/reason
- vertical feature mode
- x/y control/raw/eye fields
- confidence and vertical reliability
- pose fields
- face/valid/message
- per-eye quality
- per-eye horizontal/vertical/raw geometry fields
- iris centers/ring points
- local axes
- alternative vertical candidates
- disagreement metrics
- servo pan/tilt/gate/reason
- condition metadata

Tools folder includes:

```text
tools/analyze_raw_signals.py
tools/auto_annotate_crops.py
tools/compare_phase3.py
tools/compare_vertical_candidates.py
tools/export_eye_crops.py
tools/generate_problem_a_batch.py
tools/test_ws_servo_host.py
```

Use benchmark data only for analysis tasks. Do not assume old benchmark reports reflect current runtime truth.

---

## 16. Tests currently present

Current `tests/` includes:

```text
test_auto_annotate_crops.py
test_benchmark_flush.py
test_benchmark_session_fields.py
test_benchmark_unlabelled_logging.py
test_esp32_serial_transport.py
test_esp32_servo_tester_package.py
test_esp32_ws_firmware_package.py
test_gate_a_logging.py
test_gate_b2_crop_export.py
test_gate_c_raw_metrics.py
test_quick_kiosk_calibration.py
test_servo_config_gain.py
test_servo_ws_integration.py
test_servo_ws_server.py
test_session_manager.py
test_single_eye_servo_mapper.py
test_vertical_candidate_comparison.py
test_vertical_feature_mode.py
test_web_ui_server.py
```

Full test suite after cleanup:

```text
Ran 35 tests
OK
```

The old serial firmware package test was archived with old serial firmware.

---

## 17. Known important constraints

1. User is on Windows.
2. Python command preference: `py -3`.
3. Do not assume WSL/Linux.
4. Do not read or reveal secrets.
5. Camera/hardware tests require physical environment.
6. Passing unit tests does not prove live camera/servo behavior.
7. Manual tuning matters; avoid broad rewrites.
8. Config defaults are operationally important.
9. UI/browser layer can be stale or separate from runtime truth.
10. Servo safety gates should not be weakened casually.

---

## 18. What I need ChatGPT Pro to research/review

Please answer as an external technical reviewer. Prioritize concrete recommendations, risks, and next steps.

### A. Architecture review

Given this structure, is the separation between laptop vision/session/UI and ESP32 servo actuation appropriate? What should be kept, changed, or hardened?

### B. Safe refactor plan

Which files should be refactored first to reduce complexity without breaking behavior? Suggest a staged refactor plan with verification after each stage.

### C. Gaze estimation quality

For a normal webcam + MediaPipe FaceMesh iris pipeline, what practical improvements are most likely to improve robustness?

Please consider:

- glasses/reflections
- vertical gaze instability
- head movement contamination
- eyelid/blink failures
- per-user calibration
- session drift
- confidence quality

### D. Calibration strategy

Is current `axis5` calibration a reasonable default? Should the project keep 5-point calibration, add quick center-only mode, add 9-point mode, or use another approach?

### E. Vertical feature strategy

Current runtime default is `vertical_feature_mode: current`; `orbital_relative` exists and may help glasses sessions offline. What is the safest way to evaluate/promote a vertical feature mode without breaking current behavior?

### F. Servo/control safety

Review the current safety gates:

- session required
- confidence minimum
- calibration active neutral
- held output hold
- clamp min/max
- smoothing alpha
- max step degrees
- ESP32 watchdog

What is missing for safe physical operation?

### G. WebSocket protocol

Current payload is minimal JSON: `type`, `pan`, `tilt`, `gate`. Should the protocol include sequence number, timestamp, confidence, reason, heartbeat, ack, or watchdog fields? What is the simplest robust protocol?

### H. Testing strategy

Given the current tests pass, what tests are missing for:

- runtime loop
- WebSocket client/server behavior
- ESP32 protocol compatibility
- camera/replay determinism
- calibration save/load
- servo safety
- UI behavior

### I. Maintain/upgrade roadmap

Suggest a practical next 3-5 phase roadmap that preserves the working prototype and incrementally improves reliability.

### J. Anti-recommendations

What should this project **not** do right now? Examples: big ML model rewrite, Jetson migration, ROS migration, full web dashboard rewrite, etc. Please justify.

---

## 19. Requested output format from ChatGPT Pro

Please respond with:

1. **Executive summary** — 5-10 bullets.
2. **Top risks** — ranked by severity.
3. **What is already good** — things to preserve.
4. **Refactor plan** — staged, minimal-risk.
5. **Upgrade plan** — staged, with verification per stage.
6. **Testing gaps** — concrete tests to add.
7. **Hardware/servo safety recommendations**.
8. **Research-backed gaze tracking recommendations** — practical, not speculative.
9. **Do-not-do list**.
10. **Questions you need answered before deeper design**.

Please be explicit when a recommendation is based on general knowledge rather than direct inspection of code.
