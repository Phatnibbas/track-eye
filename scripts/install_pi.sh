#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/pi5/track-eye"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/home/pi5/track-eye-rollbacks/${STAMP}"
mkdir -p "$BACKUP"
crontab -l > "$BACKUP/crontab-before.txt" 2>/dev/null || true
sudo cp /etc/systemd/system/pupil.service "$BACKUP/pupil.service-before" 2>/dev/null || true
sudo sha256sum "$BACKUP/pupil.service-before" > "$BACKUP/pupil.service-before.sha256" 2>/dev/null || true

if crontab -l 2>/dev/null | grep -Fq '@reboot sleep 15 && /home/pi5/track-eye/run_pupil.sh >> /home/pi5/track-eye/pupil.log 2>&1'; then
  crontab -l | grep -Fv '@reboot sleep 15 && /home/pi5/track-eye/run_pupil.sh >> /home/pi5/track-eye/pupil.log 2>&1' | crontab -
fi
sudo install -m 0644 "$ROOT/deploy/track-eye.service" /etc/systemd/system/track-eye.service
sudo systemctl daemon-reload
sudo systemctl disable --now pupil.service || true
sudo systemctl enable --now track-eye.service
sudo systemctl --no-pager --full status track-eye.service
