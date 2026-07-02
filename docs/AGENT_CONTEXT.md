# Agent Context — Runtime, Refactor, Maintain, Upgrade Guide

Last curated: 2026-05-13  
Owner context: Phát has manually tuned the newest runtime and says it is already close to OK. Future agents must protect that working state.

This is the first file future agents should read. It is a **current working map**, not a speculative roadmap. If this file conflicts with live code/config/tests, trust live code/config/tests and update this file after verification.

---

## 0. Non-negotiable operating rules

1. **Runtime truth beats docs.** Read code and config before making claims.
2. **Newest active files beat archived/history files.** Do not anchor on old Problem A docs or old phase plans.
3. **Small verified changes only.** This repo has manual tuning; avoid broad rewrites unless explicitly requested.
4. **No “done/fixed” without runtime evidence.** At minimum run the relevant tests. For UI/servo/camera changes, say clearly what hardware/UI was or was not verified.
5. **Do not read secrets by default.** Especially `firmware/esp32_eye_ws_firmware/secrets.py`.
6. **Do not use `.venv/` as project source.** It is dependency state only.
7. **Archive, do not delete, unless user explicitly asks.** Historical files may still be useful for recovery.

---

## 1. Current project identity

Current project state:

- Laptop-first webcam gaze tracking prototype.
- Uses OpenCV + MediaPipe FaceMesh + NumPy.
- Extracts eye/iris features and outputs `x_ctrl`, `y_ctrl`, `confidence`.
- Has session gating for kiosk/multi-user style use.
- Current demo/debug actuation path is **single-eye servo over USB UART to ESP32-S3**.
- WiFi/WebSocket firmware still exists for later wireless demo work, but UART is the preferred path to get the physical demo running first.

Do **not** treat this as a fresh research project unless user says so. Current goal is usually to stabilize/maintain/upgrade a working prototype.

---

## 2. Read order for future agents

Read this set first for nearly every task:

1. `AGENT_CONTEXT.md` — this file.
2. `config.yaml` — active runtime parameters.
3. `main.py` — actual runtime wiring and control flow.
4. `gaze_estimator.py` — eye/iris measurement and gaze output.
5. `session_manager.py` — session lifecycle/gating.
6. `servo_mapper.py` — maps gaze to one-eye pan/tilt.
7. `servo_ws.py` — WebSocket command server.
8. `web_ui_server.py` — browser preview/HUD server.
9. Relevant tests under `tests/`.

Read only when relevant:

- `calibration.py`, `calibration_coupled.py`, `calibration_quality.py` for calibration changes.
- `benchmark_utils.py` and `tools/analyze_raw_signals.py` for benchmark/log/report work.
- `firmware/esp32_eye_uart_firmware/README.md` and `firmware/esp32_eye_uart_firmware/main.py` for current USB UART board firmware work.
- `firmware/esp32_eye_ws_firmware/README.md` and `firmware/esp32_eye_ws_firmware/main.py` only for later wireless/WebSocket work.
- `draw_utils.py` for OpenCV overlay changes.
- `tools/` for offline analysis/export utilities.

Avoid by default:

- `.venv/`
- `__pycache__/`
- `archive/legacy_2026-05-13/`
- old `benchmark_data/` sessions unless doing benchmark analysis
- `firmware/esp32_eye_ws_firmware/secrets.py`

---

## 3. Active runtime flow

`main.py` is the orchestrator. Per frame it currently does:

1. Open live camera or replay video.
2. Copy raw frame for recording if enabled.
3. Mirror frame if `mirror: true`.
4. Run `GazeEstimator.process(frame, calibration_manager.model)`.
5. Update `CalibrationManager` if calibration is active.
6. Update FPS and elapsed time.
7. Update `SessionManager` using:
   - `face_detected`
   - `confidence`
   - `x_eye`
   - `y_eye`
8. If session reset is required:
   - `estimator.reset_filters()`
   - `estimator.reset_raw_center()`
   - `session_manager.acknowledge_reset()`
9. Generate servo command through `SingleEyeServoMapper.update(...)`.
10. Optionally write serial command.
11. Optionally broadcast WebSocket command.
12. Optionally update live protocol labels.
13. Optionally log benchmark JSONL.
14. Draw overlay.
15. Optionally update browser MJPEG stream.
16. Handle keyboard controls.
17. On exit, finalize video/log/summary/labels and close resources.

If a change affects user-visible behavior, trace this full chain before claiming success.

---

## 4. Current important config facts

From `config.yaml` as of this curation:

### Camera/UI

- `camera_index: 0`
- `camera_fallback_indices: [0, 1, 2, 3]`
- `camera_backends: default, dshow, msmf`
- `frame_width: 1280`
- `frame_height: 720`
- `mirror: true`
- `window_name: "Gaze Control"`
- `debug: true`

