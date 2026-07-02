# ESP32 Eye USB UART Firmware — 4 Servo Demo

This is the active **USB UART demo/debug firmware** for the current four-servo 180-degree eye mechanism.

Short label: 4 servo USB UART demo.

Use this when the priority is: **make the demo run first, with fewer WiFi/IP variables**.

## Hardware-tested pins

From the previously working servo script:

```text
Horizontal axis servos: GPIO42, GPIO39
Vertical axis servos:   GPIO41, GPIO38
```

The mechanism uses one logical pan angle and one logical tilt angle:

```text
pan  -> written to both horizontal servos
tilt -> written to both vertical servos
```

PWM direction from the tested script:

```text
horizontal duty = duty(180 - pan)
vertical duty   = duty(tilt)
```

## Safe demo range

Current safe range used by both firmware and `config.yaml`:

```text
PAN:  neutral 90, range 50..130
TILT: neutral 0,  range 0..50
```

Do not widen these until the physical mechanism is re-tested.

## Upload with Thonny

1. Open `esp32_eye_uart_firmware/main.py`.
2. Save it to the ESP32-S3 board as `main.py`.
3. Reset the board.
4. The board waits for USB serial packets.

## Laptop command

Find the ESP32 COM port in Windows Device Manager or Thonny, then run:

```powershell
.\.venv\Scripts\python.exe main.py --servo-port COM5
```

Replace `COM5` with the real board port.

The app still runs normally; `--servo-port` only adds USB UART servo output.

## Protocol

Laptop sends newline-terminated ASCII packets:

```text
EYE,pan,tilt,gate
```

Examples:

```text
EYE,90,0,neutral
EYE,92,12,tracking
EYE,92,12,hold
```

Gate behavior:

- `tracking`: move toward the received pan/tilt target.
- `hold`: keep the previous target; watchdog still returns to neutral if packets stop.
- `neutral`: move toward neutral.

Firmware rate limits movement:

```text
MAX_STEP_DEG = 3
LOOP_DELAY_MS = 20
WATCHDOG_TIMEOUT_MS = 900
```

## Safety

- Use external 5V servo power.
- Connect ESP32 GND and servo power GND together.
- Do not power four servos from ESP32 5V/3V3 pins.
- If any servo buzzes hard, heats, or hits an end stop: disconnect servo power.
- If valid packets stop for `WATCHDOG_TIMEOUT_MS`, firmware targets neutral.
