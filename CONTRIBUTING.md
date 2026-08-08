# Contributing to HA ANT+

Thanks for helping improve HA ANT+.

## Bug reports

Include Home Assistant version, installation type, ANT adapter VID/PID, ANT sensor model, reproduction steps, and sanitized relevant logs.

## New adapter reports

Provide `lsusb` output containing VID/PID and confirm whether OpenANT successfully starts capture. Do not add broad USB matchers that may match unrelated hardware.

## New ANT+ profile support

Prefer standard ANT+ semantics and Home Assistant-native device/state classes. Preserve unknown data as diagnostics rather than guessing field meanings.

## Pull requests

- Keep the domain `antplus`.
- Run `pytest`.
- Ensure HACS and Hassfest workflows pass.
- Avoid blocking Home Assistant's event loop. OpenANT callbacks run outside the HA event loop; schedule HA state changes thread-safely.
