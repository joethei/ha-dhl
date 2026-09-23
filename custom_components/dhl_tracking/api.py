"""Asynchronous client for the DHL "Shipment Tracking - Unified" API.

Only the officially documented and publicly available API is used:
``GET {base_url}/shipments`` with a ``DHL-API-Key`` header, as described by
``docs/dhl-shipment-tracking-unified-openapi.yaml`` (OpenAPI 1.5.6) and
https://developer.dhl.com/api-reference/shipment-tracking.

The API key is treated as a secret: it is only ever placed in the request
header and never included in log messages or exception texts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from homeassistant.exceptions import HomeAssistantError

from .const import API_BASE_URL, API_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Tracking number used to probe the credentials during setup. It is
# syntactically valid but will not resolve to a shipment, so the API answers
# with HTTP 404 for a working key and HTTP 401 for a broken one.
CREDENTIAL_PROBE_TRACKING_NUMBER = "00340434000000000000"


class DhlApiError(HomeAssistantError):
    """Base error for all DHL API failures."""

    def __init__(self, translation_key: str = "api_error", **placeholders: Any) -> None:
        """Initialize the error."""
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=translation_key,
            translation_placeholders={k: str(v) for k, v in placeholders.items()}
            or None,
        )


class DhlAuthError(DhlApiError):
    """The API key was rejected (HTTP 401/403)."""

    def __init__(self) -> None:
        """Initialize the error."""
        super().__init__("invalid_auth")


class DhlNotFoundError(DhlApiError):
    """No shipment is known for the tracking number (HTTP 404)."""

    def __init__(self, tracking_number: str) -> None:
        """Initialize the error."""
        super().__init__("shipment_not_found", tracking_number=tracking_number)
        self.tracking_number = tracking_number


class DhlRateLimitError(DhlApiError):
    """The daily/second rate limit was exceeded (HTTP 429)."""

    def __init__(self, retry_after: int | None = None) -> None:
        """Initialize the error."""
        super().__init__("rate_limited")
        self.retry_after = retry_after


class DhlConnectionError(DhlApiError):
    """The API could not be reached, or the request timed out."""

    def __init__(self) -> None:
        """Initialize the error."""
        super().__init__("cannot_connect")


class DhlTrackingApi:
    """Thin async wrapper around the DHL shipment tracking endpoint."""

    def __init__(
        self,
        session: ClientSession,
        api_key: str,
        *,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def async_get_shipment(
        self,
        tracking_number: str,
        *,
        language: str = "de",
        recipient_postal_code: str | None = None,
        service: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the first shipment for ``tracking_number``.

        Returns ``None`` when the API answered successfully but did not include
        any shipment. Raises a :class:`DhlApiError` subclass on failure.
        """
        params: dict[str, str] = {
            "trackingNumber": tracking_number,
            "language": language,
            # The endpoint defaults to 5; we only ever look at the first entry.
            "limit": "1",
        }
        if recipient_postal_code:
            params["recipientPostalCode"] = recipient_postal_code
        if service:
            params["service"] = service

        payload = await self._async_request(params, tracking_number)
        shipments = payload.get("shipments") or []
        if not shipments:
            _LOGGER.debug("DHL API returned no shipments for %s", tracking_number)
            return None
        return shipments[0]

    async def async_validate_credentials(
        self, tracking_number: str | None = None
    ) -> None:
        """Verify the API key using a single request.

        A 404 (unknown tracking number) proves the key is accepted, so the
        probe costs exactly one call from the daily quota.
        """
        probe = tracking_number or CREDENTIAL_PROBE_TRACKING_NUMBER
        try:
            await self.async_get_shipment(probe, language="en")
        except DhlNotFoundError:
            return

    async def _async_request(
        self, params: dict[str, str], tracking_number: str
    ) -> dict[str, Any]:
        """Perform the HTTP request and translate failures into our errors."""
        url = f"{self._base_url}/shipments"
        headers = {
            "DHL-API-Key": self._api_key,
            "Accept": "application/json",
        }

        _LOGGER.debug("Requesting DHL tracking data for %s", tracking_number)
        try:
            async with asyncio.timeout(API_TIMEOUT):
                response = await self._session.get(url, headers=headers, params=params)
                status = response.status
                if status in (401, 403):
                    # Do not read or log the body: it may echo request details.
                    raise DhlAuthError
                if status == 404:
                    raise DhlNotFoundError(tracking_number)
                if status == 429:
                    raise DhlRateLimitError(_parse_retry_after(response.headers))
                if status >= 400:
                    raise DhlApiError("api_error", status=status)
                # `application/problem+json` is used for errors; be lenient.
                data = await response.json(content_type=None)
        except TimeoutError as err:
            raise DhlConnectionError from err
        except ClientResponseError as err:
            raise DhlApiError("api_error", status=err.status) from err
        except ClientError as err:
            raise DhlConnectionError from err

        if not isinstance(data, dict):
            raise DhlApiError("api_error", status="200")
        return data


def _parse_retry_after(headers: Any) -> int | None:
    """Return the ``Retry-After`` value in seconds, when present and numeric."""
    try:
        raw = headers.get("Retry-After")
    except AttributeError:  # pragma: no cover - defensive
        return None
    if raw is None:
        return None
    try:
        return max(0, int(str(raw).strip()))
    except ValueError:
        # HTTP-date form is allowed by RFC 9110 but not used by DHL; ignore it
        # and fall back to our own backoff schedule.
        return None
