"""
ESP32-S3 EYE FOLLOWER — nhận góc servo qua WiFi UDP từ Pi5, lái 4 servo.
MicroPython (nạp qua Thonny).

Protocol (1 datagram/frame, UDP port 8770):
    EYES,<Lpan>,<Ltilt>,<Rpan>,<Rtilt>,<gate>\n     gate = tracking | hold | neutral

Cài đặt:
  1. Copy hardware/secrets.example.py -> secrets.py, điền WIFI_SSID/WIFI_PASS (cùng wifi Pi5).
  2. Nạp secrets.py + file này lên ESP32, chạy F5. Boot in ra IP.
  3. Trên Pi: python tools/pupil_spike.py --web-ui-host 0.0.0.0 --udp-host <IP-ESP>
  4. Validate xong -> lưu file này thành main.py trên ESP để tự chạy khi cấp điện.

Data đi qua WiFi nên cổng USB/REPL để trống -> Thonny vẫn xem print() debug được.
Nguồn servo 5V RIÊNG, GND chung ESP32.
"""
import time
import network
import socket
import uselect
from machine import Pin, PWM

try:
    from secrets import WIFI_SSID, WIFI_PASS
except ImportError:
    raise SystemExit("Thiếu secrets.py (WIFI_SSID/WIFI_PASS). Copy từ secrets.example.py")
try:
    from secrets import UDP_PORT
except ImportError:
    UDP_PORT = 8770

# ---- CONFIG (khớp rig hiện tại) ----------------------------------------
PINS = {"L_pan": 11, "L_tilt": 12, "R_pan": 13, "R_tilt": 14}
PAN_NEUTRAL, PAN_MIN, PAN_MAX = 80, 40, 140
TILT_NEUTRAL, TILT_MIN, TILT_MAX = 60, 20, 110
MIN_US, MAX_US = 500, 2500        # xung servo (SG90). Rung biên -> 1000..2000
MAX_STEP_DEG = 3                  # slew ±3°/loop -> mượt, không giật
LOOP_MS = 20                      # ~50 Hz
WATCHDOG_MS = 900                 # không gói hợp lệ trong ngần này -> về neutral
DEBUG = True                      # in gói nhận (tối đa ~2/giây)
# ------------------------------------------------------------------------

NEUTRAL = {"L_pan": PAN_NEUTRAL, "L_tilt": TILT_NEUTRAL,
           "R_pan": PAN_NEUTRAL, "R_tilt": TILT_NEUTRAL}
LIMITS = {"L_pan": (PAN_MIN, PAN_MAX), "R_pan": (PAN_MIN, PAN_MAX),
          "L_tilt": (TILT_MIN, TILT_MAX), "R_tilt": (TILT_MIN, TILT_MAX)}


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class Servo:
    def __init__(self, pin):
        self.pwm = PWM(Pin(pin), freq=50)

    def write(self, deg):
        deg = clamp(deg, 0, 180)
        us = MIN_US + (MAX_US - MIN_US) * deg / 180
        self.pwm.duty_ns(int(us * 1000))


def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("wifi: connecting to", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASS)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > 20000:
                raise SystemExit("wifi: timeout - kiểm tra secrets.py / sóng")
            time.sleep_ms(200)
    ip = wlan.ifconfig()[0]
    print("wifi: OK  IP =", ip)
    return ip


def parse_packet(line):
    """'EYES,Lpan,Ltilt,Rpan,Rtilt,gate' -> (vals_dict, gate) or None."""
    parts = line.strip().split(",")
    if len(parts) != 6 or parts[0] != "EYES":
        return None
    gate = parts[5]
    if gate not in ("tracking", "hold", "neutral"):
        return None
    try:
        vals = {"L_pan": int(parts[1]), "L_tilt": int(parts[2]),
                "R_pan": int(parts[3]), "R_tilt": int(parts[4])}
    except ValueError:
        return None
    return vals, gate


def main():
    ip = wifi_connect()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("0.0.0.0", UDP_PORT))
    poller = uselect.poll()
    poller.register(sock, uselect.POLLIN)
    print("udp: listening", ip, ":", UDP_PORT)

    servos = {n: Servo(p) for n, p in PINS.items()}
    cur = dict(NEUTRAL)          # góc hiện tại (đi dần)
    target = dict(NEUTRAL)       # góc đích
    for n in servos:
        servos[n].write(cur[n])

    last_rx = time.ticks_ms()
    last_dbg = last_rx

    while True:
        now = time.ticks_ms()

        # rút hết gói đang chờ, giữ gói hợp lệ cuối cùng
        got = None
        while poller.poll(0):
            try:
                data, _ = sock.recvfrom(128)
            except OSError:
                break
            parsed = parse_packet(data.decode("utf-8"))
            if parsed is not None:
                got = parsed

        if got is not None:
            vals, gate = got
            last_rx = now
            if gate == "tracking":
                for n in target:
                    lo, hi = LIMITS[n]
                    target[n] = clamp(vals[n], lo, hi)
            elif gate == "neutral":
                target = dict(NEUTRAL)
            # gate == "hold": giữ target cũ (watchdog vẫn chạy)
            if DEBUG and time.ticks_diff(now, last_dbg) > 500:
                print("rx", gate, vals)
                last_dbg = now

        # watchdog: mất tín hiệu -> về giữa
        if time.ticks_diff(now, last_rx) > WATCHDOG_MS:
            target = dict(NEUTRAL)

        # slew tới target rồi xuất PWM
        for n in servos:
            delta = target[n] - cur[n]
            if delta > MAX_STEP_DEG:
                delta = MAX_STEP_DEG
            elif delta < -MAX_STEP_DEG:
                delta = -MAX_STEP_DEG
            cur[n] += delta
            servos[n].write(cur[n])

        time.sleep_ms(LOOP_MS)


main()
