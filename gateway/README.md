# HA ANT+ Remote Gateway

This gateway lets an ANT+ USB adapter connected to another Linux computer feed
the same HA ANT+ integration.

## Identity

ANT device ID is the canonical sensor identity. The same ANT ID received through
local and remote adapters is treated as the same sensor.

## Global Capture

The HA ANT+ `Capture` switch controls local and remote scanning.

## Remote Linux installation

1. Run `sudo ./install.sh`.
2. Edit `/etc/ha-antplus-gateway.env`.
3. Set `HA_URL`, `HA_TOKEN`, and `GATEWAY_ID`.
4. Run `sudo systemctl restart ha-antplus-gateway`.
5. Watch logs with `sudo journalctl -u ha-antplus-gateway -f`.

The gateway only makes an outbound WebSocket connection to Home Assistant.
