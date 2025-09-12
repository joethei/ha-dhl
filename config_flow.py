"""Config flow for DHL Tracking integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_API_KEY, CONF_TRACKING_NUMBERS
from .dhl_tracker import DHLTracker

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): cv.string,
        vol.Optional(CONF_TRACKING_NUMBERS, default=""): cv.string,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    tracker = DHLTracker(data[CONF_API_KEY])
    
    # Test the API key with a dummy request (this will fail but validate the key format)
    try:
        # We just test if we can initialize and make a request
        # A 404 or similar error is expected here, but auth errors would be different
        await hass.async_add_executor_job(
            tracker.track_shipment, "test123456789"
        )
    except Exception as exc:
        # Check if it's an auth error vs other errors
        if "auth" in str(exc).lower() or "unauthorized" in str(exc).lower():
            raise InvalidAuth from exc
        # Other errors are likely just due to invalid tracking number, which is expected
        _LOGGER.debug("API test completed (expected error): %s", exc)

    # Parse tracking numbers
    tracking_numbers = []
    if data.get(CONF_TRACKING_NUMBERS):
        tracking_input = data[CONF_TRACKING_NUMBERS].strip()
        if tracking_input:
            # Split by comma and clean up each number
            tracking_numbers = [
                num.strip() 
                for num in tracking_input.split(",") 
                if num.strip()
            ]
    
    _LOGGER.debug("Parsed tracking numbers: %s", tracking_numbers)

    return {
        "title": "DHL Tracking",
        CONF_API_KEY: data[CONF_API_KEY],
        CONF_TRACKING_NUMBERS: tracking_numbers,
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DHL Tracking."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
