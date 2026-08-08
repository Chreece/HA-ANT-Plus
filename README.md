# HA ANT+

<p align="center"><img src="assets/ha-ant-plus-logo.png" alt="HA ANT+" width="500"></p>

[![HACS validation](https://github.com/Chreece/HA-ANT-Plus/actions/workflows/hacs.yml/badge.svg)](https://github.com/Chreece/HA-ANT-Plus/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/Chreece/HA-ANT-Plus/actions/workflows/hassfest.yml/badge.svg)](https://github.com/Chreece/HA-ANT-Plus/actions/workflows/hassfest.yml)
[![Tests](https://github.com/Chreece/HA-ANT-Plus/actions/workflows/tests.yml/badge.svg)](https://github.com/Chreece/HA-ANT-Plus/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**HA ANT+** is a local Home Assistant custom integration for receiving ANT+ sensor broadcasts through a compatible ANT USB adapter. It uses a single continuous scan channel, discovers ANT+ devices automatically, merges multiple ANT+ profiles that share the same ANT device number, and exposes decoded metrics as Home Assistant entities.

## Highlights

- Local-only ANT+ reception; no cloud service required.
- Automatic USB discovery for known Dynastream/Garmin ANT adapters.
- Automatic discovery of broadcasting ANT+ devices; no sensor IDs need to be entered.
- One Home Assistant device per ANT device number, even when a sensor exposes several ANT+ profiles.
- Curated decoders for common running, cycling and fitness metrics.
- Reuses compatible OpenANT profile parsers for broader profile coverage.
- Raw ANT pages remain available as disabled-by-default diagnostic entities for unsupported data.
- Live metric inactivity handling, with slower device/battery information handled separately.
- Start/stop capture control and diagnostic receiver state.

## Supported USB adapters

Automatic Home Assistant USB discovery currently includes:

| USB VID:PID | Adapter family | Status |
|---|---|---|
| `0FCF:1008` | Dynastream/Garmin ANTUSB2 and compatible rebrands using the same USB ID | **Confirmed** |
| `0FCF:1009` | Dynastream/Garmin ANTUSB-m family | Expected / supported by discovery |

Other ANT adapters may work with OpenANT when added manually, but they are **not claimed as supported until tested**. Please open a compatibility report with the adapter's VID/PID and logs if you successfully use another model.

## ANT+ profiles

The integration contains curated decoding for heart rate, power, fitness equipment, bike cadence, bike speed, combined bike speed/cadence and stride speed/distance. It also attempts to reuse OpenANT parsers for additional profiles when they are available. Unknown/unsupported pages are retained as disabled diagnostic raw-data entities rather than silently discarded.

Because ANT+ devices vary in the pages they transmit, available entities depend on the sensor and its current operating mode.

## Installation

### HACS

1. Open HACS in Home Assistant.
2. Add `https://github.com/Chreece/HA-ANT-Plus` as a **Custom repository** of type **Integration** until the repository is accepted into the default HACS catalog.
3. Install **HA ANT+**.
4. Restart Home Assistant.
5. Plug in a supported ANT USB adapter. Home Assistant should offer **HA ANT+** automatically under **Settings → Devices & services**.
6. Confirm setup.

### Manual

Copy `custom_components/antplus` into your Home Assistant configuration directory:

```text
/config/custom_components/antplus
```

Restart Home Assistant, then add **HA ANT+** from **Settings → Devices & services**.

## Docker / Container installations

The Home Assistant container must be able to access the physical ANT USB adapter. USB discovery and OpenANT access are separate concerns: the adapter must be visible to Home Assistant and must also be openable by libusb/OpenANT.

A useful container check is:

```bash
ls -l /dev/serial/by-id/
```

If Home Assistant can discover the adapter but capture cannot start, check container USB passthrough, permissions, and whether another process already owns the ANT stick.

Only one process should use the ANT USB adapter at a time.

## Entities and availability

Live metrics use the configurable inactivity timeout (default: **30 seconds**). Device-based/slow diagnostics such as battery information remain available while the physical ANT device continues to be received, with a separate default device timeout of **60 seconds**.

The integration also creates an **ANT+ USB Adapter** hub device containing capture controls and diagnostics.

## Troubleshooting

Enable debug logging temporarily:

```yaml
logger:
  logs:
    custom_components.antplus: debug
    homeassistant.components.usb: debug
    openant: debug
```

Useful information for bug reports includes:

- Home Assistant version and installation type.
- ANT adapter VID/PID (`lsusb`).
- ANT sensor brand/model.
- Relevant `custom_components.antplus` and `openant` logs.
- Whether the device is visible under `/dev/serial/by-id/` for container installations.

Please do not post secrets, Home Assistant access tokens, or unrelated private logs.

## Development

Run the repository tests with:

```bash
python -m pip install -r requirements_test.txt
pytest
```

GitHub Actions validate HACS compatibility, Hassfest checks, Python syntax and unit tests.

## Contributing

Issues and pull requests are welcome. For support for a new ANT+ profile or adapter, include real device information and sanitized captures/logs where possible. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Trademark notice

ANT and ANT+ are trademarks of Garmin Canada Inc. This project is an independent community integration and is not affiliated with or endorsed by Garmin, Dynastream, the ANT+ Alliance, or Home Assistant/Open Home Foundation.
