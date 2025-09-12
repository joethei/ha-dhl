"""DHL Tracker API client."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .const import API_BASE_URL, MIN_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class DHLTracker:
    """DHL Tracking API client with rate limiting."""

    def __init__(self, api_key: str) -> None:
        """Initialize the DHL Tracker.

        Args:
            api_key: The DHL API key
        """
        self.api_key = api_key
        self.base_url = API_BASE_URL
        self.last_request_time = 0
        self.request_count_today = 0
        self.last_reset_date = time.strftime("%Y-%m-%d")

    def _respect_rate_limit(self) -> None:
        """Ensure we respect the API rate limits."""
        current_date = time.strftime("%Y-%m-%d")

        # Reset daily counter if it's a new day
        if current_date != self.last_reset_date:
            self.request_count_today = 0
            self.last_reset_date = current_date
            _LOGGER.info("Daily API request counter reset")

        # Check if we've hit the daily limit
        if self.request_count_today >= 240:  # Leave some buffer
            _LOGGER.warning(
                "Approaching daily API limit (%d/250). Skipping request.",
                self.request_count_today,
            )
            raise Exception("Daily API rate limit reached")

        # Ensure minimum time between requests
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < MIN_SCAN_INTERVAL:
            sleep_time = MIN_SCAN_INTERVAL - time_since_last
            _LOGGER.debug("Rate limiting: sleeping for %.1f seconds", sleep_time)
            time.sleep(sleep_time)

        self.last_request_time = time.time()
        self.request_count_today += 1

        _LOGGER.debug("API request %d/250 for today", self.request_count_today)

    def track_shipment(
        self, tracking_number: str, service: str | None = None, language: str = "de"
    ) -> dict[str, Any]:
        """Track a shipment by tracking number.

        Args:
            tracking_number: The tracking number
            service: The service type (optional)
            language: The language for the response (default: "de")

        Returns:
            The API response with shipment information

        Raises:
            requests.HTTPError: On API errors
            Exception: On rate limit violations
        """
        # Respect rate limits before making request
        self._respect_rate_limit()

        url = f"{self.base_url}/shipments"
        headers = {"DHL-API-Key": self.api_key, "Accept": "application/json"}
        params: dict[str, str] = {
            "trackingNumber": tracking_number,
            "language": language,
        }
        if service:
            params["service"] = service

        _LOGGER.debug("Making API request for tracking number: %s", tracking_number)

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_shipment_status(self, tracking_number: str) -> dict[str, Any] | None:
        """Get the complete shipment data from DHL API.

        Args:
            tracking_number: The tracking number

        Returns:
            Complete shipment data from DHL API or None if not found
        """
        try:
            result = self.track_shipment(tracking_number)
            shipments = result.get("shipments", [])

            if not shipments:
                _LOGGER.warning("No shipments found for %s", tracking_number)
                return None

            # Return the complete shipment data from the API
            shipment = shipments[0]  # Take the first shipment
            _LOGGER.debug(
                "Successfully retrieved data for tracking number: %s", tracking_number
            )
            return shipment

        except Exception as exc:
            if "rate limit" in str(exc).lower():
                _LOGGER.warning(
                    "Rate limit reached, skipping update for %s: %s",
                    tracking_number,
                    exc,
                )
            else:
                _LOGGER.error("Error tracking shipment %s: %s", tracking_number, exc)
            return None
