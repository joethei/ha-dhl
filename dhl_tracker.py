"""DHL Tracker API client."""
from __future__ import annotations

import logging
from typing import Any

import requests

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class DHLTracker:
    """DHL Tracking API client."""

    def __init__(self, api_key: str) -> None:
        """Initialize the DHL Tracker.
        
        Args:
            api_key: The DHL API key
        """
        self.api_key = api_key
        self.base_url = API_BASE_URL

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
        """
        url = f"{self.base_url}/shipments"
        headers = {
            "DHL-API-Key": self.api_key,
            "Accept": "application/json"
        }
        params: dict[str, str] = {
            "trackingNumber": tracking_number,
            "language": language
        }
        if service:
            params["service"] = service

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_shipment_status(self, tracking_number: str) -> dict[str, Any] | None:
        """Get the current status of a shipment.
        
        Args:
            tracking_number: The tracking number
            
        Returns:
            Shipment status information or None if not found
        """
        try:
            result = self.track_shipment(tracking_number)
            shipments = result.get("shipments", [])
            
            if not shipments:
                _LOGGER.warning("No shipments found for %s", tracking_number)
                return None
                
            shipment = shipments[0]  # Take the first shipment
            
            # Extract relevant information
            status = shipment.get("status", {})
            details = shipment.get("details", {})
            
            return {
                "tracking_number": shipment.get("id", tracking_number),
                "status": status.get("status", "Unknown"),
                "status_code": status.get("statusCode", ""),
                "status_timestamp": status.get("timestamp", ""),
                "description": status.get("description", ""),
                "product": details.get("product", {}).get("productName", "Unknown"),
                "total_pieces": details.get("totalNumberOfPieces", 0),
                "weight": self._get_weight_string(details.get("weight", {})),
                "origin": self._get_location_string(shipment.get("origin", {})),
                "destination": self._get_location_string(
                    shipment.get("destination", {})
                ),
                "service_url": shipment.get("serviceUrl", ""),
                "events": shipment.get("events", []),
                "raw_data": shipment,
            }
        except requests.RequestException as exc:
            _LOGGER.error("Error tracking shipment %s: %s", tracking_number, exc)
            return None
        except Exception as exc:
            _LOGGER.exception(
                "Unexpected error tracking shipment %s: %s", tracking_number, exc
            )
            return None

    def _get_weight_string(self, weight_info: dict[str, Any]) -> str:
        """Format weight information as string."""
        if not weight_info:
            return "Unknown"
        
        value = weight_info.get("value", "")
        unit = weight_info.get("unitText", "")
        
        if value and unit:
            return f"{value} {unit}"
        elif value:
            return str(value)
        else:
            return "Unknown"

    def _get_location_string(self, location_info: dict[str, Any]) -> str:
        """Format location information as string."""
        if not location_info:
            return "Unknown"
        
        address = location_info.get("address", {})
        country = address.get("countryCode", "")
        city = address.get("addressLocality", "")
        
        if country and city:
            return f"{city}, {country}"
        elif country:
            return country
        elif city:
            return city
        else:
            return "Unknown"
