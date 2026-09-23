"""Constants for the DHL Tracking integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dhl_tracking"

ATTRIBUTION: Final = "Data provided by Deutsche Post DHL Group"
MANUFACTURER: Final = "Deutsche Post DHL Group"

# --- Config entry -----------------------------------------------------------
# Config entry data
CONF_API_KEY: Final = "api_key"

# Config entry options
CONF_SHIPMENTS: Final = "shipments"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_LANGUAGE: Final = "language"
CONF_POLL_DELIVERED: Final = "poll_delivered"

# Legacy config entry key (<= schema version 1), kept for migration only.
CONF_TRACKING_NUMBERS: Final = "tracking_numbers"

# Shipment record keys
CONF_TRACKING_NUMBER: Final = "tracking_number"
CONF_NAME: Final = "name"
CONF_RECIPIENT_POSTAL_CODE: Final = "recipient_postal_code"
CONF_CREATED_AT: Final = "created_at"

# --- Defaults ---------------------------------------------------------------
DEFAULT_NAME: Final = "DHL Tracking"
DEFAULT_LANGUAGE: Final = "de"
SUPPORTED_LANGUAGES: Final = ("de", "en", "fr", "es", "it", "nl", "pl", "cs")

# Poll interval of the coordinator for *active* shipments, in seconds.
DEFAULT_SCAN_INTERVAL: Final = 1800  # 30 minutes
MIN_SCAN_INTERVAL: Final = 300  # 5 minutes - hard floor, not user overridable
MAX_SCAN_INTERVAL: Final = 86400  # 24 hours

# Delivered shipments are polled at most once per this interval (if enabled),
# so a late "returned to sender" update is still picked up eventually.
DELIVERED_SCAN_INTERVAL: Final = 86400  # 24 hours
DEFAULT_POLL_DELIVERED: Final = True

# --- DHL API ----------------------------------------------------------------
API_BASE_URL: Final = "https://api-eu.dhl.com/track"
API_TIMEOUT: Final = 30

# Documented limits of the free ("initial") DHL developer plan for the
# "Shipment Tracking - Unified" API:
#   "250 calls per day, with a maximum of 1 call every 5 seconds."
# https://developer.dhl.com/api-reference/shipment-tracking
API_DAILY_CALL_LIMIT: Final = 250
API_MIN_SECONDS_BETWEEN_CALLS: Final = 6  # 5s documented + 1s safety margin

# Our own budget stays below the documented limit so that manual refreshes,
# config-flow validation and re-authentication never exhaust the quota.
DAILY_REQUEST_BUDGET: Final = 200

# Backoff applied after an HTTP 429 response (seconds).
RATE_LIMIT_BACKOFF_START: Final = 900  # 15 minutes
RATE_LIMIT_BACKOFF_MAX: Final = 21600  # 6 hours

# --- Shipment status --------------------------------------------------------
# `TrackingShipmentStatus.statusCode` enum of the Unified Shipment Tracking API
# (OpenAPI 1.5.6, see docs/dhl-shipment-tracking-unified-openapi.yaml).
STATUS_CODE_DELIVERED: Final = "delivered"
STATUS_CODE_FAILURE: Final = "failure"
STATUS_CODE_PRE_TRANSIT: Final = "pre-transit"
STATUS_CODE_TRANSIT: Final = "transit"
STATUS_CODE_UNKNOWN: Final = "unknown"

STATUS_CODES: Final = (
    STATUS_CODE_DELIVERED,
    STATUS_CODE_FAILURE,
    STATUS_CODE_PRE_TRANSIT,
    STATUS_CODE_TRANSIT,
    STATUS_CODE_UNKNOWN,
)

# --- Poll priority -----------------------------------------------------------
# The API has no "out for delivery" status: `StatusCode` is documented as a
# "high-level grouping" with exactly the five values above, and the detailed
# fields (`status`, `statusDetailed`, `description`, `remark`, `nextSteps`) are
# free text in the language requested via the `language` parameter. Matching on
# them would break as soon as the user changes that language.
#
# The delivery forecast is the only structured, language independent signal, so
# imminence is derived from `estimatedDeliveryTimeFrame` and
# `estimatedTimeOfDelivery` instead.
DELIVERY_IMMINENT_LEAD_HOURS: Final = 8
# A shipment whose forecast has passed but that is not delivered yet is
# probably out for delivery and running late - keep it on the fast lane.
DELIVERY_OVERDUE_GRACE_HOURS: Final = 24

# Relative share of the daily request budget per priority. Only the ratios
# matter; a shipment with twice the weight is polled twice as often.
PRIORITY_WEIGHT_IMMINENT: Final = 6
PRIORITY_WEIGHT_TRANSIT: Final = 2
PRIORITY_WEIGHT_PRE_TRANSIT: Final = 1

# Per-priority floor, relative to the configured scan interval. A shipment is
# never polled more often than its floor allows, even if budget is left over.
IMMINENT_INTERVAL_DIVISOR: Final = 3
PRE_TRANSIT_INTERVAL_FACTOR: Final = 2

# --- Services ---------------------------------------------------------------
SERVICE_ADD_SHIPMENT: Final = "add_shipment"
SERVICE_REMOVE_SHIPMENT: Final = "remove_shipment"
SERVICE_REMOVE_DELIVERED_SHIPMENTS: Final = "remove_delivered_shipments"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_OLDER_THAN_DAYS: Final = "older_than_days"

# Default age for `remove_delivered_shipments`: a safe value, so an accidental
# call without arguments does not drop shipments delivered minutes ago.
DEFAULT_OLDER_THAN_DAYS: Final = 7

# --- Events -----------------------------------------------------------------
EVENT_SHIPMENT_ADDED: Final = "dhl_tracking_shipment_added"
EVENT_SHIPMENT_REMOVED: Final = "dhl_tracking_shipment_removed"
EVENT_STATUS_CHANGED: Final = "dhl_tracking_status_changed"

# --- Dispatcher -------------------------------------------------------------
SIGNAL_SHIPMENTS_CHANGED: Final = "dhl_tracking_shipments_changed_{}"

# --- Validation -------------------------------------------------------------
# DHL tracking numbers differ wildly between business units (10-digit Express
# air waybills, 12-20 digit parcel numbers, alphanumeric international IDs).
# Keep validation permissive but reject obvious junk.
TRACKING_NUMBER_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9-]{3,38}$"
POSTAL_CODE_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9 -]{1,11}$"
MAX_NAME_LENGTH: Final = 100
