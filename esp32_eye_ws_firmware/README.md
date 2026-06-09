# ESP32 Eye WebSocket Firmware

Laptop là WebSocket host/server. ESP32-S3 là WiFi WebSocket client.

## Files upload bằng Thonny

Upload vào ESP32:

```text
main.py
secrets.py
```

Tạo `secrets.py` trên board dựa từ `secrets_example.py`:

```python
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "<nhập password trên board, không commit>"
SERVER_HOST = "192.168.1.22"
SERVER_PORT = 8765
SERVER_PATH = "/"
```

## Laptop command

Tìm IP laptop trong WiFi YOUR_WIFI_SSID:

```powershell
ipconfig
```

Sau đó chạy app laptop:

```powershell
.\.venv\Scripts\python.exe main.py --calibration-path calibration_data\calibration_glasses.json --servo-ws-host 0.0.0.0 --servo-ws-port 8765
```

ESP32 sẽ connect tới `ws://SERVER_HOST:8765/`.

## Packet

Laptop gửi JSON WebSocket:

```json
{"type":"eye","pan":90,"tilt":80,"gate":"tracking"}
```

## Servo pins

```text
PAN  lt -> GPIO5
TILT lp -> GPIO4
```

## Safety

- Servo dùng nguồn 5V ngoài.
- GND nguồn servo nối chung ESP32 GND.
- Watchdog: mất packet >900ms thì mắt về neutral.
- Nếu servo kẹt/buzz, ngắt nguồn ngay.
