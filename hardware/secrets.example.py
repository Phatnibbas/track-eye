# Copy file này thành  secrets.py  (đã bị .gitignore) rồi điền thông tin thật.
# Nạp cả secrets.py lên ESP32 cùng esp32s3_eye_follow.py.
# WiFi phải CÙNG mạng với Pi5.

WIFI_SSID = "MakerLabVN"
WIFI_PASS = "your-wifi-password"
UDP_PORT = 8770        # phải khớp --udp-port bên Pi (mặc định 8770)
