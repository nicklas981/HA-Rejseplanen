"""HA-Rejseplanen - sensor-platform."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STOP_ID, CONF_STOP_NAME


async def async_setup_entry(hass, entry, async_add_entities):
    """Kaldes via async_forward_entry_setups fra __init__.py."""
    async_add_entities([NextDepartureSensor(entry.runtime_data)])


class NextDepartureSensor(CoordinatorEntity, SensorEntity):
    """Naeste afgang som timestamp - HA viser selv 'om X minutter'."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator):
        super().__init__(coordinator)
        stop_id = coordinator.entry.data[CONF_STOP_ID]
        stop_name = coordinator.entry.data[CONF_STOP_NAME]
        self._attr_unique_id = f"{stop_id}_next_departure"
        self._attr_name = f"{stop_name} Næste afgang"

    @property
    def native_value(self):
        """Tidspunktet for naeste afgang som datetime - IKKE tekst."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data[0]["tidspunkt"]

    @property
    def extra_state_attributes(self):
        """Naeste afgangs detaljer + de kommende 10 afgange."""
        if not self.coordinator.data:
            return {"afgange": []}
        naeste = self.coordinator.data[0]
        return {
            "linje": naeste["linje"],
            "retning": naeste["retning"],
            "afgange": [
                {
                    "linje": d["linje"],
                    "retning": d["retning"],
                    "tidspunkt": d["tidspunkt"].isoformat(),
                }
                for d in self.coordinator.data[:10]
            ],
        }