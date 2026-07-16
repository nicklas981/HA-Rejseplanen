from datetime import datetime, timedelta
import logging
from zoneinfo import ZoneInfo
from .const import CONF_ACCESS_ID, CONF_STOP_ID, CONF_LINES, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
import aiohttp
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

_LOGGER = logging.getLogger(__name__)

DK_TZ = ZoneInfo("Europe/Copenhagen")
BASE = "https://www.rejseplanen.dk/api"

class RejseplanenCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            name="ha_rejseplanen",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.entry = entry

    async def _async_update_data(self):
        session = async_get_clientsession(self.hass)
        params = {
            "accessId": self.entry.data[CONF_ACCESS_ID],   # ← fra config flow!
            "id": self.entry.data[CONF_STOP_ID],           # ← fra config flow!
            "format": "json",
        }

        try:
            async with session.get(f"{BASE}/departureBoard", params=params) as resp:
                data = await resp.json()
        except aiohttp.ClientError as err:
            # UpdateFailed = HA markerer entities som "unavailable" og prøver igen
            raise UpdateFailed(f"API-fejl: {err}") from err

        afgange = []
        for dep in data.get("Departure", []):
            tid_str = dep.get("rtTime", dep.get("time"))
            dato_str = dep.get("rtDate", dep.get("date"))
            afgang_dt = datetime.strptime(
                f"{dato_str} {tid_str}", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=DK_TZ)
            linjefilter = [
            x.strip()
            for x in self.entry.options.get(CONF_LINES, "").split(",")
            if x.strip()
        ]
            if linjefilter and dep.get("ProductAtStop", {}).get("displayNumber") not in linjefilter:
                continue
            afgange.append(
                {
                    "linje": dep.get("ProductAtStop", {}).get("displayNumber"),
                    "retning": dep.get("direction"),
                    "tidspunkt": afgang_dt,
                }
            )
        return afgange  # Bliver til self.data på coordinatoren