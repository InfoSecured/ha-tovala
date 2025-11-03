# custom_components/tovala/__init__.py
from __future__ import annotations
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, PLATFORMS
from .api import TovalaClient
from .coordinator import TovalaCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    email = entry.data.get("email")
    password = entry.data.get("password")
    oven_id = entry.data.get("oven_id")
    token = entry.data.get("token")  # optional, in case we add token-based options

    session = async_get_clientsession(hass)
    client = TovalaClient(session, email=email, password=password, token=token)

    # If the oven id isn't set yet, fetch it
    if not oven_id:
        ovens = await client.list_ovens()
        oven_id = ovens[0]["id"] if ovens else None
        if not oven_id:
            raise RuntimeError("No ovens found on your Tovala account")
        hass.config_entries.async_update_entry(entry, data={**entry.data, "oven_id": oven_id})

    coord = TovalaCoordinator(hass, client, oven_id)
    await coord.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {"client": client, "coordinator": coord}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True