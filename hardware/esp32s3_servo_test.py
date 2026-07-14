"""
ESP32-S3 servo test — MicroPython (Thonny). 4 servo: 2 mắt x (pan+tilt).
Nguồn servo 5V RIÊNG, GND chung với ESP32.

Chạy F5 -> tất cả về 90 do. Rồi gõ ở Shell:
    go('L_pan', 120)     # đưa 1 servo tới góc bất kỳ (0..180)
    go('R_tilt', 60)
    center()             # tất cả về 90
"""
from machine import Pin, PWM

PINS = {"L_pan": 11, "L_tilt": 12, "R_pan": 13, "R_tilt": 14}
pwm = {n: PWM(Pin(p), freq=50) for n, p in PINS.items()}


def go(name, deg):
    deg = max(0, min(180, deg))
    us = 500 + (2500 - 500) * deg / 180     # SG90: 500..2500us. Rung biên -> đổi 1000..2000
    pwm[name].duty_ns(int(us * 1000))
    print(name, "=", deg, "deg")


def center():
    for n in pwm:
        go(n, 90)


center()
print("READY. Vd:  go('L_pan', 120)   |   center()")
