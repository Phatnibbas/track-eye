#!/usr/bin/env bash
# One-time installer: make the pupil demo auto-start on power-on (systemd).
# Run ON THE PI:   bash ~/track-eye/install_autostart.sh
# (asks for sudo to install the unit under /etc/systemd/system)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

# strip any CR (in case files came from Windows) so bash/systemd don't choke
sed -i 's/\r$//' "$DIR/run_pupil.sh" "$DIR/pupil.service"
chmod +x "$DIR/run_pupil.sh"

# stop any manual demo so it doesn't hold port 8080
pkill -f '[p]upil_spike.py' || true
sleep 1

sudo cp "$DIR/pupil.service" /etc/systemd/system/pupil.service
sudo systemctl daemon-reload
sudo systemctl enable --now pupil.service

echo "=== status ==="
systemctl --no-pager -l status pupil.service | head -12
echo
echo "Auto-start installed. It now runs on every power-on."
echo "Watch the stream at:  http://\$(hostname -I | awk '{print \$1}'):8080"
echo "Logs:   journalctl -u pupil -f"
echo "Stop:   sudo systemctl stop pupil     Disable: sudo systemctl disable pupil"
