"""Constants for the DHL Tracking integration."""

DOMAIN = "dhl_tracking"

# Configuration keys
CONF_API_KEY = "api_key"
CONF_TRACKING_NUMBERS = "tracking_numbers"

# Default values
DEFAULT_NAME = "DHL Tracking"
DEFAULT_SCAN_INTERVAL = 600  # 10 minutes to respect rate limit
MIN_SCAN_INTERVAL = 300  # Minimum 5 minutes between requests

# API Configuration
API_BASE_URL = "https://api-eu.dhl.com/track"
API_RATE_LIMIT_PER_DAY = 250  # DHL API rate limit
API_REQUESTS_PER_HOUR_SAFE = 8  # Safe limit: ~192 requests per day

# Sensor types - Ein Sensor für jedes API-Attribut
SENSOR_TYPES = {
    "status": {
        "name": "Status",
        "icon": "mdi:package-variant-closed",
        "device_class": None,
        "unit": None,
        "api_path": ["status", "status"],
    },
    "status_code": {
        "name": "Status Code",
        "icon": "mdi:barcode",
        "device_class": None,
        "unit": None,
        "api_path": ["status", "statusCode"],
    },
    "status_timestamp": {
        "name": "Status Zeitstempel",
        "icon": "mdi:clock-outline",
        "device_class": "timestamp",
        "unit": None,
        "api_path": ["status", "timestamp"],
    },
    "status_description": {
        "name": "Status Beschreibung",
        "icon": "mdi:text",
        "device_class": None,
        "unit": None,
        "api_path": ["status", "description"],
    },
    "status_location": {
        "name": "Status Standort",
        "icon": "mdi:map-marker",
        "device_class": None,
        "unit": None,
        "api_path": ["status", "location"],
    },
    "service": {
        "name": "Service",
        "icon": "mdi:truck",
        "device_class": None,
        "unit": None,
        "api_path": ["service"],
    },
    "product_name": {
        "name": "Produkt",
        "icon": "mdi:package",
        "device_class": None,
        "unit": None,
        "api_path": ["details", "product", "productName"],
    },
    "total_pieces": {
        "name": "Anzahl Stücke",
        "icon": "mdi:package-variant",
        "device_class": None,
        "unit": "Stück",
        "api_path": ["details", "totalNumberOfPieces"],
    },
    "weight_value": {
        "name": "Gewicht",
        "icon": "mdi:weight-kilogram",
        "device_class": "weight",
        "unit": None,
        "api_path": ["details", "weight", "value"],
    },
    "weight_unit": {
        "name": "Gewichtseinheit",
        "icon": "mdi:scale",
        "device_class": None,
        "unit": None,
        "api_path": ["details", "weight", "unitText"],
    },
    "origin_country": {
        "name": "Herkunftsland",
        "icon": "mdi:flag",
        "device_class": None,
        "unit": None,
        "api_path": ["origin", "address", "countryCode"],
    },
    "origin_city": {
        "name": "Herkunftsort",
        "icon": "mdi:city",
        "device_class": None,
        "unit": None,
        "api_path": ["origin", "address", "addressLocality"],
    },
    "destination_country": {
        "name": "Zielland",
        "icon": "mdi:flag-outline",
        "device_class": None,
        "unit": None,
        "api_path": ["destination", "address", "countryCode"],
    },
    "destination_city": {
        "name": "Zielort",
        "icon": "mdi:city-variant",
        "device_class": None,
        "unit": None,
        "api_path": ["destination", "address", "addressLocality"],
    },
    "pickup_date": {
        "name": "Abholdatum",
        "icon": "mdi:calendar-start",
        "device_class": "timestamp",
        "unit": None,
        "api_path": ["pickUpDate"],
    },
    "estimated_delivery": {
        "name": "Geplante Zustellung",
        "icon": "mdi:calendar-check",
        "device_class": "timestamp",
        "unit": None,
        "api_path": ["estimatedTimeOfDelivery"],
    },
    "service_url": {
        "name": "Service URL",
        "icon": "mdi:web",
        "device_class": None,
        "unit": None,
        "api_path": ["serviceUrl"],
    },
    "return_flag": {
        "name": "Rücksendung",
        "icon": "mdi:keyboard-return",
        "device_class": None,
        "unit": None,
        "api_path": ["returnFlag"],
    },
}

# Attributes
ATTR_TRACKING_NUMBER = "tracking_number"
ATTR_PRODUCT = "product"
ATTR_TOTAL_PIECES = "total_pieces"
ATTR_WEIGHT = "weight"
ATTR_ORIGIN = "origin"
ATTR_DESTINATION = "destination"
ATTR_SERVICE_URL = "service_url"
ATTR_STATUS_CODE = "status_code"
ATTR_ORIGINAL_STATUS = "original_status"
ATTR_STATUS_TIMESTAMP = "status_timestamp"
ATTR_STATUS_DESCRIPTION = "status_description"
ATTR_EVENTS = "events"
