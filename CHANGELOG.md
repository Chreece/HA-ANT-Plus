## 2026.8.10

- Expand Controls Device support with dedicated Home Assistant buttons for Generic Control menu navigation and timer Start, Stop, Reset, Lap and Length commands, plus `antplus.send_generic_control`.
- Add full FE-C trainer-mode controls for simulation grade, rolling resistance, wind resistance, wind speed and drafting factor in addition to the existing Target Power and Basic Resistance controls.
- Add FE-C user-configuration controls for user weight, bicycle weight, wheel diameter and gear ratio.
- Add FE-C zero-offset/spin-down calibration buttons, calibration progress/result metrics and `antplus_event` calibration events.
- Add an FE-C Request Capabilities button and use received capability information to disable unsupported Basic Resistance, Target Power or Simulation controls.
- Add Bicycle Power manual-calibration control and calibration-response events.
- Route every new semantic command through the existing confirmed adapter-control transport, preserving identical behavior for local ANT USB adapters and remote gateways.
- Keep Generic Control timer Stop distinct from Audio/Video Pause: Pause belongs to the ANT+ Audio/Video control use cases and is not fabricated as a Generic Control command.

## 2026.8.9

- Replace per-sensor receiver-state callbacks with one integration-level callback, eliminating callback fanout as multi-profile devices create many entities.
- Replace one 5-second inactivity timer per ANT sensor with one integration-level timer and only write HA state when availability actually changes.
- Add diagnostics counters/gauges for global sensor refreshes, checks, writes, callback count and inactivity-timer count.
- Treat incoming remote RF packets as authoritative Capture-ON confirmation, preventing slow ANT handshakes from leaving the HA switch falsely reverted to OFF while packets are flowing.
- Include authoritative per-adapter `capture_states` in gateway hello/status messages, report Capture OFF when a gateway scanner stops, and increase the confirmation grace period to 30 seconds.
- Include the capture-state reconciliation capability without changing the existing telemetry/control protocol versions, preserving backward compatibility.

## 2026.8.8

- Add diagnostics-only instrumentation for ANT+ performance investigations.
- Add `antplus.dump_diagnostics` to log packet/decode/OpenANT/metric/entity counters, timings, queue gauges, and all live Python thread stacks without external profilers or Unix signals.
- Add `antplus.reset_diagnostics` so a reproduction can start from zeroed counters.
- No ANT transport, decoding, coalescing, event, control, or gateway behavior is changed in this release.

## 2026.8.7

- Add two-sided ANT+ telemetry coalescing for high-rate remote sensors: the gateway now collapses RF repetitions before WebSocket transport and HA independently coalesces received telemetry before decoding.
- Treat only implemented/page-aware ANT+ profiles as page-keyed streams; raw/spec-required profiles such as Running Dynamics are coalesced per profile so arbitrary payload byte 0 values cannot create hundreds of fake page streams.
- Preserve Controls Device, Shifting, Dropper and FE-C command-status packets outside telemetry coalescing so automation/control events remain lossless under normal operation.
- Add a producer-side `GatewayPacketBuffer` so the Jetson no longer queues every repeated RF packet before the periodic sender can coalesce it.
- Globally coalesce Home Assistant metric state writes into 100 ms windows and replace per-entity receiver callbacks with one integration-level dispatcher, eliminating O(metrics × entities) callback fanout.
- Advertise `telemetry_protocol=2` from updated remote gateways while retaining compatibility with older gateways.


## 2026.8.6

- Move all remote ANT+ packet validation/decoding off Home Assistant's MainThread into a dedicated worker thread.
- Add a bounded 4096-packet remote queue; on saturation the oldest telemetry is discarded so stale backlog can never freeze HA.
- Stop the remote packet worker cleanly when the integration unloads.
- Reduce OpenANT power-meter per-packet logging from INFO to warnings/errors to avoid high-rate log storms.

## 2026.8.5

- Normalize semantic metric keys globally across native and OpenANT decoders so the same ANT field cannot create duplicate Home Assistant entities.
- Collapse OpenANT Heart Rate aliases (`beat_count`, `beat_time`, manufacturer-ID LSB and profile serial fragment) into the native canonical HR entities.
- Stop recreating component-only entities such as page-specific bytes and coarse/fractional voltage; the bounded Raw Data diagnostic preserves the original packet losslessly.
- Namespace generic OpenANT status fields and map Common BatteryData status to the canonical `Battery Status` entity.
- Separate Common Page 82 battery operating time from profile-specific operating time to prevent one entity from changing meaning between ANT pages.
- Expose Common Page 82 Battery ID, Battery Count and Battery Operating Time as disabled-by-default diagnostics.
- Expose Common Page 83 device date/time as a disabled-by-default diagnostic.
- Distinguish OpenANT profile pages named `battery` (such as LEV battery data) from the actual Common BatteryData callback.
- Classify protocol counters, event-time arrays, cumulative bookkeeping and capability fields as disabled-by-default diagnostics while keeping semantic measurements enabled.
- Remove obsolete pre-normalization duplicate entities from the entity registry on integration setup.

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
