#!/usr/bin/env bash
set +e
if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo ./uninstall.sh"
  exit 1
fi
systemctl disable --now ha-antplus-gateway.service 2>/dev/null
rm -f /etc/systemd/system/ha-antplus-gateway.service
systemctl daemon-reload
rm -rf /opt/ha-antplus-gateway
echo "Gateway application removed."
echo "Configuration kept at /etc/ha-antplus-gateway.env"
