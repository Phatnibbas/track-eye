"""
ESP32-S3 — 2 con mắt ĐẢO VÒNG TRÒN (MicroPython / Thonny).
4 servo: 2 mắt x (pan ngang + tilt dọc). Nguồn servo 5V RIÊNG, GND chung ESP32.

Biên đo thực tế:
    pan  (ngang): thẳng 80, biên 40..140
    tilt (dọc)  : thẳng 60, trên 110 / dưới 20
Dùng biên độ đối xứng quanh tâm cho vòng tròn đều & an toàn.

Chạy F5: 2 mắt về giữa 1s rồi xoay vòng tròn liên tục. Ctrl+C để dừng.
"""
from machine import Pin, PWM
import time
import math

PINS = {"L_pan": 11, "L_tilt": 12, "R_pan": 13, "R_tilt": 14}
pwm = {n: PWM(Pin(p), freq=50) for n, p in PINS.items()}

PAN_C, PAN_AMP = 80, 40      # ngang: 40..120
TILT_C, TILT_AMP = 60, 40    # dọc:  20..100
SPEED = 0.06                 # tốc độ xoay (rad/bước); to hơn = quay nhanh hơn


def write(name, deg):
    deg = max(0, min(180, deg))
    us = 500 + 2000 * deg / 180        # SG90 500..2500us
    pwm[name].duty_ns(int(us * 1000))


def both(pan, tilt):
    write("L_pan", pan)
    write("R_pan", pan)
    write("L_tilt", tilt)
    write("R_tilt", tilt)


def center():
    both(PAN_C, TILT_C)


center()
time.sleep(1)
print("Dao mat vong tron. Ctrl+C de dung.")
try:
    th = 0.0
    while True:
        pan = PAN_C + PAN_AMP * math.cos(th)
        tilt = TILT_C + TILT_AMP * math.sin(th)
        both(pan, tilt)
        th += SPEED
        time.sleep_ms(20)
except KeyboardInterrupt:
    center()
    print("stopped")
