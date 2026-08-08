"""Base ANT+ entity."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import (
    DEFAULT_INACTIVITY_TIMEOUT,
    DEVICE_INACTIVITY_TIMEOUT,
    DEVICE_TYPE_NAMES,
    DOMAIN,
    device_display_name,
    device_model_name,
)
from .models import AntDevice
from .receiver import AntPlusReceiver


class AntPlusEntity(Entity):
    """Base entity for one metric on an ANT device."""

    _attr_should_poll = False

    def __init__(
        self,
        receiver: AntPlusReceiver,
        device: AntDevice,
        metric_key: str,
        inactivity_timeout: int = DEFAULT_INACTIVITY_TIMEOUT,
    ) -> None:
        self.receiver = receiver
        self.ant_device_id = device.device_id
        self.metric_key = metric_key
        self.inactivity_timeout = inactivity_timeout

    @property
    def ant_device(self) -> AntDevice:
        return self.receiver.devices[self.ant_device_id]

    @property
    def available(self) -> bool:
        if not self.receiver.running:
            return False

        metric = self.ant_device.metrics.get(self.metric_key)
        if metric is None:
            return False

        # Live metrics must themselves be fresh. Slow ANT+ information such
        # as battery is often transmitted only every few minutes, so it
        # remains available while the physical ANT device is still active.
        if metric.availability_mode == "device":
            timestamp = self.ant_device.last_seen
            timeout = DEVICE_INACTIVITY_TIMEOUT
        else:
            timestamp = metric.updated_at
            timeout = self.inactivity_timeout

        if timestamp is None:
            return False

        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        return age <= timeout

    @property
    def device_info(self) -> DeviceInfo:
        dev = self.ant_device

        info = {
            "identifiers": {(DOMAIN, str(dev.device_id))},
            "name": device_display_name(dev),
        }

        # Only supply positively learned metadata. Omitting unknown fields is
        # important: HA's Device Registry can then preserve metadata learned
        # during an earlier ANT session/restart.
        if dev.manufacturer_name and not dev.manufacturer_name.startswith(
            "ANT manufacturer "
        ):
            info["manufacturer"] = dev.manufacturer_name

        if dev.profiles:
            info["model"] = device_model_name(dev)

        if dev.software_ver is not None:
            info["sw_version"] = dev.software_ver

        if dev.hardware_rev not in (None, 0xFF):
            info["hw_version"] = str(dev.hardware_rev)

        if dev.serial_no not in (None, 0xFFFF, 0xFFFFFFFF):
            info["serial_number"] = str(dev.serial_no)

        return DeviceInfo(**info)

    @property
    def extra_state_attributes(self):
        dev = self.ant_device
        return {
            "ant_device_id": dev.device_id,
            "profiles": [
                {
                    "id": profile,
                    "name": DEVICE_TYPE_NAMES.get(profile, "Unknown"),
                }
                for profile in sorted(dev.profiles)
            ],
            "transmission_types": sorted(dev.transmission_types),
            "manufacturer_id": dev.manufacturer_id,
            "model_number": dev.model_no,
            "last_seen": dev.last_seen.isoformat() if dev.last_seen else None,
        }
