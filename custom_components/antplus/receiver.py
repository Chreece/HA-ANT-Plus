"""Continuous ANT+ scan-mode receiver."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import threading
from typing import Any

from openant.devices import ANTPLUS_NETWORK_KEY
from openant.easy.channel import Channel
from openant.easy.node import Node

from .const import (
    ANTPLUS_NETWORK_NUMBER,
    ANTPLUS_RF_FREQUENCY,
    DEVICE_TYPE_NAMES,
    MANUFACTURERS,
)
from .decoder import decode_packet
from .models import AntDevice

_LOGGER = logging.getLogger(__name__)

DeviceCallback = Callable[[AntDevice], None]
MetricCallback = Callable[[AntDevice, str], None]
StateCallback = Callable[[], None]


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
        elif state in ("starting", "running"):
            self.error = None

        if state in ("running", "error", "stopped"):
            self._started_event.set()

        for callback in tuple(self._state_callbacks):
            try:
                callback()
            except Exception:
                _LOGGER.debug("ANT+ state callback failed", exc_info=True)

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

        # Also start the optional local adapter.
        self.start(wait=False)

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
            # Deliberately keyed ONLY by ANT device ID.
            device = self.devices.get(device_id)
            if device is None:
                device = AntDevice(device_id=device_id)
                self.devices[device_id] = device
                new_device = True

            if device_type not in device.profiles:
                device.profiles.add(device_type)
                new_profile = True

            device.transmission_types.add(transmission_type)
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

            changed_metrics: list[str] = []

            for metric in decode_packet(device, device_type, payload):
                old = device.metrics.get(metric.key)
                device.metrics[metric.key] = metric

                if old != metric:
                    changed_metrics.append(metric.key)

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

        if new_device or new_profile or metadata_changed:
            for callback in tuple(self._device_callbacks):
                try:
                    callback(device)
                except Exception:
                    _LOGGER.debug(
                        "ANT+ device callback failed",
                        exc_info=True,
                    )

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
