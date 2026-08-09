"""Sensor platform for ANT+."""

from __future__ import annotations
from homeassistant.helpers.entity import EntityCategory

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .adapter_sensor import async_setup_adapter_sensors
from .const import (
    DEFAULT_INACTIVITY_TIMEOUT,
    DOMAIN,
    device_display_name,
    device_model_name,
)
from .entity import AntPlusEntity
from .models import AntDevice
from .receiver import AntPlusReceiver


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    receiver: AntPlusReceiver = hass.data[DOMAIN][entry.entry_id]
    adapter_manager = receiver.adapter_manager
    await async_setup_adapter_sensors(
        hass,
        entry,
        adapter_manager,
        async_add_entities,
    )
    timeout = int(entry.options.get("inactivity_timeout", DEFAULT_INACTIVITY_TIMEOUT))
    known_entities: set[tuple[int, str]] = set()


    @callback
    def add_metric_entity(device_id: int, metric_key: str) -> None:
        identity = (device_id, metric_key)
        if identity in known_entities:
            return
        device = receiver.devices.get(device_id)
        if device is None or metric_key not in device.metrics:
            return
        known_entities.add(identity)
        async_add_entities(
            [AntPlusSensor(receiver, device, metric_key, timeout)],
            update_before_add=False,
        )

    def metric_changed(device: AntDevice, metric_key: str) -> None:
        def handle() -> None:
            if (device.device_id, metric_key) not in known_entities:
                add_metric_entity(device.device_id, metric_key)
        hass.loop.call_soon_threadsafe(handle)

    entry.async_on_unload(receiver.add_metric_callback(metric_changed))

    device_registry = dr.async_get(hass)

    def device_changed(device: AntDevice) -> None:
        def handle() -> None:
            ha_device = device_registry.async_get_device(
                identifiers={(DOMAIN, str(device.device_id))}
            )
            if ha_device is None:
                return

            changes = {
                "name": device_display_name(device),
            }

            # Do not clear metadata merely because its slow ANT
            # identification page has not been repeated in this session.
            if (
                device.manufacturer_name
                and not device.manufacturer_name.startswith("ANT manufacturer ")
            ):
                changes["manufacturer"] = device.manufacturer_name

            if device.profiles:
                changes["model"] = device_model_name(device)

            if device.software_ver is not None:
                changes["sw_version"] = device.software_ver

            if device.hardware_rev not in (None, 0xFF):
                changes["hw_version"] = str(device.hardware_rev)

            if device.serial_no not in (None, 0xFFFF, 0xFFFFFFFF):
                changes["serial_number"] = str(device.serial_no)

            device_registry.async_update_device(
                ha_device.id,
                **changes,
            )

        hass.loop.call_soon_threadsafe(handle)

    entry.async_on_unload(receiver.add_device_callback(device_changed))

    for device in receiver.snapshot().values():
        for metric_key in device.metrics:
            add_metric_entity(device.device_id, metric_key)


class AntPlusSensor(AntPlusEntity, SensorEntity):
    """A decoded ANT+ metric."""

    def __init__(
        self,
        receiver: AntPlusReceiver,
        device: AntDevice,
        metric_key: str,
        inactivity_timeout: int,
    ) -> None:
        super().__init__(receiver, device, metric_key, inactivity_timeout)
        metric = device.metrics[metric_key]
        self._attr_unique_id = f"{device.device_id}_{metric_key}"
        self._attr_name = metric.name
        self._attr_native_unit_of_measurement = metric.unit
        self._attr_icon = metric.icon
        self._attr_device_class = metric.device_class
        self._attr_state_class = metric.state_class
        if isinstance(metric.entity_category, str):
            self._attr_entity_category = EntityCategory(metric.entity_category)
        else:
            self._attr_entity_category = metric.entity_category
        self._attr_entity_registry_enabled_default = metric.enabled_default

    @property
    def native_value(self) -> Any:
        metric = self.ant_device.metrics.get(self.metric_key)
        return metric.value if metric is not None else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        def metric_changed(device: AntDevice, metric_key: str) -> None:
            if device.device_id == self.ant_device_id and metric_key == self.metric_key:
                self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

        def receiver_changed() -> None:
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

        self.async_on_remove(self.receiver.add_metric_callback(metric_changed))
        self.async_on_remove(self.receiver.add_state_callback(receiver_changed))
        @callback
        def refresh_state(_now) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                refresh_state,
                timedelta(seconds=1),
            )
        )



class AntPlusDecoderCoverageSensor(SensorEntity):
    """Profiles with semantic parsers available in this integration."""

    _attr_name = "Decoder Coverage"
    _attr_unique_id = "antplus_decoder_coverage"
    _attr_icon = "mdi:code-json"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, receiver: AntPlusReceiver) -> None:
        self.receiver = receiver

    @property
    def native_value(self):
        from .openant_bridge import supported_profile_types
        # +1 for our custom Stride Speed/Distance parser.
        return len(supported_profile_types() | {124})

    @property
    def extra_state_attributes(self):
        from .const import DEVICE_TYPE_NAMES
        from .openant_bridge import supported_profile_types
        types = sorted(supported_profile_types() | {124})
        return {
            "decoded_profiles": [
                {
                    "device_type": profile,
                    "name": DEVICE_TYPE_NAMES.get(profile, f"Profile {profile}"),
                }
                for profile in types
            ],
            "raw_fallback_for_all_profiles": True,
        }