### Gaze estimation

- `head_pose_enabled: false` by default.
- `vertical_feature_mode: "current"` by default.
- Valid `vertical_feature_mode` values in current code:
  - `current`
  - `orbital_relative`
- `smoothing_alpha: 0.55`
- `smoothing_alpha_y: 0.42`
- `dead_zone: 0.03`
- `dead_zone_y: 0.05`
- `control_scale_x: 1.6`
- `control_scale_y: 1.8`

### Session lifecycle

- `session_acquire_frames: 10`
- `session_baseline_hold_s: 1.5`
- `session_lost_face_timeout_s: 1.0`
- `session_min_confidence: 0.35`
- `session_drift_threshold: 0.25`
- `kiosk_quick_calibration_enabled: true`

### Calibration

- `autoload_calibration: true`
- model path: `calibration_data/calibration.json`
- `calibration.mode: axis5`
- `calibration.points: axis5`
- `calibration.coupled_basis: affine`

### Servo

Active single-eye config:

- `confidence_min: 0.45`
- `session_required: true`
- `smoothing_alpha: 0.20`
- `max_step_deg: 3.0`
- pan:
  - logical horizontal axis, UART firmware writes GPIO42 and GPIO39
  - neutral 90
  - range 50..130
  - gain 40
  - inverted
- tilt:
  - logical vertical axis, UART firmware writes GPIO41 and GPIO38
  - neutral 0
  - range 0..50
  - gain 50
  - inverted

---

## 5. Active firmware and hardware boundary

Current active demo/debug ESP32 path:

```text
firmware/esp32_eye_uart_firmware/
```

Architecture:

- Laptop runs Python app and sends newline-terminated packets over USB serial.
- ESP32-S3 receives packets over USB UART and drives one eye / four 180-degree servos.
- Packet shape:

```text
EYE,pan,tilt,gate
```

Run laptop app with UART output:

```powershell
.\.venv\Scripts\python.exe main.py --servo-port COM5
```

Replace `COM5` with the real ESP32 serial port.

Current UART firmware safe pins/ranges from the hardware-tested script:

```text
Horizontal axis servos -> GPIO42, GPIO39, neutral 90, range 50..130
Vertical axis servos   -> GPIO41, GPIO38, neutral 0,  range 0..50
```

Current wireless ESP32 path for later demo work:

```text
firmware/esp32_eye_ws_firmware/
```

Wireless architecture:

- Laptop runs Python app and is WebSocket server.
- ESP32-S3 is WiFi WebSocket client.
- Laptop broadcasts compact JSON command:

```json
{"type":"eye","pan":90,"tilt":80,"gate":"tracking"}
```

WebSocket firmware README says servo pins are:

```text
PAN  lt -> GPIO5
TILT lp -> GPIO4
```

Safety expectations:

- Servo uses external 5V power.
- ESP32 and servo power share GND.
- Firmware should neutral/fail-safe when packets stop.

Older USB-serial firmware was archived here:

```text
archive/legacy_2026-05-13/esp32_eye_firmware_serial_legacy/
```

Do not use archived serial firmware as current architecture. Use `firmware/esp32_eye_uart_firmware/` instead.

---

## 6. File ownership map

### Runtime / app shell

- `main.py`
  - CLI args
  - camera/replay open
  - runtime loop
  - calibration lifecycle
  - session lifecycle integration
  - servo serial/WebSocket dispatch
  - benchmark logging
  - overlay/browser UI updates

- `config.yaml`
  - active runtime parameters
  - any behavior change should start by checking if config already controls it

### Gaze estimation

- `gaze_estimator.py`
  - MediaPipe FaceMesh init
  - landmark-to-pixel conversion
  - iris/eye geometry extraction
  - vertical feature selection
  - per-eye quality
  - binocular/mono fusion
  - confidence gating
  - smoothing / hold / decay behavior

- `constants.py`
  - MediaPipe landmark indices
  - calibration point definitions
  - feature names

- `filters.py`
  - clamp, dead zone, EMA helpers

### Calibration

- `calibration.py`
  - `AxisCalibrationModel`
  - legacy linear model support
  - `CalibrationManager`
  - save/load/recenter/update logic

- `calibration_coupled.py`
  - coupled affine/quadratic calibration model

- `calibration_quality.py`
  - model quality metrics and validation helpers

### Session/control output

- `session_manager.py`
  - deterministic session state machine
  - states include `idle`, `acquire_face`, `baseline_lock`, `active`, `needs_recenter`

- `servo_mapper.py`
  - maps `x_ctrl/y_ctrl/confidence/session_ready/output_source/calibration_active` to one-eye `pan_deg/tilt_deg/gate_state/reason`
  - protects servo from calibration, low confidence, session not ready, held gaze output

