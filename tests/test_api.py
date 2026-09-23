"""Tests for the DHL API client.

All requests are served by Home Assistant's aiohttp mocker - no test ever
talks to the real DHL API.
"""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.dhl_tracking.api import (
    DhlApiError,
    DhlAuthError,
    DhlConnectionError,
    DhlNotFoundError,
    DhlRateLimitError,
    DhlTrackingApi,
)
from custom_components.dhl_tracking.const import API_BASE_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_KEY, TRACKING_NUMBER, shipment_payload, tracking_response

URL = f"{API_BASE_URL}/shipments"


def build_api(hass: HomeAssistant) -> DhlTrackingApi:
    """Return an API client bound to the test session."""
    return DhlTrackingApi(async_get_clientsession(hass), API_KEY)


async def test_get_shipment_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 200 response returns the first shipment and sends the right request."""
    aioclient_mock.get(URL, json=tracking_response(shipment_payload(TRACKING_NUMBER)))

    shipment = await build_api(hass).async_get_shipment(
        TRACKING_NUMBER, language="de", recipient_postal_code="12345"
    )

    assert shipment is not None
    assert shipment["id"] == TRACKING_NUMBER

    method, url, _data, headers = aioclient_mock.mock_calls[0]
    assert method == "GET"
    assert url.query["trackingNumber"] == TRACKING_NUMBER
    assert url.query["language"] == "de"
    assert url.query["recipientPostalCode"] == "12345"
    assert headers["DHL-API-Key"] == API_KEY


async def test_get_shipment_empty_response(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A successful response without shipments yields None."""
    aioclient_mock.get(URL, json={"shipments": []})
    assert await build_api(hass).async_get_shipment(TRACKING_NUMBER) is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, DhlAuthError),
        (403, DhlAuthError),
        (404, DhlNotFoundError),
        (429, DhlRateLimitError),
        (500, DhlApiError),
    ],
)
async def test_error_status_codes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    expected: type[Exception],
) -> None:
    """HTTP errors are mapped onto dedicated exceptions."""
    aioclient_mock.get(URL, status=status, json={"status": status})
    with pytest.raises(expected):
        await build_api(hass).async_get_shipment(TRACKING_NUMBER)


async def test_rate_limit_retry_after(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A numeric Retry-After header is picked up."""
    aioclient_mock.get(URL, status=429, headers={"Retry-After": "120"}, text="")
    with pytest.raises(DhlRateLimitError) as err:
        await build_api(hass).async_get_shipment(TRACKING_NUMBER)
    assert err.value.retry_after == 120


async def test_rate_limit_without_retry_after(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A non-numeric Retry-After falls back to our own backoff schedule."""
    aioclient_mock.get(
        URL,
        status=429,
        headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
        text="",
    )
    with pytest.raises(DhlRateLimitError) as err:
        await build_api(hass).async_get_shipment(TRACKING_NUMBER)
    assert err.value.retry_after is None


async def test_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A timeout is reported as a connection error."""
    aioclient_mock.get(URL, exc=TimeoutError())
    with pytest.raises(DhlConnectionError):
        await build_api(hass).async_get_shipment(TRACKING_NUMBER)


async def test_asyncio_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An asyncio timeout is reported as a connection error too."""
    aioclient_mock.get(URL, exc=TimeoutError())
    with pytest.raises(DhlConnectionError):
        await build_api(hass).async_get_shipment(TRACKING_NUMBER)


async def test_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Client errors are reported as connection errors."""
    from aiohttp import ClientConnectionError

    aioclient_mock.get(URL, exc=ClientConnectionError())
    with pytest.raises(DhlConnectionError):
        await build_api(hass).async_get_shipment(TRACKING_NUMBER)


async def test_validate_credentials_accepts_404(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 404 proves the key works and costs exactly one call."""
    aioclient_mock.get(URL, status=404, json={"status": 404})
    await build_api(hass).async_validate_credentials()
    assert len(aioclient_mock.mock_calls) == 1


async def test_validate_credentials_rejects_401(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 surfaces as an auth error."""
    aioclient_mock.get(URL, status=401, text="")
    with pytest.raises(DhlAuthError):
        await build_api(hass).async_validate_credentials()


async def test_api_key_is_never_logged(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The API key must not leak into log records or exception messages."""
    import logging

    caplog.set_level(logging.DEBUG)

    aioclient_mock.get(URL, status=401, text=f"invalid key {API_KEY}")
    api = build_api(hass)
    with pytest.raises(DhlAuthError) as err:
        await api.async_get_shipment(TRACKING_NUMBER)

    assert API_KEY not in str(err.value)
    assert API_KEY not in repr(err.value)
    assert API_KEY not in caplog.text

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, json=tracking_response(shipment_payload(TRACKING_NUMBER)))
    await api.async_get_shipment(TRACKING_NUMBER)
    assert API_KEY not in caplog.text
