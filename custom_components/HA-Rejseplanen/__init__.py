from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import RejseplanenCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Kaldes af HA med den gemte entry - byg coordinator og start platforme."""
    coordinator = RejseplanenCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # Gem coordinatoren PÅ entry'en, så sensor.py kan hente den
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Kaldes når brugeren fjerner integrationen - ryd pænt op."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Genindlæs entry'en når options ændres."""
    await hass.config_entries.async_reload(entry.entry_id)