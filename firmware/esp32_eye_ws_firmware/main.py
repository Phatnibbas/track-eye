"""ESP32-S3 MicroPython WebSocket client for one eye / two 180 servos.

Laptop is the WebSocket server. ESP32 connects as client and receives JSON:
    {"type":"eye","pan":90,"tilt":80,"gate":"tracking"}

Fill in WiFi credentials on the board only. Do not commit real secrets.
"""

from machine import Pin, PWM
from time import sleep_ms, ticks_ms, ticks_diff
import json
import network
import socket
import ubinascii
import uhashlib

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "PUT_PASSWORD_HERE_ON_BOARD_ONLY"
SERVER_HOST = "192.168.1.22"
SERVER_PORT = 8765
SERVER_PATH = "/"


SERVO_FREQ_HZ = 50
MIN_US = 500
MAX_US = 2500
PAN_PIN = 5
TILT_PIN = 4
PAN_NEUTRAL = 90
PAN_MIN = 40
PAN_MAX = 140
TILT_NEUTRAL = 80
TILT_MIN = 40
TILT_MAX = 120
WATCHDOG_TIMEOUT_MS = 900
MAX_STEP_DEG = 3
LOOP_DELAY_MS = 20


def clamp(value, low, high):
    return max(low, min(high, int(value)))


def angle_to_us(angle):
    angle = clamp(angle, 0, 180)
    return MIN_US + ((MAX_US - MIN_US) * angle // 180)


def write_servo(pwm, angle):
    pwm.duty_ns(angle_to_us(angle) * 1000)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting WiFi", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected():
            sleep_ms(250)
    print("WiFi", wlan.ifconfig())
    return wlan


def websocket_handshake(sock, host, port, path):
    # RFC6455 requires Sec-WebSocket-Key to be base64 of exactly 16 bytes.
    key = ubinascii.b2a_base64(b"esp32-eye-key123").strip().decode()
    request = (
        "GET {} HTTP/1.1\r\n"
        "Host: {}:{}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: {}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).format(path, host, port, key)
    sock.send(request.encode())
    response = sock.recv(512)
    if b"101" not in response.split(b"\r\n", 1)[0]:
        raise RuntimeError("WebSocket handshake failed: {}".format(response))


def read_exact(sock, n):
    data = b""
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
        except OSError:
            return None
        if not chunk:
            raise RuntimeError("socket closed")
        data += chunk
    return data


def read_ws_text_frame(sock):
    header = read_exact(sock, 2)
    if header is None:
        return None
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    if length == 126:
        ext = read_exact(sock, 2)
        if ext is None:
            return None
        length = (ext[0] << 8) | ext[1]
    elif length == 127:
        raise RuntimeError("large ws frame unsupported")
    payload = read_exact(sock, length)
    if payload is None:
        return None
    if opcode == 8:
        raise RuntimeError("ws close")
    if opcode != 1:
        return None
    return payload.decode()


def connect_ws():
    addr = socket.getaddrinfo(SERVER_HOST, SERVER_PORT)[0][-1]
    sock = socket.socket()
    sock.connect(addr)
    websocket_handshake(sock, SERVER_HOST, SERVER_PORT, SERVER_PATH)
    sock.settimeout(0.05)
    print("WebSocket connected to {}:{}".format(SERVER_HOST, SERVER_PORT))
    return sock


def parse_command(text):
    payload = json.loads(text)
    if payload.get("type") != "eye":
        return None
    return (
        clamp(payload.get("pan", PAN_NEUTRAL), PAN_MIN, PAN_MAX),
        clamp(payload.get("tilt", TILT_NEUTRAL), TILT_MIN, TILT_MAX),
        str(payload.get("gate", "hold")),
    )


def approach(current, target):
    delta = clamp(target - current, -MAX_STEP_DEG, MAX_STEP_DEG)
    return current + delta


pan_pwm = PWM(Pin(PAN_PIN), freq=SERVO_FREQ_HZ)
tilt_pwm = PWM(Pin(TILT_PIN), freq=SERVO_FREQ_HZ)
current_pan = PAN_NEUTRAL
current_tilt = TILT_NEUTRAL
target_pan = PAN_NEUTRAL
target_tilt = TILT_NEUTRAL
last_packet_ms = ticks_ms()
write_servo(pan_pwm, current_pan)
write_servo(tilt_pwm, current_tilt)

connect_wifi()

while True:
    try:
        ws = connect_ws()
        while True:
            text = read_ws_text_frame(ws)
            if text is not None:
                command = parse_command(text)
                if command is not None:
                    pan, tilt, gate = command
                    print("RX pan={} tilt={} gate={}".format(pan, tilt, gate))
                    if gate == "tracking":
                        target_pan = pan
                        target_tilt = tilt
                    elif gate == "neutral":
                        target_pan = PAN_NEUTRAL
                        target_tilt = TILT_NEUTRAL
                    last_packet_ms = ticks_ms()

            if ticks_diff(ticks_ms(), last_packet_ms) > WATCHDOG_TIMEOUT_MS:
                target_pan = PAN_NEUTRAL
                target_tilt = TILT_NEUTRAL

            current_pan = approach(current_pan, target_pan)
            current_tilt = approach(current_tilt, target_tilt)
            write_servo(pan_pwm, current_pan)
            write_servo(tilt_pwm, current_tilt)
            sleep_ms(LOOP_DELAY_MS)
    except Exception as exc:
        print("WS error/reconnect:", exc)
        target_pan = PAN_NEUTRAL
        target_tilt = TILT_NEUTRAL
        write_servo(pan_pwm, target_pan)
        write_servo(tilt_pwm, target_tilt)
        sleep_ms(1000)
