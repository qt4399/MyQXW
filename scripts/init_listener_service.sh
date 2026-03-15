#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="QQListener"
SERVICE_FILE="${HOME}/.config/systemd/user/${SERVICE_NAME}.service"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "${HOME}/.config/systemd/user"

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=QQListener
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_BIN} ${PROJECT_DIR}/qq_api_reference/napcat_listener.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

read -r -p "是否要开启开机自启动(强烈建议开启)(y/n) " response
if [[ "${response,,}" == "y" ]]; then
  systemctl --user enable --now "${SERVICE_NAME}.service"
  echo "已创建、启动并开启开机自启动：${SERVICE_NAME}.service"
else
  systemctl --user start "${SERVICE_NAME}.service"
  echo "已创建并启动 ${SERVICE_NAME}.service，未开启开机自启动"
fi

echo "service 文件：${SERVICE_FILE}"
echo "查看状态：systemctl --user status ${SERVICE_NAME}.service"
echo "查看日志：journalctl --user -u ${SERVICE_NAME}.service -f"