- `servo_ws.py`
  - background asyncio WebSocket server
  - formats command JSON

- `servo_serial.py`
  - older/laptop-side serial packet helper still present
  - not the active firmware route, but may be useful for tests or fallback

### UI/logging/tools

- `draw_utils.py`
  - OpenCV overlay and debug visuals

- `web_ui_server.py`
  - MJPEG frame stream and browser HUD

- `benchmark_utils.py`
  - protocol labels
  - JSONL per-frame logs
  - summaries
  - replay/live label tracking

- `tools/`
  - offline scripts for raw signal analysis, crop export, auto annotation, candidate comparison

### Tests

- `tests/`
  - current executable contract
  - after archive cleanup, full suite currently has 35 tests

---

## 7. Refactor policy

Use this process before any non-trivial refactor:

1. **Identify behavior contract**
   - What observable behavior must stay the same?
   - Which test already protects it?
   - If no test protects it, add a small characterization test first.

2. **Choose the narrowest seam**
   - Prefer extracting pure helpers from `main.py`/`gaze_estimator.py` over redesigning control flow.
   - Do not mix refactor with tuning changes.
   - Do not change config defaults during a refactor unless explicitly required.

3. **Preserve runtime defaults**
   - Keep existing `config.yaml` semantics.
   - Keep keyboard controls stable.
   - Keep servo safety gates stable.

4. **Verify in layers**
   - unit tests for changed modules
   - full test suite if broad change
   - smoke/replay if runtime loop touched
   - hardware/UI note if not physically tested

5. **Update this file**
   - If ownership, commands, active firmware, or architecture changes, update `AGENT_CONTEXT.md` in same change.

Refactor candidates that are probably safe if done carefully:

- Split `main.py` runtime loop helpers, but keep CLI and behavior stable.
- Isolate benchmark setup/finalization into helpers.
- Add pure tests around servo mapping/config parsing.
- Add typed config loaders gradually.

Refactor candidates that are risky:

- Rewriting `gaze_estimator.py` fusion/confidence/smoothing in one pass.
- Changing vertical feature defaults.
- Changing session reset behavior.
- Changing servo ranges/inversion/gates.
- Replacing MediaPipe pipeline.

---

## 8. Maintenance policy

### Dependency upgrades

Current dependencies from `requirements.txt`:

```text
mediapipe==0.10.14
opencv-python>=4.10,<5
numpy>=1.26,<3
PyYAML>=6.0,<7
pyserial>=3.5,<4
websockets>=12,<16
```

Maintenance rules:

- Keep `mediapipe==0.10.14` pinned unless explicitly testing FaceMesh API compatibility.
- After changing dependencies, run full tests.
- If MediaPipe/OpenCV changes, also run a smoke camera/replay path.
- Do not assume Python version. User preference is `py -3`.

### Config maintenance

- `config.yaml` is runtime truth for tunables.
- Do not silently change servo range/gain/inversion.
- If adding a config key:
  - provide a default in code
  - document it here if operationally important
  - add/update tests if behavior changes

### Benchmark/log maintenance

- Keep JSONL schema backward-friendly when possible.
- If adding fields, don't remove existing fields unless necessary.
- Old benchmark reports are not current truth; use them only for analysis tasks.

### Firmware maintenance

- For the current demo, keep laptop UART packet contract and ESP32 UART parser in sync.
- If UART packet changes, update:
  - `servo_serial.py`
  - `firmware/esp32_eye_uart_firmware/main.py`
  - `firmware/esp32_eye_uart_firmware/README.md`
  - tests
  - this file
- If WebSocket payload changes later, update:
  - `servo_ws.py`
  - `firmware/esp32_eye_ws_firmware/main.py`
  - `firmware/esp32_eye_ws_firmware/README.md`
  - tests
  - this file

---

## 9. Upgrade policy

Treat upgrades as explicit tracks. Do not combine tracks unless user approves.

### Track A — Runtime stability

Goal: keep laptop runtime reliable.

Allowed work:

- camera fallback robustness
- clean startup/shutdown
- better error messages
- safer no-window/replay behavior
- logging without changing estimator behavior

Verification:

```powershell
py -3 -m unittest discover -s tests
py -3 main.py --no-window --max-frames 120
```

Camera smoke may fail if no camera is available; report that as environment/hardware, not code success.

### Track B — Gaze estimation quality

Goal: improve `x_ctrl/y_ctrl/confidence` behavior.

Rules:

- Add characterization tests or replay comparisons first.
- Do not change multiple tuning dimensions at once.
- Keep `vertical_feature_mode` default stable unless live evidence says otherwise.
- If changing vertical behavior, log current vs candidate when possible.

