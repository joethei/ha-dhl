"""Constants for the DHL Tracking integration."""

DOMAIN = "dhl_tracking"

# Configuration keys
CONF_API_KEY = "api_key"
CONF_TRACKING_NUMBERS = "tracking_numbers"

# Default values
DEFAULT_NAME = "DHL Tracking"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes

# API Configuration
API_BASE_URL = "https://api-eu.dhl.com/track"

# Attributes
ATTR_TRACKING_NUMBER = "tracking_number"
ATTR_PRODUCT = "product"
ATTR_TOTAL_PIECES = "total_pieces"
ATTR_WEIGHT = "weight"
ATTR_ORIGIN = "origin"
ATTR_DESTINATION = "destination"
ATTR_SERVICE_URL = "service_url"
ATTR_STATUS_CODE = "status_code"
ATTR_STATUS_TIMESTAMP = "status_timestamp"
ATTR_STATUS_DESCRIPTION = "status_description"
ATTR_EVENTS = "events"
