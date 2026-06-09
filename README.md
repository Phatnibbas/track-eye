# Track Eye — Current Runtime Entry Point

Read `docs/AGENT_CONTEXT.md` first.

This repo is currently a **laptop-first webcam gaze tracking + single-eye ESP32 servo prototype**. The current demo/debug connection is **USB UART** to a four-servo 180-degree eye mechanism. WiFi/WebSocket remains available for later wireless demos. Older research plans, stale docs, and legacy firmware were moved to `archive/legacy_2026-05-13/` so future agents do not anchor on outdated context.

## For future agents

Do not start by reading archive or old benchmark reports. Start here:

1. `docs/AGENT_CONTEXT.md`
2. `config.yaml`
3. `main.py`
4. the active module relevant to the task
5. relevant tests

## Current active areas

- Runtime loop: `main.py`
- Gaze estimation: `gaze_estimator.py`
- Session gating: `session_manager.py`
- Servo mapping: `servo_mapper.py`
- USB UART output: `servo_serial.py`
- WebSocket output: `servo_ws.py`
- Browser UI: `web_ui_server.py`
- Active demo ESP32 firmware: `firmware/esp32_eye_uart_firmware/`
- Optional wireless ESP32 firmware: `firmware/esp32_eye_ws_firmware/`
- Raspberry Pi 5 deployment spec: `docs/DEPLOYMENT_PI5.md`

## Quick verify

```powershell
py -3 -m unittest discover -s tests
```

## Main runtime

```powershell
py -3 main.py
```

## USB UART servo demo runtime

```powershell
.\.venv\Scripts\python.exe main.py --servo-port COM5
```

Replace `COM5` with the actual ESP32-S3 serial port.

## USB UART mechanical limit test first

Run this before using gaze control on the physical servo mechanism:

```powershell
.\.venv\Scripts\python.exe tools\servo_uart_mechanical_test.py --port COM5
```

It waits for Enter before each movement so you can stop if a servo buzzes or hits an end-stop.

## WebSocket servo runtime

```powershell
.\.venv\Scripts\python.exe main.py --servo-ws-host 0.0.0.0 --servo-ws-port 8765
```

## Browser UI runtime

```powershell
.\.venv\Scripts\python.exe main.py --web-ui-host 0.0.0.0 --web-ui-port 8080
```

## Maintenance rule

If a change affects runtime behavior, update `AGENT_CONTEXT.md` and run relevant tests before claiming completion.
