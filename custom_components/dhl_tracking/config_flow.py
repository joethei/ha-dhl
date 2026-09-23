"""Config and options flow for the DHL Tracking integration."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    DhlApiError,
    DhlAuthError,
    DhlConnectionError,
    DhlRateLimitError,
    DhlTrackingApi,
)
from .const import (
    CONF_API_KEY,
    CONF_AUTO_REMOVE_DELIVERED_DAYS,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_POLL_DELIVERED,
    CONF_RECIPIENT_POSTAL_CODE,
    CONF_SCAN_INTERVAL,
    CONF_TRACKING_NUMBER,
    CONF_TRACKING_NUMBERS,
    DEFAULT_LANGUAGE,
    DEFAULT_NAME,
    DOMAIN,
    MAX_AUTO_REMOVE_DELIVERED_DAYS,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SUPPORTED_LANGUAGES,
)
from .models import (
    DhlOptions,
    Shipment,
    ShipmentValidationError,
    normalize_name,
    normalize_postal_code,
    normalize_tracking_number,
)

_LOGGER = logging.getLogger(__name__)

CONF_SELECTED = "selected"

API_KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): API_KEY_SELECTOR,
        vol.Optional(CONF_TRACKING_NUMBERS, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
        ),
    }
)

STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): API_KEY_SELECTOR})

SHIPMENT_FIELDS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRACKING_NUMBER): TextSelector(),
        vol.Optional(CONF_NAME): TextSelector(),
        vol.Optional(CONF_RECIPIENT_POSTAL_CODE): TextSelector(),
    }
)

EDIT_SHIPMENT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME): TextSelector(),
        vol.Optional(CONF_RECIPIENT_POSTAL_CODE): TextSelector(),
    }
)

_FIELD_FOR_ERROR = {
    "empty_tracking_number": CONF_TRACKING_NUMBER,
    "invalid_tracking_number": CONF_TRACKING_NUMBER,
    "invalid_name": CONF_NAME,
    "invalid_postal_code": CONF_RECIPIENT_POSTAL_CODE,
}


def _settings_schema(options: DhlOptions) -> vol.Schema:
    """Return the schema of the general settings step."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SCAN_INTERVAL, default=options.scan_interval // 60
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL // 60,
                    max=MAX_SCAN_INTERVAL // 60,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Required(CONF_LANGUAGE, default=options.language): SelectSelector(
                SelectSelectorConfig(
                    options=list(SUPPORTED_LANGUAGES),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="language",
                )
            ),
            vol.Required(
                CONF_POLL_DELIVERED, default=options.poll_delivered
            ): BooleanSelector(),
            vol.Required(
                CONF_AUTO_REMOVE_DELIVERED_DAYS,
                default=options.auto_remove_delivered_days,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=MAX_AUTO_REMOVE_DELIVERED_DAYS,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="d",
                )
            ),
        }
    )


def _shipment_select_schema(options: DhlOptions, *, multiple: bool) -> vol.Schema:
    """Return a schema letting the user pick tracked shipments."""
    choices = [
        SelectOptionDict(
            value=shipment.tracking_number,
            label=(
                f"{shipment.name} ({shipment.tracking_number})"
                if shipment.name
                else shipment.tracking_number
            ),
        )
        for shipment in options.shipments
    ]
    return vol.Schema(
        {
            vol.Required(CONF_SELECTED): SelectSelector(
                SelectSelectorConfig(
                    options=choices,
                    multiple=multiple,
                    mode=SelectSelectorMode.LIST,
                )
            )
        }
    )


async def _async_validate_api_key(
    hass: Any, api_key: str, probe_tracking_number: str | None
) -> str | None:
    """Return an error key when the API key cannot be used, else ``None``."""
    api = DhlTrackingApi(async_get_clientsession(hass), api_key)
    try:
        await api.async_validate_credentials(probe_tracking_number)
    except DhlAuthError:
        return "invalid_auth"
    except DhlRateLimitError:
        return "rate_limited"
    except DhlConnectionError:
        return "cannot_connect"
    except DhlApiError:
        return "cannot_connect"
    except Exception:  # pylint: disable=broad-except - surfaced as "unknown"
        _LOGGER.exception("Unexpected error while validating the DHL API key")
        return "unknown"
    return None


class DhlTrackingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of a DHL Tracking config entry."""

    VERSION = 2
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            shipments: list[Shipment] = []
            try:
                shipments = _parse_tracking_number_input(
                    user_input.get(CONF_TRACKING_NUMBERS, "")
                )
            except ShipmentValidationError as err:
                errors[CONF_TRACKING_NUMBERS] = err.error_key

            if not api_key:
                errors[CONF_API_KEY] = "invalid_auth"

            if not errors:
                await self.async_set_unique_id(_api_key_fingerprint(api_key))
                self._abort_if_unique_id_configured()

                probe = shipments[0].tracking_number if shipments else None
                if error := await _async_validate_api_key(self.hass, api_key, probe):
                    errors["base"] = error

            if not errors:
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={CONF_API_KEY: api_key},
                    options=DhlOptions(shipments=tuple(shipments)).as_dict(),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication after the API key stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user for a new API key."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            options = DhlOptions.from_mapping(entry.options)
            probe = options.shipments[0].tracking_number if options.shipments else None
            if error := await _async_validate_api_key(self.hass, api_key, probe):
                errors["base"] = error
            else:
                await self.async_set_unique_id(_api_key_fingerprint(api_key))
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=STEP_REAUTH_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> DhlOptionsFlowHandler:
        """Return the options flow handler."""
        return DhlOptionsFlowHandler()


class DhlOptionsFlowHandler(OptionsFlow):
    """Manage tracked shipments and polling settings from the UI.

    Every step persists immediately via ``async_create_entry``; the update
    listener in ``__init__`` then applies the change to the running
    integration without reloading the config entry.
    """

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._selected: str | None = None

    @property
    def _options(self) -> DhlOptions:
        """Return the currently stored options."""
        return DhlOptions.from_mapping(self.config_entry.options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the main options menu."""
        menu_options = ["add_shipment"]
        if self._options.shipments:
            menu_options += ["edit_shipment", "remove_shipment"]
        menu_options.append("settings")
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_add_shipment(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new tracking number."""
        errors: dict[str, str] = {}
        options = self._options

        if user_input is not None:
            try:
                shipment = Shipment.create(
                    user_input.get(CONF_TRACKING_NUMBER),
                    user_input.get(CONF_NAME),
                    user_input.get(CONF_RECIPIENT_POSTAL_CODE),
                )
            except ShipmentValidationError as err:
                errors[_FIELD_FOR_ERROR.get(err.error_key, "base")] = err.error_key
            else:
                if options.get(shipment.tracking_number) is not None:
                    errors[CONF_TRACKING_NUMBER] = "already_tracked"
                else:
                    return self.async_create_entry(
                        data=options.with_shipments(
                            [*options.shipments, shipment]
                        ).as_dict()
                    )

        return self.async_show_form(
            step_id="add_shipment",
            data_schema=self.add_suggested_values_to_schema(
                SHIPMENT_FIELDS_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_edit_shipment(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the shipment that should be edited."""
        options = self._options
        if not options.shipments:
            return self.async_abort(reason="no_shipments")

        if user_input is not None:
            self._selected = user_input[CONF_SELECTED]
            return await self.async_step_edit_details()

        return self.async_show_form(
            step_id="edit_shipment",
            data_schema=_shipment_select_schema(options, multiple=False),
        )

    async def async_step_edit_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the display name and recipient postal code of a shipment."""
        options = self._options
        assert self._selected is not None
        current = options.get(self._selected)
        if current is None:  # pragma: no cover - removed in a parallel flow
            return self.async_abort(reason="no_shipments")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                updated = Shipment(
                    tracking_number=current.tracking_number,
                    name=normalize_name(user_input.get(CONF_NAME)),
                    recipient_postal_code=normalize_postal_code(
                        user_input.get(CONF_RECIPIENT_POSTAL_CODE)
                    ),
                    created_at=current.created_at,
                )
            except ShipmentValidationError as err:
                errors[_FIELD_FOR_ERROR.get(err.error_key, "base")] = err.error_key
            else:
                return self.async_create_entry(
                    data=options.with_shipments(
                        updated if s.tracking_number == updated.tracking_number else s
                        for s in options.shipments
                    ).as_dict()
                )

        return self.async_show_form(
            step_id="edit_details",
            data_schema=self.add_suggested_values_to_schema(
                EDIT_SHIPMENT_SCHEMA,
                user_input
                or {
                    CONF_NAME: current.name or "",
                    CONF_RECIPIENT_POSTAL_CODE: current.recipient_postal_code or "",
                },
            ),
            errors=errors,
            description_placeholders={"tracking_number": current.tracking_number},
        )

    async def async_step_remove_shipment(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove one or more tracked shipments."""
        options = self._options
        if not options.shipments:
            return self.async_abort(reason="no_shipments")

        if user_input is not None:
            selected = set(user_input[CONF_SELECTED])
            return self.async_create_entry(
                data=options.with_shipments(
                    shipment
                    for shipment in options.shipments
                    if shipment.tracking_number not in selected
                ).as_dict()
            )

        return self.async_show_form(
            step_id="remove_shipment",
            data_schema=_shipment_select_schema(options, multiple=True),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the polling settings."""
        options = self._options

        if user_input is not None:
            scan_interval = int(user_input[CONF_SCAN_INTERVAL]) * 60
            return self.async_create_entry(
                data={
                    **options.as_dict(),
                    CONF_SCAN_INTERVAL: max(
                        MIN_SCAN_INTERVAL, min(scan_interval, MAX_SCAN_INTERVAL)
                    ),
                    CONF_LANGUAGE: user_input.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    CONF_POLL_DELIVERED: bool(user_input[CONF_POLL_DELIVERED]),
                    CONF_AUTO_REMOVE_DELIVERED_DAYS: min(
                        max(int(user_input[CONF_AUTO_REMOVE_DELIVERED_DAYS]), 0),
                        MAX_AUTO_REMOVE_DELIVERED_DAYS,
                    ),
                }
            )

        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(options)
        )


def _parse_tracking_number_input(raw: str) -> list[Shipment]:
    """Parse the comma separated tracking numbers of the initial setup step."""
    shipments: list[Shipment] = []
    seen: set[str] = set()
    for chunk in raw.replace("\n", ",").replace(";", ",").split(","):
        if not chunk.strip():
            continue
        tracking_number = normalize_tracking_number(chunk)
        if tracking_number in seen:
            continue
        seen.add(tracking_number)
        shipments.append(Shipment.create(tracking_number))
    return shipments


def _api_key_fingerprint(api_key: str) -> str:
    """Return a non-reversible fingerprint used as the entry unique id.

    The API key itself is never used as an identifier so that it does not show
    up in diagnostics, logs or the config entry unique id.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]
