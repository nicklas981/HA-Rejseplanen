"""Config flow for Rejseplanen 2."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_ACCESS_ID, CONF_STOP_ID, CONF_STOP_NAME, DOMAIN, CONF_SCAN_INTERVAL, CONF_LINES, DEFAULT_SCAN_INTERVAL

BASE = "https://www.rejseplanen.dk/api"


class RejseplanenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """To trin: (1) nøgle + søgning, (2) vælg stop."""

    VERSION = 1

    def __init__(self):
        self._access_id = None
        self._stops = []

    async def async_step_user(self, user_input=None):
            """Trin 1: nøgle og søgetekst."""
            errors = {}

            if user_input is not None:
                self._access_id = user_input[CONF_ACCESS_ID]
                session = async_get_clientsession(self.hass)
                params = {
                    "accessId": self._access_id,
                    "input": user_input["search"],
                    "format": "json",
                }
                resp = await session.get(f"{BASE}/location.name", params=params)
                if resp.status in (401, 403):
                    errors["base"] = "invalid_auth"
                else:
                    data = await resp.json()
                    self._stops = [
                        loc["StopLocation"]
                        for loc in data.get("stopLocationOrCoordLocation", [])
                        if "StopLocation" in loc
                    ]
                    if not self._stops:
                        errors["base"] = "no_stops"
                    else:
                        return await self.async_step_stop()

            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ACCESS_ID): str,
                        vol.Required("search"): str,
                    }
                ),
                errors=errors,
            )

    async def async_step_stop(self, user_input=None):
            """Trin 2: vælg stop fra søgeresultaterne."""
            if user_input is not None:
                stop = next(
                    s for s in self._stops if s["extId"] == user_input[CONF_STOP_ID]
                )
                await self.async_set_unique_id(stop["extId"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=stop["name"],
                    data={
                        CONF_ACCESS_ID: self._access_id,
                        CONF_STOP_ID: stop["extId"],
                        CONF_STOP_NAME: stop["name"],
                    },
                )

            return self.async_show_form(
                step_id="stop",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_STOP_ID): vol.In(
                            {s["extId"]: s["name"] for s in self._stops}
                        )
                    }
                ),
            )
    @staticmethod
    def async_get_options_flow(config_entry):
        """Fortæl HA hvilken klasse der håndterer 'Konfigurer'."""
        return RejseplanenOptionsFlow()

class RejseplanenOptionsFlow(config_entries.OptionsFlow):
    """Indstillinger for en eksisterende entry."""

    async def async_step_init(self, user_input=None):
        """Options flow starter altid i step 'init'."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: user_input.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                    CONF_LINES: user_input.get(CONF_LINES, ""),
                }
            )

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                    vol.Optional(
                        CONF_LINES,
                        description={"suggested_value": options.get(CONF_LINES, "")},
                    ): str,
                }
            ),
        )