"""HA ANT+ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .receiver import AntPlusReceiver
from .remote import async_register_remote_listener


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up HA ANT+."""
    receiver = AntPlusReceiver()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = receiver

    await async_cleanup_legacy_entities(hass)

    # Remote ANT+ is always active once HA ANT+ is configured.
    entry.async_on_unload(
        async_register_remote_listener(
            hass,
            receiver,
        )
    )

    # Try local USB as well, but never make the integration depend on it.
    #
    # wait=False means the executor call returns immediately after starting
    # the receiver thread. A remote-only installation therefore loads
    # normally even when there is no ANT USB adapter on this HA host.
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
) -> None:
    """Remove implementation-detail entities from early versions."""
    registry = er.async_get(hass)

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

    for entity in list(registry.entities.values()):
        if entity.platform != DOMAIN:
            continue

        unique_id = entity.unique_id or ""

        if any(
            unique_id.endswith(suffix)
            for suffix in unwanted_suffixes
        ):
            registry.async_remove(entity.entity_id)
