#!/usr/bin/env bash
# Launch the Track Eye per-eye pupil demo.
# Used by the systemd service (pupil.service) and for manual runs.
set -euo pipefail
cd "$(dirname "$0")"
exec ./.venv/bin/python -u tools/pupil_spike.py --web-ui-host 0.0.0.0 "$@"
