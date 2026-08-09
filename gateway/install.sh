#!/usr/bin/env bash
set +e
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/ha-antplus-gateway"
ENV_FILE="/etc/ha-antplus-gateway.env"
SERVICE_FILE="/etc/systemd/system/ha-antplus-gateway.service"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo ./install.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip libusb-1.0-0

mkdir -p "$INSTALL_DIR"
cp "$SOURCE_DIR/antplus_gateway.py" "$INSTALL_DIR/antplus_gateway.py"
cp "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/requirements.txt"

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"

cp "$SOURCE_DIR/ha-antplus-gateway.service" "$SERVICE_FILE"

if [ ! -f "$ENV_FILE" ]; then
  cp "$SOURCE_DIR/ha-antplus-gateway.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE"
fi

systemctl daemon-reload
systemctl enable ha-antplus-gateway.service

echo "Installation complete."
echo "Edit $ENV_FILE, then run:"
echo "sudo systemctl restart ha-antplus-gateway"
echo "sudo journalctl -u ha-antplus-gateway -f"
