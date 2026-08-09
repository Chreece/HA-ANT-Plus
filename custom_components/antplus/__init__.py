"""HA ANT+ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .adapter import AntAdapterManager
from .const import DOMAIN, PLATFORMS
from .receiver import AntPlusReceiver
from .remote import async_register_remote_listener


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up HA ANT+."""
    receiver = AntPlusReceiver()
    adapter_manager = AntAdapterManager(hass, entry)
    receiver.adapter_manager = adapter_manager

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = receiver

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

    # Optional local transport. Missing local USB is a normal remote-only state.
    await hass.async_add_executor_job(receiver.start, False)

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
    """Reload after option changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload HA ANT+."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )

    if not unloaded:
        return False

    receiver: AntPlusReceiver = hass.data[DOMAIN].pop(entry.entry_id)
    await hass.async_add_executor_job(receiver.stop)

    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)

    return True


async def async_cleanup_legacy_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove obsolete entities and the old HA ANT+ hub device."""
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
        "antplus_capture_status",
        "antplus_capture_last_error",
    }

    device_less_unique_ids = {
        "antplus_capture",
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
            continue

        if unique_id in device_less_unique_ids and entity.device_id is not None:
            entity_registry.async_update_entity(
                entity.entity_id,
                device_id=None,
            )

    hub = device_registry.async_get_device_by_identifier(
        (DOMAIN, "hub"),
        entry.entry_id,
    )
    if hub is not None:
        device_registry.async_remove_device(hub.id)
