"""Shared test constants."""

from __future__ import annotations

from typing import Any

API_KEY = "test-api-key-do-not-log"
TRACKING_NUMBER = "00340434123456789012"
OTHER_TRACKING_NUMBER = "00340434987654321098"


def shipment_payload(
    tracking_number: str = TRACKING_NUMBER,
    *,
    status: str = "In transit",
    status_code: str = "transit",
    timestamp: str = "2026-09-20T09:15:00+02:00",
    estimated_delivery: str | None = "2026-09-21T12:00:00+02:00",
    delivery_time_frame: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a TrackingShipment payload modelled after the DHL OpenAPI spec."""
    payload: dict[str, Any] = {
        "id": tracking_number,
        "service": "parcel-de",
        "origin": {"address": {"countryCode": "DE", "addressLocality": "Berlin"}},
        "destination": {"address": {"countryCode": "DE", "addressLocality": "Hamburg"}},
        "status": {
            "timestamp": timestamp,
            "location": {
                "address": {"countryCode": "DE", "addressLocality": "Hamburg"}
            },
            "statusCode": status_code,
            "status": status,
            "description": "The shipment is on its way.",
        },
        "pickUpDate": "2026-09-19T17:00:00+02:00",
        "serviceUrl": f"https://www.dhl.de/de/privatkunden.html?piececode={tracking_number}",
        "returnFlag": False,
        "details": {
            "product": {"productName": "DHL Paket"},
            "totalNumberOfPieces": 1,
            "weight": {"value": 2.5, "unitText": "kg"},
            "receiver": {"name": "Erika Mustermann"},
        },
        "events": [
            {
                "timestamp": timestamp,
                "statusCode": status_code,
                "status": status,
                "description": "The shipment is on its way.",
                "location": {
                    "address": {"countryCode": "DE", "addressLocality": "Hamburg"}
                },
            }
        ],
    }
    if estimated_delivery is not None:
        payload["estimatedTimeOfDelivery"] = estimated_delivery
    if delivery_time_frame is not None:
        payload["estimatedDeliveryTimeFrame"] = delivery_time_frame
    return payload


def tracking_response(*shipments: dict[str, Any]) -> dict[str, Any]:
    """Wrap shipments into a TrackingShipments response."""
    return {"shipments": list(shipments)}
