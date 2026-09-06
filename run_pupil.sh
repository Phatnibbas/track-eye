#!/usr/bin/env bash
# Launch the Track Eye per-eye pupil demo (perception + web UI + servo feed).
# Used by the systemd service (pupil.service) and for manual runs.
#
# ESP_HOST = nơi gửi góc servo qua UDP.
#   (bỏ trống / không đặt)  -> TỰ LẤY địa chỉ broadcast của mạng hiện tại.
#                              ESP32 nhận được dù DHCP đổi IP của nó -> zero-config.
#   192.168.1.182           -> gửi thẳng 1 IP (dùng khi AP chặn broadcast).
#   off                     -> tắt hẳn phần servo, chỉ tracking + web UI.
set -euo pipefail
cd "$(dirname "$0")"

ESP_HOST="${ESP_HOST:-}"
if [ -z "$ESP_HOST" ]; then
  # ví dụ dòng ip: "2: wlan0 inet 192.168.1.211/24 brd 192.168.1.255 scope global ..."
  ESP_HOST="$(ip -o -4 addr show scope global \
              | awk '{for (i = 1; i <= NF; i++) if ($i == "brd") { print $(i+1); exit }}')"
  ESP_HOST="${ESP_HOST:-255.255.255.255}"
fi

if [ "$ESP_HOST" = "off" ]; then
  echo "[run_pupil] servo output: OFF"
  exec ./.venv/bin/python -u tools/pupil_spike.py --web-ui-host 0.0.0.0 "$@"
fi

echo "[run_pupil] servo output -> $ESP_HOST"
exec ./.venv/bin/python -u tools/pupil_spike.py \
     --web-ui-host 0.0.0.0 --udp-host "$ESP_HOST" "$@"
