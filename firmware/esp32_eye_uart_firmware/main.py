"""ESP32-S3 MicroPython firmware for USB UART 4-servo eye demo.

Laptop sends newline-terminated packets over USB serial:
    EYE,pan,tilt,gate

The physical mechanism uses four 180-degree servos:
    horizontal axis pins: 42, 39
    vertical axis pins:   41, 38

The PWM duty math intentionally matches the previously hardware-tested script:
    horizontal: duty from 180 - angle
    vertical:   duty from angle
"""

import sys
import uselect
from machine import Pin, PWM
from time import sleep_ms, ticks_diff, ticks_ms


SERVO_FREQ_HZ = 50

# Hardware-tested pins from the previous working script.
HORIZ_PINS = [42, 39]
VERT_PINS = [41, 38]

PAN_NEUTRAL = 90
PAN_MIN = 50
PAN_MAX = 130
TILT_NEUTRAL = 0
TILT_MIN = 0
TILT_MAX = 50

WATCHDOG_TIMEOUT_MS = 900
MAX_STEP_DEG = 3
LOOP_DELAY_MS = 20


def clamp(value, low, high):
    return max(low, min(high, int(value)))


def angle_to_duty(angle):
    # Matches previous tested code: int((angle / 180) * 102 + 26)
    angle = clamp(angle, 0, 180)
    return int((angle / 180) * 102 + 26)


def set_hardware_angles(pan, tilt):
    """Write hardware PWM for all 4 servos."""
    pan = clamp(pan, PAN_MIN, PAN_MAX)
    tilt = clamp(tilt, TILT_MIN, TILT_MAX)

    # Horizontal axis is mechanically inverted: 180 - angle.
    h_duty = angle_to_duty(180 - pan)
    v_duty = angle_to_duty(tilt)

    for servo in h_servos:
        servo.duty(h_duty)
    for servo in v_servos:
        servo.duty(v_duty)


def parse_eye_packet(line):
    # EYE,pan,tilt,gate
    parts = line.strip().split(",")
    if len(parts) != 4 or parts[0] != "EYE":
        return None
    try:
        pan = clamp(parts[1], PAN_MIN, PAN_MAX)
        tilt = clamp(parts[2], TILT_MIN, TILT_MAX)
    except Exception:
        return None
    gate = parts[3].strip()
    if gate not in ("tracking", "hold", "neutral"):
        return None
    return pan, tilt, gate


def approach(current, target):
    delta = clamp(target - current, -MAX_STEP_DEG, MAX_STEP_DEG)
    return current + delta


h_servos = [PWM(Pin(pin), freq=SERVO_FREQ_HZ) for pin in HORIZ_PINS]
v_servos = [PWM(Pin(pin), freq=SERVO_FREQ_HZ) for pin in VERT_PINS]

current_pan = PAN_NEUTRAL
current_tilt = TILT_NEUTRAL
target_pan = PAN_NEUTRAL
target_tilt = TILT_NEUTRAL
last_packet_ms = ticks_ms()

set_hardware_angles(current_pan, current_tilt)

poller = uselect.poll()
poller.register(sys.stdin, uselect.POLLIN)

print("ESP32 USB UART 4-servo eye firmware ready")
print("Protocol: EYE,pan,tilt,gate")
print("Horizontal pins: {} | Vertical pins: {}".format(HORIZ_PINS, VERT_PINS))
print("Safe ranges: pan {}..{} tilt {}..{}".format(PAN_MIN, PAN_MAX, TILT_MIN, TILT_MAX))

while True:
    if poller.poll(0):
        line = sys.stdin.readline()
        packet = parse_eye_packet(line)
        if packet is not None:
            pan, tilt, gate = packet
            if gate == "tracking":
                target_pan = pan
                target_tilt = tilt
            elif gate == "neutral":
                target_pan = PAN_NEUTRAL
                target_tilt = TILT_NEUTRAL
            # gate == "hold" keeps the previous target. Watchdog still
            # returns to neutral if valid packets stop.
            last_packet_ms = ticks_ms()
            print("OK pan={} tilt={} gate={}".format(target_pan, target_tilt, gate))
        else:
            print("ERR bad_packet")

    if ticks_diff(ticks_ms(), last_packet_ms) > WATCHDOG_TIMEOUT_MS:
        target_pan = PAN_NEUTRAL
        target_tilt = TILT_NEUTRAL

    current_pan = approach(current_pan, target_pan)
    current_tilt = approach(current_tilt, target_tilt)
    set_hardware_angles(current_pan, current_tilt)
    sleep_ms(LOOP_DELAY_MS)
