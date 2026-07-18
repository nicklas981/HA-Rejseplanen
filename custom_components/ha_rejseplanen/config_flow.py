"""HA-Rejseplanen - config flow (kun API-nøgle)."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RejseplanenAuthError, RejseplanenClient, RejseplanenError
from .const import CONF_ACCESS_ID, DOMAIN


class RejseplanenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Stateless: brugeren indtaster kun sin accessId."""

    VERSION = 2

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            access_id = user_input[CONF_ACCESS_ID].strip()
            client = RejseplanenClient(async_get_clientsession(self.hass), access_id)
            try:
                await client.lookup_stop("Odense")  # billigt valideringskald
            except RejseplanenAuthError:
                errors["base"] = "invalid_auth"
            except RejseplanenError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()  # kun én instans
                return self.async_create_entry(
                    title="HA-Rejseplanen",
                    data={CONF_ACCESS_ID: access_id},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ACCESS_ID): str}),
            errors=errors,
        )