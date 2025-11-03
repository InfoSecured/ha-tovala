# custom_components/tovala/config_flow.py
from __future__ import annotations
from typing import Any, Dict
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_OVEN_ID
from .api import TovalaClient, TovalaAuthError

class TovalaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    _creds: Dict[str, Any] = {}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = TovalaClient(session, email=user_input[CONF_EMAIL], password=user_input[CONF_PASSWORD])
            try:
                await client.login()
                ovens = await client.list_ovens()
                if not ovens:
                    errors["base"] = "no_ovens_found"
                else:
                    self._creds = user_input
                    # Build a map of id->label for selection
                    self._oven_choices = {o["id"]: f'{o.get("name") or "Oven"} ({o["id"]})' for o in ovens}
                    return await self.async_step_select_oven()
            except TovalaAuthError:
                errors["base"] = "auth"
            except Exception:
                errors["base"] = "unknown"

        schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PASSWORD): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_select_oven(self, user_input=None):
        if user_input is not None:
            data = {
                CONF_EMAIL: self._creds[CONF_EMAIL],
                CONF_PASSWORD: self._creds[CONF_PASSWORD],
                CONF_OVEN_ID: user_input[CONF_OVEN_ID],
            }
            return self.async_create_entry(title="Tovala", data=data)

        schema = vol.Schema({
            vol.Required(CONF_OVEN_ID): vol.In(self._oven_choices),
        })
        return self.async_show_form(step_id="select_oven", data_schema=schema)