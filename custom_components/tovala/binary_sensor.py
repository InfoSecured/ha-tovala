from __future__ import annotations
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .coordinator import TovalaCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities: AddEntitiesCallback):
    coord: TovalaCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    add_entities([TovalaTimerRunningBinarySensor(coord)])

class TovalaTimerRunningBinarySensor(CoordinatorEntity[TovalaCoordinator], BinarySensorEntity):
    _attr_name = "Tovala Timer Running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: TovalaCoordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"tovala_{coordinator.oven_id}_timer_running"

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        remaining = int(self.coordinator.data.get("remaining") or self.coordinator.data.get("time_remaining") or 0)
        return remaining > 0

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success