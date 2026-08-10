## 2026.8.4

- Make remote active control transactional: HA sends a correlated command ID and waits for the exact gateway/adapter to confirm success or report an error.
- Remote gateways advertise `control_protocol=1`; HA only exposes remote controls when the connected gateway supports the confirmed-control protocol.
- Add an internal `antplus_adapter_control_result` acknowledgement path and timeout/error propagation back to Home Assistant entities/services.
- Add advanced HA actions `antplus.send_raw_control` and `antplus.request_data_page`; both use the same local-or-remote routed transmit path.
- Add ANT+ Common Page 70 request-data-page packet support.
- Expose TPMS sensor-position control (Unknown/Front/Rear).
- Expose LEV wheel-circumference and command-manufacturer-ID writable fields in addition to the existing assist/regen/gears/lights controls.
- Expose Common Page 80/81 identification values as disabled-by-default diagnostic entities as well as Device Registry metadata.
- Expose FE-C command-status page 71 as diagnostics and `antplus_event` command-status events.
- Stop legacy cleanup from deleting useful manufacturer/model/serial/software/hardware diagnostic entities.

## 2026.8.3

- Expose every useful field decoded by the bundled OpenANT 1.3.4 parsers; protocol bookkeeping and identification values are retained as diagnostic entities instead of being silently dropped.
- Correct OpenANT status handling so profile status fields are not mistaken for battery status.
- Add ANT+ tire-pressure-monitor writable barometric, low-alarm and high-alarm pressure controls using OpenANT's documented page 0x10 implementation.
- Preserve raw profile data/last-page diagnostics for profiles without a semantic decoder.

## 2026.8.2

- Added semantic `antplus_event` Home Assistant bus events for Controls Device commands, shifting changes and dropper valve events.
- Added active FE-C Target Power and Basic Resistance controls.
- Added active LEV assist, regenerative braking, gear, lights, high-beam and turn-signal controls.
- Added Dropper Seatpost valve and stored unlock-delay controls.
- Added active-control routing through the exact local or remote ANT USB adapter that observed the device.
- Gateway now receives and transmits routed ANT+ acknowledged control packets.

# Changelog

## 2026.8.1

- Start the `year.month.release_increment` release numbering scheme.
- Add two independent parser backends: native HA ANT+ and OpenANT.
- Native decoding takes precedence; OpenANT fills missing semantic metrics.
- Catalogue publicly documented capabilities for all recognized ANT+ profile families.
- Recognize Extended Display (device type 38) in the profile catalogue.
- Expose decoder-backend and documented-capability coverage in diagnostics.
- Preserve bounded raw fallback for every recognized profile.
- Keep active ANT-FS/request/control functionality explicitly separate from passive receive data.
- Retain the load-safety protections for discovery, entity creation and remote gateway traffic.
