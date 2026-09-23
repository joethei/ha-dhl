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
CONF_AUTO_REMOVE_DELIVERED_DAYS: Final = "auto_remove_delivered_days"

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

# Automatically drop delivered shipments after this many days. 0 disables it.
DEFAULT_AUTO_REMOVE_DELIVERED_DAYS: Final = 3
MAX_AUTO_REMOVE_DELIVERED_DAYS: Final = 365

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

# Values the API itself can return.
API_STATUS_CODES: Final = (
    STATUS_CODE_DELIVERED,
    STATUS_CODE_FAILURE,
    STATUS_CODE_PRE_TRANSIT,
    STATUS_CODE_TRANSIT,
    STATUS_CODE_UNKNOWN,
)

# Derived by this integration on top of `transit`. DHL developer support lists
# "Out for Delivery" as planned but not yet available in the API, and the
# division specific texts in `status.status` (for example "PO") are not
# documented anywhere - DHL states the descriptions "completely depend on each
# division and their logic". The derivation therefore uses the structured
# `estimatedDeliveryTimeFrame` instead of any status text.
STATUS_CODE_OUT_FOR_DELIVERY: Final = "out_for_delivery"

# Exposed as the `options` of the status code sensor.
STATUS_CODES: Final = (*API_STATUS_CODES, STATUS_CODE_OUT_FOR_DELIVERY)

# A same-day delivery window still counts as "out for delivery" for this long
# after it has closed - the courier may simply be running late.
OUT_FOR_DELIVERY_GRACE_HOURS: Final = 2

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

# --- Delivery features ------------------------------------------------------
# Normalised service keys exposed as the `services` entity attribute. Only
# `bulky`, `cash_on_delivery`, `pickup`, `gogreen`, `priority`,
# `extra_insurance`, `direct_injection` and `import_fees` have a structured
# counterpart in the API (`ValueAddedService.serviceType`); the rest is parsed
# out of the free-text product name. See shipment_features.py.
SERVICE_AGE_CHECK: Final = "age_check"
SERVICE_BULKY: Final = "bulky"
SERVICE_CASH_ON_DELIVERY: Final = "cash_on_delivery"
SERVICE_DIRECT_INJECTION: Final = "direct_injection"
SERVICE_EXTRA_INSURANCE: Final = "extra_insurance"
SERVICE_GOGREEN: Final = "gogreen"
SERVICE_IDENT_CHECK: Final = "ident_check"
SERVICE_IMPORT_FEES: Final = "import_fees"
SERVICE_NO_NEIGHBOUR_DELIVERY: Final = "no_neighbour_delivery"
SERVICE_PICKUP: Final = "pickup"
SERVICE_PREFERRED_DAY: Final = "preferred_day"
SERVICE_PREFERRED_LOCATION: Final = "preferred_location"
SERVICE_PREFERRED_NEIGHBOUR: Final = "preferred_neighbour"
SERVICE_PRIORITY: Final = "priority"
SERVICE_RETURN: Final = "return"
SERVICE_SIGNATURE: Final = "signature"

# --- References -------------------------------------------------------------
# `details.references[]` carries the numbers a shipment was booked under. The
# order below decides which one the "customer reference" sensor shows.
REFERENCE_TYPE_PRIORITY: Final = (
    "customer-order-number",
    "customer-reference",
    "ecommerce-number",
    "customer-confirmation-number",
    "local-tracking-number",
    "domestic-consignment-id",
    "shipment-id",
    "reference",
)

# Never published as an entity state or attribute, whatever `@scope` says.
SENSITIVE_REFERENCE_TYPES: Final = frozenset(
    {
        "payer-account-number",
        "receiver-account-number",
        "shipper-account-number",
    }
)

# `Reference.@scope` values DHL itself marks as protected.
SENSITIVE_REFERENCE_SCOPES: Final = frozenset({"secret", "sensitive"})

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

# Fired from the payload diff: everything below is derived from data that the
# regular poll already fetched, so none of it costs an extra API request.
EVENT_SCAN_ADDED: Final = "dhl_tracking_scan_added"
EVENT_DELIVERY_CHANGED: Final = "dhl_tracking_delivery_changed"
EVENT_DELIVERY_OVERDUE: Final = "dhl_tracking_delivery_overdue"
EVENT_REROUTE_AVAILABLE: Final = "dhl_tracking_reroute_available"
EVENT_PROOF_OF_DELIVERY_AVAILABLE: Final = "dhl_tracking_proof_of_delivery_available"

# How long after the forecast end a shipment is considered overdue.
DELIVERY_OVERDUE_AFTER_HOURS: Final = 2

# --- Dispatcher -------------------------------------------------------------
SIGNAL_SHIPMENTS_CHANGED: Final = "dhl_tracking_shipments_changed_{}"

# --- Validation -------------------------------------------------------------
# DHL tracking numbers differ wildly between business units (10-digit Express
# air waybills, 12-20 digit parcel numbers, alphanumeric international IDs).
# Keep validation permissive but reject obvious junk.
TRACKING_NUMBER_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9-]{3,38}$"
POSTAL_CODE_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9 -]{1,11}$"
MAX_NAME_LENGTH: Final = 100
