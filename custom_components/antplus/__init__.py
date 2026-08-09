"""HA ANT+ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .adapter import AntAdapterManager
from .const import DOMAIN, PLATFORMS, SENSORS_PARENT_IDENTIFIER
from .receiver import AntPlusReceiver
from .remote import async_register_remote_listener


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up HA ANT+."""
    receiver = AntPlusReceiver()
    adapter_manager = AntAdapterManager(hass, entry, receiver)
    receiver.adapter_manager = adapter_manager

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = receiver

    device_registry = dr.async_get(hass)
    sensor_parent = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={SENSORS_PARENT_IDENTIFIER},
        name="ANT+ Sensors",
        manufacturer="HA ANT+",
        model="Logical ANT+ Sensor Collection",
    )

    await async_cleanup_legacy_entities(hass, entry)
    await adapter_manager.async_start()
    entry.async_on_unload(adapter_manager.stop)

    entry.async_on_unload(
        async_register_remote_listener(
            hass,
            entry,
            receiver,
            adapter_manager,
        )
    )

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    entry.async_on_unload(
        entry.add_update_listener(_async_options_updated)
    )

    return True


async def _async_options_updated(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )

    if not unloaded:
        return False

    receiver = hass.data[DOMAIN].pop(entry.entry_id)
    receiver.adapter_manager.stop()

    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)

    return True


async def async_cleanup_legacy_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove old hub/global capture entities; physical devices stay."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    unwanted_suffixes = {
        "_page_specific",
        "_manufacturer_id_lsb",
        "_manufacturer_id",
        "_serial_number",
        "_serial_no",
        "_hardware_rev",
        "_hardware_revision",
        "_software_rev",
        "_software_revision",
        "_model_no",
        "_model_number",
        "_voltage_coarse",
        "_voltage_fractional",
        "_operating_time",
        "_capture_toggle",
    }

    obsolete_unique_ids = {
        "antplus_capture",
        "antplus_capture_status",
        "antplus_capture_last_error",
        "antplus_cleanup_stale_devices",
        "antplus_receiver_state",
        "antplus_confirmed_devices",
        "antplus_discovery_candidates",
        "antplus_last_error",
        "antplus_decoder_coverage",
    }

    for entity in list(entity_registry.entities.values()):
        if entity.platform != DOMAIN:
            continue

        unique_id = entity.unique_id or ""
        if (
            unique_id in obsolete_unique_ids
            or any(unique_id.endswith(suffix) for suffix in unwanted_suffixes)
        ):
            entity_registry.async_remove(entity.entity_id)

    hub = device_registry.async_get_device_by_identifier(
        (DOMAIN, "hub"),
        entry.entry_id,
    )
    if hub is not None:
        device_registry.async_remove_device(hub.id)

    sensor_parent = device_registry.async_get_device_by_identifier(
        SENSORS_PARENT_IDENTIFIER,
        entry.entry_id,
    )

    if sensor_parent is not None:
        for device in list(device_registry.devices.values()):
            if entry.entry_id not in device.config_entries:
                continue

            is_ant_sensor = any(
                domain == DOMAIN and str(value).isdigit()
                for domain, value in device.identifiers
            )
            if not is_ant_sensor:
                continue

            device_registry.async_update_device(
                device.id,
                via_device_id=sensor_parent.id,
            )

    integration_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, "integration"),
        entry.entry_id,
    )
    if integration_device is not None:
        device_registry.async_remove_device(integration_device.id)
