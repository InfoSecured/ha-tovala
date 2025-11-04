from __future__ import annotations
from datetime import timedelta
from typing import Any
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, EVENT_TIMER_FINISHED

_LOGGER = logging.getLogger(__name__)

class TovalaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, client, oven_id: str):
        super().__init__(
            hass,
            _LOGGER,  # Changed from hass.helpers.logger.getLogger(__name__)
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.oven_id = oven_id
        self._last_reported_remaining = None

    async def _async_update_data(self) -> dict:
        if not self.oven_id:
            # Return empty data if we don't have an oven yet
            _LOGGER.warning("No oven_id configured yet")
            return {}
        
        try:
            data = await self.client.oven_status(self.oven_id)
            _LOGGER.debug("Oven status: %s", data)
            
            # Expected keys (example): {"state":"cooking|idle", "remaining":123, "mode":"air_fry", ...}
            remaining = data.get("remaining") or data.get("time_remaining") or 0
            
            # Fire event once when remaining crosses to 0
            if (self._last_reported_remaining and self._last_reported_remaining > 0) and int(remaining) == 0:
                _LOGGER.info("Timer finished for oven %s", self.oven_id)
                self.hass.bus.async_fire(EVENT_TIMER_FINISHED, {
                    "oven_id": self.oven_id,
                    "data": data
                })
            
            self._last_reported_remaining = int(remaining)
            return data
            
        except Exception as err:
            _LOGGER.error("Error fetching oven status: %s", err, exc_info=True)
            raise