Verification:

- relevant unit tests
- full test suite
- replay/benchmark comparison if available

### Track C — Servo behavior

Goal: improve physical eye motion without unsafe jumps.

Rules:

- Preserve confidence/session/calibration gates unless explicitly changing safety policy.
- Do not widen servo range without hardware confirmation.
- Respect neutral positions.
- If hardware not connected, say so.

Verification:

- `tests/test_single_eye_servo_mapper.py`
- `tests/test_servo_config_gain.py`
- `tests/test_esp32_serial_transport.py`
- `tests/test_esp32_uart_firmware_package.py`
- WebSocket/server tests if touching WS
- optional hardware test with user present

### Track D — Web UI / operator UX

Goal: make monitoring/control easier.

Rules:

- Browser UI is secondary to runtime correctness.
- Verify served HTML and WebSocket port assumptions.
- If changing UI, check `web_ui_server.py`, `servo_ws.py`, and `main.py` together.

Verification:

- `tests/test_web_ui_server.py`
- relevant WebSocket tests
- manual browser check if available

### Track E — Firmware

Goal: stable ESP32 client/servo control.

Rules:

- Do not put real WiFi credentials in committed files.
- Update `secrets_example.py`, not `secrets.py`, for examples.
- Keep watchdog/fail-safe behavior.
- Current demo-first firmware is USB UART in `firmware/esp32_eye_uart_firmware/`.
- WiFi/WebSocket firmware remains available but should not be the default debug path.

Verification:

- firmware package tests
- syntax/static review where possible
- board test only when hardware is connected

---

## 10. Verification matrix

Use the smallest relevant set, then full suite for broad changes.

| Change area | Minimum verification |
|---|---|
| docs only | read changed docs; no runtime claim |
| config parser/defaults | targeted tests + full suite |
| `main.py` loop | full suite + no-window smoke/replay if possible |
| `gaze_estimator.py` | gaze/calibration tests + full suite + smoke/replay if possible |
| calibration | calibration tests + save/load check if touched |
| session manager | `tests/test_session_manager.py` + integration tests if gating touched |
| servo mapper | servo mapper/config tests |
| WebSocket server | WS tests + optional local client smoke |
| Web UI | web UI tests + manual browser note if not tested |
| ESP32 UART firmware | `tests/test_esp32_uart_firmware_package.py` + hardware note |
| ESP32 WebSocket firmware | `tests/test_esp32_ws_firmware_package.py` + hardware note |
| dependencies | full suite + import/smoke path |

Current full-suite command:

```powershell
py -3 -m unittest discover -s tests
```

Verified after cleanup on 2026-05-13:

```text
Ran 35 tests in 0.926s
OK
```

---

## 11. Archive policy

Archived stale/history files live here:

```text
archive/legacy_2026-05-13/
```

Archived content:

- old Problem A synthesis and external-agent docs
- old benchmark protocol markdown
- old root README
- old `docs/superpowers/` plans/specs
- old USB-serial ESP32 firmware folder
- old serial firmware package test
- old `.qwen` settings
- old `.planning/debug` notes

Reason: user explicitly said old code/docs are outdated and newest manual runtime edits are closer to working.

Rules:

- Future agents should not read archive by default.
- If using archive, state why it is relevant.
- Do not move archived material back into active root without user intent.
- If adding new obsolete docs/code, put them under dated archive folder and update this section.

---

## 12. Quick start for future agents

If asked to fix/upgrade something:

1. Read `AGENT_CONTEXT.md`.
2. Read `config.yaml`.
3. Read only the active files for the requested area.
4. State a short plan if the change is multi-file.
5. Edit minimal code/docs.
6. Run targeted tests.
7. Run full suite if behavior changed broadly.
8. Report exact evidence and any unverified hardware/UI caveats.

Default full test:

```powershell
py -3 -m unittest discover -s tests
```

Default runtime smoke:

```powershell
py -3 main.py --no-window --max-frames 120
```

Default UART servo run for demo:

```powershell
.\.venv\Scripts\python.exe main.py --servo-port COM5
```

Replace `COM5` with the ESP32 board port.

Before gaze control, run the interactive mechanical limit test:

```powershell
.\.venv\Scripts\python.exe tools\servo_uart_mechanical_test.py --port COM5
```

This sends the safe pan/tilt range one step at a time and waits for Enter before each movement.

Default WebSocket run for later wireless demo:

```powershell
.\.venv\Scripts\python.exe main.py --servo-ws-host 0.0.0.0 --servo-ws-port 8765
```

Default Web UI run:

```powershell
.\.venv\Scripts\python.exe main.py --web-ui-host 0.0.0.0 --web-ui-port 8080
```
