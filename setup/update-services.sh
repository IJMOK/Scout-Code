#!/usr/bin/env bash
# After `git pull`: refresh the systemd services and restart them. No internet needed.
#
#   sudo ./setup/update-services.sh
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Please run with sudo."; exit 1; fi

SCOUT_DIR=/opt/scout
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-pi}"
# shellcheck source=setup/lib.sh
source "$APP_DIR/setup/lib.sh"

install_shutdown_permission
restore_model_after_crash

SERVICES=()
for unit in scout-llm scout-stats scout-portal; do
  # Only update services this Pi already has (the worker has no portal).
  if [[ -f "/etc/systemd/system/$unit.service" ]]; then
    render_unit "$APP_DIR/setup/systemd/$unit.service"
    SERVICES+=("$unit")
  fi
done

systemctl daemon-reload
systemctl restart "${SERVICES[@]}"
echo "✅ Updated and restarted: ${SERVICES[*]}"
