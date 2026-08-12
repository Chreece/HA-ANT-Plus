"""Continuous ANT+ scan-mode receiver."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import time
from typing import Any

from openant.devices import ANTPLUS_NETWORK_KEY
from openant.easy.channel import Channel
from openant.easy.node import Node

from .const import (
    ANTPLUS_NETWORK_NUMBER,
    ANTPLUS_RF_FREQUENCY,
    DEVICE_TYPE_FITNESS_EQUIPMENT,
    DEVICE_TYPE_NAMES,
    MANUFACTURERS,
)
from .decoder import decode_packet
from .capabilities import capability_signature, record_fe_command_status, record_observed_page
from .diagnostics import AntPlusDiagnostics
from .models import AntDevice

_LOGGER = logging.getLogger(__name__)

SUPPORTED_LOCAL_USB_IDS = {("0FCF", "1008"), ("0FCF", "1009")}

# Wildcard ANT scan mode can occasionally yield malformed/transient extended
# packets. Do not create a persistent HA device/profile from a single packet.
DISCOVERY_CONFIRM_PACKETS = 5
DISCOVERY_CONFIRM_WINDOW_SECONDS = 10.0
DISCOVERY_CANDIDATE_TTL_SECONDS = 30.0
MAX_DISCOVERY_CANDIDATES = 256
MAX_CONFIRMED_DEVICES = 256
MAX_PROFILES_PER_DEVICE = 16
MAX_METRICS_PER_DEVICE = 96

DeviceCallback = Callable[[AntDevice], None]
MetricCallback = Callable[[AntDevice, str], None]
StateCallback = Callable[[], None]
PacketCallback = Callable[[AntDevice, int, int, bytes, str], None]


class AntPlusReceiver:
    """Own the ANT USB stick and receive all broadcasts on one scan channel."""

    def __init__(self) -> None:
        self.devices: dict[int, AntDevice] = {}
        self._node: Node | None = None
        self._channel: Channel | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._control_lock = threading.RLock()
        self._started_event = threading.Event()
        self._device_callbacks: list[DeviceCallback] = []
        self._metric_callbacks: list[MetricCallback] = []
        self._state_callbacks: list[StateCallback] = []
        self._packet_callbacks: list[PacketCallback] = []
        self.diagnostics = AntPlusDiagnostics()

        # Unconfirmed RF discoveries. A tuple is promoted only after repeated
        # observations, preventing one malformed wildcard-scan packet from
        # permanently creating a Home Assistant device.
        self._discovery_candidates: dict[
            tuple[int, int, int],
            dict[str, Any],
        ] = {}

        self.error: str | None = None
        self._state = "stopped"

        # Global HA ANT+ capture state.
        #
        # True:
        #   - local ANT USB reception is enabled
        #   - remote ANT+ packets are accepted
        #
        # False:
        #   - local ANT USB reception is stopped
        #   - remote ANT+ packets are discarded
        self._capture_enabled = True

    @property
    def running(self) -> bool:
        """Return whether the local ANT USB receiver is running."""
        return self._state == "running"

    @property
    def capture_enabled(self) -> bool:
        """Return the global HA ANT+ capture state."""
        return self._capture_enabled

    @property
    def state(self) -> str:
        return self._state

    def add_device_callback(self, callback: DeviceCallback) -> Callable[[], None]:
        self._device_callbacks.append(callback)
        return lambda: self._remove_callback(self._device_callbacks, callback)

    def add_metric_callback(self, callback: MetricCallback) -> Callable[[], None]:
        self._metric_callbacks.append(callback)
        return lambda: self._remove_callback(self._metric_callbacks, callback)

    def add_state_callback(self, callback: StateCallback) -> Callable[[], None]:
        self._state_callbacks.append(callback)
        return lambda: self._remove_callback(self._state_callbacks, callback)

    def add_packet_callback(self, callback: PacketCallback) -> Callable[[], None]:
        """Register for confirmed raw ANT+ packets after identity validation."""
        self._packet_callbacks.append(callback)
        return lambda: self._remove_callback(self._packet_callbacks, callback)

    @staticmethod
    def _remove_callback(callbacks: list, callback: Callable) -> None:
        try:
            callbacks.remove(callback)
        except ValueError:
            pass

    def _set_state(self, state: str, error: str | None = None) -> None:
        self._state = state
        if error is not None:
            self.error = error
        elif state in ("starting", "running", "remote"):
            self.error = None

        if state in ("running", "remote", "error", "stopped"):
            self._started_event.set()

        for callback in tuple(self._state_callbacks):
            try:
                callback()
            except Exception:
                _LOGGER.debug("ANT+ state callback failed", exc_info=True)

    def _local_usb_present(self) -> bool:
        """Return whether a supported ANT USB adapter is attached locally."""
        root = Path("/sys/bus/usb/devices")
        if not root.exists():
            return False
        for device_path in root.glob("*"):
            try:
                vid = (device_path / "idVendor").read_text().strip().upper()
                pid = (device_path / "idProduct").read_text().strip().upper()
            except (OSError, UnicodeError):
                continue
            if (vid, pid) in SUPPORTED_LOCAL_USB_IDS:
                return True
        return False

    def enable_capture(self) -> None:
        """Enable capture from all ANT+ sources."""
        with self._control_lock:
            changed = not self._capture_enabled
            self._capture_enabled = True

        if changed:
            for callback in tuple(self._state_callbacks):
                try:
                    callback()
                except Exception:
                    _LOGGER.debug(
                        "ANT+ state callback failed",
                        exc_info=True,
                    )

        # Start local OpenANT only if local ANT USB hardware exists.
        if self._local_usb_present():
            self.start(wait=False)
        else:
            self._set_state("remote")

    def disable_capture(self) -> None:
        """Disable capture from all ANT+ sources."""
        with self._control_lock:
            changed = self._capture_enabled
            self._capture_enabled = False

        # Stop the local USB receiver.
        self.stop()

        if changed:
            for callback in tuple(self._state_callbacks):
                try:
                    callback()
                except Exception:
                    _LOGGER.debug(
                        "ANT+ state callback failed",
                        exc_info=True,
                    )

    def start(self, wait: bool = True) -> None:
        """Start the optional local ANT USB receiver."""
        # Missing local USB is normal in a remote-gateway setup.
        if not self._local_usb_present():
            self._set_state("remote")
            return
        with self._control_lock:
            if not self._capture_enabled:
                return

            if self._state in ("starting", "running"):
                return

            thread = self._thread
            if thread and thread.is_alive():
                _LOGGER.warning("ANT+ receiver thread is still alive; refusing duplicate start")
                return

            self._started_event.clear()
            self._set_state("starting")
            self._thread = threading.Thread(
                target=self._run,
                name="antplus-receiver",
                daemon=True,
            )
            self._thread.start()

        if wait:
            # Give interactive callers a deterministic result.
            self._started_event.wait(timeout=5)

    def stop(self) -> None:
        """Stop capture and wait for the receiver thread to terminate."""
        with self._control_lock:
            if self._state == "stopped":
                return

            self._set_state("stopping")
            node = self._node
            if node is not None:
                try:
                    node.stop()
                except Exception:
                    _LOGGER.debug("Error stopping ANT+ node", exc_info=True)

            thread = self._thread

        if (
            thread
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=10)

        with self._control_lock:
            if thread and thread.is_alive():
                self._set_state(
                    "error",
                    "ANT+ receiver did not stop within 10 seconds",
                )
                return

            self._thread = None
            self._node = None
            self._channel = None
            self._set_state("stopped")



    def snapshot(self) -> dict[int, AntDevice]:
        with self._lock:
            return dict(self.devices)

    def _run(self) -> None:
        try:
            node = Node()
            self._node = node
            node.set_network_key(ANTPLUS_NETWORK_NUMBER, ANTPLUS_NETWORK_KEY)

            channel = node.new_channel(
                Channel.Type.BIDIRECTIONAL_RECEIVE,
                ANTPLUS_NETWORK_NUMBER,
                0x01,
            )
            self._channel = channel
            channel.on_broadcast_data = self._on_data
            channel.on_burst_data = self._on_data
            channel.on_acknowledge = self._on_data
            channel.set_id(0, 0, 0)
            channel.enable_extended_messages(1)
            channel.set_rf_freq(ANTPLUS_RF_FREQUENCY)

            _LOGGER.info("Opening ANT+ continuous RX scan mode")
            channel.open_rx_scan_mode()

            self._set_state("running")
            node.start()

        except Exception as err:
            _LOGGER.exception("ANT+ receiver stopped with an error")
            self._set_state("error", str(err))

        finally:
            node = self._node
            if node is not None:
                try:
                    node.stop()
                except Exception:
                    pass

            self._node = None
            self._channel = None

            # If stop() initiated shutdown, let stop() publish "stopped".
            if self._state not in ("stopping", "error"):
                self._set_state("stopped")

    def _on_data(self, data: Any) -> None:
        """Receive one packet from the local ANT USB adapter."""
        if len(data) < 13:
            return

        payload = bytes(data[:8])
        device_id = int(data[9]) | (int(data[10]) << 8)
        device_type = int(data[11])
        transmission_type = int(data[12])

        self.process_packet(
            device_id=device_id,
            device_type=device_type,
            transmission_type=transmission_type,
            payload=payload,
            source="local",
        )

    def _expire_discovery_candidates(self, now_ts: float) -> None:
        expired = [
            key
            for key, candidate in self._discovery_candidates.items()
            if now_ts - float(candidate["last_seen"])
            > DISCOVERY_CANDIDATE_TTL_SECONDS
        ]
        for key in expired:
            self._discovery_candidates.pop(key, None)

    def _candidate_confirmed(
        self,
        device_id: int,
        device_type: int,
        transmission_type: int,
        payload: bytes,
        source: str,
    ) -> bool:
        now_ts = datetime.now(timezone.utc).timestamp()
        self._expire_discovery_candidates(now_ts)

        key = (device_id, device_type, transmission_type)
        candidate = self._discovery_candidates.get(key)

        if candidate is None:
            if len(self._discovery_candidates) >= MAX_DISCOVERY_CANDIDATES:
                oldest_key = min(
                    self._discovery_candidates,
                    key=lambda item: float(
                        self._discovery_candidates[item]["last_seen"]
                    ),
                )
                self._discovery_candidates.pop(oldest_key, None)

            self._discovery_candidates[key] = {
                "count": 1,
                "first_seen": now_ts,
                "last_seen": now_ts,
                "last_payload": payload,
                "sources": {source},
            }
            _LOGGER.debug(
                "ANT+ discovery candidate %s type %s tx %s: 1/%s",
                device_id,
                device_type,
                transmission_type,
                DISCOVERY_CONFIRM_PACKETS,
            )
            return False

        first_seen = float(candidate["first_seen"])
        if now_ts - first_seen > DISCOVERY_CONFIRM_WINDOW_SECONDS:
            candidate.clear()
            candidate.update(
                {
                    "count": 1,
                    "first_seen": now_ts,
                    "last_seen": now_ts,
                    "last_payload": payload,
                    "sources": {source},
                }
            )
            return False

        candidate["count"] = int(candidate["count"]) + 1
        candidate["last_seen"] = now_ts
        candidate["last_payload"] = payload
        candidate.setdefault("sources", set()).add(source)

        count = int(candidate["count"])
        if count < DISCOVERY_CONFIRM_PACKETS:
            _LOGGER.debug(
                "ANT+ discovery candidate %s type %s tx %s: %s/%s",
                device_id,
                device_type,
                transmission_type,
                count,
                DISCOVERY_CONFIRM_PACKETS,
            )
            return False

        self._discovery_candidates.pop(key, None)
        _LOGGER.info(
            "Confirmed ANT+ RF identity %s type %s tx %s after %s packets",
            device_id,
            device_type,
            transmission_type,
            count,
        )
        return True

    def process_packet(
        self,
        device_id: int,
        device_type: int,
        transmission_type: int,
        payload: bytes,
        *,
        source: str = "unknown",
    ) -> None:
        """Process one ANT+ packet from any transport.

        ANT device ID is the canonical identity. If the same ANT ID is seen
        through local USB and/or multiple remote gateways, all packets update
        the same AntDevice instance.
        """
        self.diagnostics.inc("receiver_packets_seen")
        self.diagnostics.inc_profile("receiver_packets_seen", device_type)
        # One global Capture switch controls every ANT+ source.
        if not self._capture_enabled:
            return

        if not 0 <= device_id <= 0xFFFF:
            raise ValueError(f"Invalid ANT device ID: {device_id}")

        if not 0 <= device_type <= 0xFF:
            raise ValueError(f"Invalid ANT device type: {device_type}")

        if not 0 <= transmission_type <= 0xFF:
            raise ValueError(
                f"Invalid ANT transmission type: {transmission_type}"
            )

        if len(payload) != 8:
            raise ValueError(
                f"ANT payload must contain exactly 8 bytes, got {len(payload)}"
            )

        new_device = False
        new_profile = False
        metadata_changed = False

        with self._lock:
            # ANT device ID remains the canonical HA identity. A brand-new
            # device ID or a new profile on an existing device must first
            # survive RF candidate validation.
            device = self.devices.get(device_id)
            needs_confirmation = (
                device is None
                or device_type not in device.profiles
            )

            if needs_confirmation and not self._candidate_confirmed(
                device_id,
                device_type,
                transmission_type,
                payload,
                source,
            ):
                return

            if device is None:
                if len(self.devices) >= MAX_CONFIRMED_DEVICES:
                    _LOGGER.warning(
                        "ANT+ confirmed-device safety limit reached (%s); "
                        "ignoring new device %s",
                        MAX_CONFIRMED_DEVICES,
                        device_id,
                    )
                    return
                device = AntDevice(device_id=device_id)
                device.decoder_state["_diagnostics"] = self.diagnostics
                self.devices[device_id] = device
                new_device = True

            if device_type not in device.profiles:
                if len(device.profiles) >= MAX_PROFILES_PER_DEVICE:
                    _LOGGER.warning(
                        "ANT+ profile safety limit reached for device %s (%s)",
                        device_id,
                        MAX_PROFILES_PER_DEVICE,
                    )
                    return
                device.profiles.add(device_type)
                new_profile = True

            device.transmission_types.add(transmission_type)
            profile_tx = device.decoder_state.setdefault("profile_transmission_types", {})
            profile_tx.setdefault(device_type, set()).add(transmission_type)
            device.last_seen = datetime.now(timezone.utc)

            # Keep source information diagnostic-only. It does not participate
            # in device identity.
            sources = device.decoder_state.setdefault("sources", set())
            sources.add(source)

            before_metadata = (
                device.manufacturer_id,
                device.manufacturer_name,
                device.model_no,
                device.hardware_rev,
                device.serial_no,
                device.software_ver,
            )

            self._decode_metadata(device, device_type, payload)

            after_metadata = (
                device.manufacturer_id,
                device.manufacturer_name,
                device.model_no,
                device.hardware_rev,
                device.serial_no,
                device.software_ver,
            )

            metadata_changed = before_metadata != after_metadata

            # Central capability model tracks positive page evidence before
            # entities/events are exposed. Capability changes are surfaced to
            # the same device callbacks used for profile discovery.
            before_capabilities = capability_signature(device)
            record_observed_page(device, device_type, payload)

            changed_metrics: list[str] = []

            decode_started = time.perf_counter()
            decoded_metrics = decode_packet(device, device_type, payload)
            decode_elapsed = time.perf_counter() - decode_started
            self.diagnostics.inc("decode_calls")
            self.diagnostics.inc_profile("decode_calls", device_type)
            self.diagnostics.inc("metrics_produced", len(decoded_metrics))
            self.diagnostics.add_time("decode_total", decode_elapsed)
            self.diagnostics.set_gauge("last_decode_device_type", device_type)

            # FE-C command status is authoritative capability feedback. A PASS
            # can confirm an optional control; NOT_SUPPORTED/REJECTED revokes it.
            if device_type == DEVICE_TYPE_FITNESS_EQUIPMENT and (payload[0] & 0x7F) == 0x47:
                record_fe_command_status(device, payload[1], payload[3])

            capability_changed = capability_signature(device) != before_capabilities

            for metric in decoded_metrics:
                old = device.metrics.get(metric.key)

                if old is None and len(device.metrics) >= MAX_METRICS_PER_DEVICE:
                    _LOGGER.warning(
                        "ANT+ metric safety limit reached for device %s (%s)",
                        device_id,
                        MAX_METRICS_PER_DEVICE,
                    )
                    continue

                device.metrics[metric.key] = metric

                if old is None or (
                    old.value != metric.value
                    or old.unit != metric.unit
                    or old.device_class != metric.device_class
                    or old.state_class != metric.state_class
                    or old.icon != metric.icon
                    or old.entity_category != metric.entity_category
                    or old.enabled_default != metric.enabled_default
                    or old.availability_mode != metric.availability_mode
                ):
                    changed_metrics.append(metric.key)

        for callback in tuple(self._packet_callbacks):
            try:
                callback(device, device_type, transmission_type, payload, source)
            except Exception:
                _LOGGER.debug("ANT+ packet callback failed", exc_info=True)

        if new_device:
            _LOGGER.info(
                "Discovered ANT+ device %s via %s",
                device_id,
                source,
            )

        if new_profile:
            _LOGGER.info(
                "ANT+ device %s exposed profile %s (%s) via %s",
                device_id,
                device_type,
                DEVICE_TYPE_NAMES.get(device_type, "Unknown"),
                source,
            )

        if new_device or new_profile or metadata_changed or capability_changed:
            for callback in tuple(self._device_callbacks):
                try:
                    callback(device)
                except Exception:
                    _LOGGER.debug(
                        "ANT+ device callback failed",
                        exc_info=True,
                    )

        self.diagnostics.inc("metrics_changed", len(changed_metrics))
        for key in changed_metrics:
            for callback in tuple(self._metric_callbacks):
                try:
                    callback(device, key)
                except Exception:
                    _LOGGER.debug(
                        "ANT+ metric callback failed",
                        exc_info=True,
                    )

    def _decode_metadata(
        self, device: AntDevice, device_type: int, data: bytes
    ) -> None:
        """Decode identification without mistaking proprietary pages for common pages."""
        page = data[0] & 0x7F

        # Only standardized ANT+ device types may use Common Pages 80/81.
        # Proprietary/unknown device types can legitimately reuse 0x50/0x51
        # for unrelated payloads, as Stryd device type 30 does.
        if device_type in DEVICE_TYPE_NAMES:
            if page == 80:
                hardware_rev = data[3]
                manufacturer_id = data[4] | (data[5] << 8)
                model_no = data[6] | (data[7] << 8)

                if hardware_rev != 0xFF:
                    device.hardware_rev = hardware_rev

                if manufacturer_id not in (0xFFFF,):
                    device.manufacturer_id = manufacturer_id
                    device.manufacturer_name = MANUFACTURERS.get(
                        manufacturer_id,
                        f"ANT manufacturer {manufacturer_id}",
                    )

                if model_no != 0xFFFF:
                    device.model_no = model_no

            elif page == 81:
                sw_rev = data[2]
                sw_main = data[3]
                serial_no = int.from_bytes(data[4:8], byteorder="little")

                # Software revision is manufacturer-defined. 0xFF/0xFF means
                # unavailable; otherwise keep the actual transmitted value.
                if not (sw_rev == 0xFF and sw_main == 0xFF):
                    device.software_ver = (
                        str(sw_main / 10)
                        if sw_rev == 0xFF
                        else str((sw_main * 100 + sw_rev) / 1000)
                    )

                if serial_no != 0xFFFFFFFF:
                    device.serial_no = serial_no

        # HRM profile has identification fields on profile pages 2 and 3.
        if device_type == 120:
            if page == 2:
                manufacturer_id = data[1]
                serial_fragment = data[2] | (data[3] << 8)

                if manufacturer_id != 0xFF:
                    device.manufacturer_id = manufacturer_id
                    device.manufacturer_name = MANUFACTURERS.get(
                        manufacturer_id,
                        f"ANT manufacturer {manufacturer_id}",
                    )

                if serial_fragment != 0xFFFF:
                    device.serial_no = serial_fragment

            elif page == 3:
                hardware_rev = data[1]
                software_rev = data[2]
                model_no = data[3]

                if hardware_rev != 0xFF:
                    device.hardware_rev = hardware_rev

                if software_rev != 0xFF:
                    device.software_ver = str(software_rev)

                if model_no != 0xFF:
                    device.model_no = model_no
