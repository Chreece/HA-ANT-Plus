"""ANT+ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .receiver import AntPlusReceiver


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    receiver = AntPlusReceiver()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = receiver

    await async_cleanup_legacy_entities(hass)
    await hass.async_add_executor_job(receiver.start)
    if not receiver.running:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise ConfigEntryNotReady(receiver.error or "ANT+ USB adapter is not available")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False
    receiver: AntPlusReceiver = hass.data[DOMAIN].pop(entry.entry_id)
    await hass.async_add_executor_job(receiver.stop)
    return True



async def async_cleanup_legacy_entities(hass: HomeAssistant) -> None:
    """Remove implementation-detail entities created by early development builds."""
    registry = er.async_get(hass)

    # These suffixes were exposed by the generic OpenANT dataclass bridge in
    # 0.3.0 but are now either device metadata, raw diagnostics or merged
    # battery fields.
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
    }

    for entity in list(registry.entities.values()):
        if entity.platform != DOMAIN:
            continue

        unique_id = entity.unique_id or ""
        if any(unique_id.endswith(suffix) for suffix in unwanted_suffixes):
            registry.async_remove(entity.entity_id)
