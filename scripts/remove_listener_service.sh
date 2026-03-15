#!/usr/bin/env bash
set -euo pipefail
SERVICE_NAME="QQListener"

systemctl --user disable --now "${SERVICE_NAME}.service"
rm -f ~/.config/systemd/user/"${SERVICE_NAME}.service"
systemctl --user daemon-reload
systemctl --user reset-failed
