# DHL Tracking Home Assistant Integration

Eine Home Assistant Custom Component zur Verfolgung von DHL-Sendungen über die offizielle DHL Tracking API.

## Features

- 📦 Verfolge mehrere DHL-Sendungen gleichzeitig
- 🔄 Automatische Aktualisierung alle 10 Minuten (respektiert DHL API Rate Limits)
- 🌍 Unterstützt internationale DHL-Sendungen  
- 📱 Einfache Konfiguration über die Home Assistant UI
- 📊 **16 verschiedene Sensoren** pro Sendung mit spezifischen API-Attributen
- � Direkter Zugriff auf alle DHL API-Daten ohne Übersetzung
- ⚡ Intelligentes Rate Limiting (max. 240 Requests/Tag)
- 🛡️ Automatische Fehlerbehandlung bei API-Limits
- 🔍 Debug-Informationen mit API-Pfaden in Sensor-Attributen

## Installation

### HACS (Empfohlen)

1. Öffne HACS in Home Assistant
2. Gehe zu "Integrations"
3. Klicke auf die drei Punkte oben rechts und wähle "Custom repositories"
4. Füge `https://github.com/pascatl/ha-dhl` als Repository hinzu
5. Suche nach "DHL Tracking" und installiere es
6. Starte Home Assistant neu

> 💡 **Tipp**: Die Integration wird über CI/CD automatisch mit neuen Releases aktualisiert!

### Manuelle Installation

1. Lade die neueste `dhl_tracking.zip` von den [GitHub Releases](https://github.com/pascatl/ha-dhl/releases) herunter
2. Erstelle einen Ordner `dhl_tracking` in deinem Home Assistant `custom_components` Verzeichnis  
3. Extrahiere den ZIP-Inhalt in den `custom_components/dhl_tracking` Ordner
4. Starte Home Assistant neu

Deine Ordnerstruktur sollte so aussehen:
```
custom_components/
└── dhl_tracking/
    ├── __init__.py
    ├── manifest.json
    ├── const.py
    ├── config_flow.py
    ├── dhl_tracker.py
    ├── sensor.py
    └── strings.json
```

**Wichtig**: Kopiere nur die Component-Dateien (`.py` und `.json`), nicht die anderen Dateien wie `README.md`, `main.py`, etc.

## Konfiguration

### DHL API-Schlüssel erhalten

1. Besuche das [DHL Developer Portal](https://developer.dhl.com/)
2. Erstelle einen Account oder melde dich an
3. Erstelle eine neue App und wähle die "Track & Trace" API
4. Kopiere deinen API-Schlüssel

### Integration einrichten

1. Gehe zu **Einstellungen** > **Geräte & Dienste**
2. Klicke auf **Integration hinzufügen**
3. Suche nach "DHL Tracking"
4. Gib deinen DHL API-Schlüssel ein
5. Füge deine Sendungsnummern hinzu (durch Komma getrennt)

## Verwendung

Nach der Einrichtung werden für jede Sendungsnummer **16 verschiedene Sensoren** erstellt, die direkten Zugriff auf alle DHL API-Attribute bieten:

### 📊 Verfügbare Sensoren pro Sendung

| Sensor | Entity ID | Beschreibung | API Pfad |
|--------|-----------|--------------|----------|
| **Status** | `sensor.dhl_<nummer>_status` | Aktueller Sendungsstatus | `status.status` |
| **Status Code** | `sensor.dhl_<nummer>_status_code` | DHL-Statuscode (z.B. "OK", "PO") | `status.statusCode` |
| **Status Zeitstempel** | `sensor.dhl_<nummer>_status_timestamp` | Zeitpunkt der letzten Statusänderung | `status.timestamp` |
| **Status Beschreibung** | `sensor.dhl_<nummer>_status_description` | Detaillierte Statusbeschreibung | `status.description` |
| **Status Standort** | `sensor.dhl_<nummer>_status_location` | Aktueller Standort der Sendung | `status.location` |
| **Service** | `sensor.dhl_<nummer>_service` | DHL-Service (z.B. "express", "parcel-de") | `service` |
| **Produkt** | `sensor.dhl_<nummer>_product_name` | Produktname (z.B. "DHL Paket") | `details.product.productName` |
| **Anzahl Stücke** | `sensor.dhl_<nummer>_total_pieces` | Anzahl der Pakete | `details.totalNumberOfPieces` |
| **Gewicht** | `sensor.dhl_<nummer>_weight_value` | Gewichtswert | `details.weight.value` |
| **Gewichtseinheit** | `sensor.dhl_<nummer>_weight_unit` | Gewichtseinheit (z.B. "kg") | `details.weight.unitText` |
| **Herkunftsland** | `sensor.dhl_<nummer>_origin_country` | Land des Absenders | `origin.address.countryCode` |
| **Herkunftsort** | `sensor.dhl_<nummer>_origin_city` | Stadt des Absenders | `origin.address.addressLocality` |
| **Zielland** | `sensor.dhl_<nummer>_destination_country` | Zielland | `destination.address.countryCode` |
| **Zielort** | `sensor.dhl_<nummer>_destination_city` | Zielstadt | `destination.address.addressLocality` |
| **Abholdatum** | `sensor.dhl_<nummer>_pickup_date` | Datum der Abholung | `pickUpDate` |
| **Geplante Zustellung** | `sensor.dhl_<nummer>_estimated_delivery` | Geschätzte Zustellzeit | `estimatedTimeOfDelivery` |
| **Service URL** | `sensor.dhl_<nummer>_service_url` | Link zur DHL-Sendungsverfolgung | `serviceUrl` |
| **Rücksendung** | `sensor.dhl_<nummer>_return_flag` | Ist es eine Rücksendung? | `returnFlag` |

### 📋 Sensor-Attribute

Jeder Sensor enthält zusätzliche Debug-Informationen:

```yaml
# Beispiel eines Status-Sensors
tracking_number: "1234567890123456789"
api_path: "status -> status"
raw_value: "delivered"  # Originaler API-Wert
events: [...]  # Vollständiger Sendungsverlauf
```

## Automatisierung

Du kannst Automatisierungen basierend auf den verschiedenen Sensoren erstellen:

### 📦 Zustellung benachrichtigen
```yaml
automation:
  - alias: "DHL Paket zugestellt"
    trigger:
      - platform: state
        entity_id: sensor.dhl_1234567890123456789_status
        to: "delivered"
    action:
      - service: notify.mobile_app
        data:
          title: "📦 DHL Paket angekommen!"
          message: "Deine Sendung {{ trigger.entity_id.split('_')[1] }} wurde zugestellt."
```

### 🚚 Status-Code überwachen
```yaml
automation:
  - alias: "DHL Status geändert"
    trigger:
      - platform: state
        entity_id: sensor.dhl_1234567890123456789_status_code
    action:
      - service: notify.mobile_app
        data:
          title: "� DHL Status Update"
          message: "Neuer Status: {{ states('sensor.dhl_1234567890123456789_status_code') }}"
```

### 📍 Standortänderung verfolgen
```yaml
automation:
  - alias: "DHL Standort geändert"
    trigger:
      - platform: state
        entity_id: sensor.dhl_1234567890123456789_status_location
    condition:
      - condition: template
        value_template: "{{ trigger.from_state.state != trigger.to_state.state }}"
    action:
      - service: notify.mobile_app
        data:
          title: "📍 DHL Standort Update"
          message: "Neuer Standort: {{ states('sensor.dhl_1234567890123456789_status_location') }}"
```

### ⏰ Geschätzte Zustellung überwachen
```yaml
automation:
  - alias: "DHL Zustellung geplant"
    trigger:
      - platform: state
        entity_id: sensor.dhl_1234567890123456789_estimated_delivery
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state not in ['unknown', 'unavailable'] }}"
    action:
      - service: notify.mobile_app
        data:
          title: "📅 DHL Zustellung geplant"
          message: "Zustellung geplant für: {{ states('sensor.dhl_1234567890123456789_estimated_delivery') }}"
```

## Fehlerbehebung

## 🔧 Troubleshooting

### Häufige Probleme

1. **Ungültiger API-Schlüssel**: Überprüfe deinen DHL API-Schlüssel im Developer Portal
2. **Keine Daten**: Stelle sicher, dass die Sendungsnummer korrekt und aktuell ist
3. **Rate Limiting**: Die DHL API hat Begrenzungen (250 Requests/Tag) - Integration pausiert automatisch
4. **Mehrere gleiche Entities**: Lösche die Integration und richte sie neu ein
5. **Tracking-Nummer wird als einzelne Ziffern behandelt**: Verwende Version 0.0.2 oder neuer

## 🔧 Troubleshooting

### Häufige Probleme

1. **Ungültiger API-Schlüssel**: Überprüfe deinen DHL API-Schlüssel im Developer Portal
2. **Keine Daten**: Stelle sicher, dass die Sendungsnummer korrekt und aktuell ist
3. **Rate Limiting**: Die DHL API hat Begrenzungen (250 Requests/Tag) - Integration pausiert automatisch
4. **Mehrere gleiche Entities**: Lösche die Integration und richte sie neu ein
5. **Sensoren zeigen "unknown"**: Prüfe die API-Pfade in den Sensor-Attributen

### ⚡ DHL API Rate Limits

Die DHL API erlaubt **250 Requests pro Tag**. Diese Integration:
- ✅ Aktualisiert alle **10 Minuten** (144 Requests/Tag pro Sendung)
- ✅ Überwacht täglich verbrauchte Requests
- ✅ Pausiert automatisch bei Erreichen des Limits
- ✅ Mindestabstand von **5 Minuten** zwischen Requests
- ✅ Behält vorherige Daten bei Rate Limit Fehlern

**💡 Tipp**: Bei vielen Sendungen (>2) erwäge manuelle Anpassung des Update-Intervalls in der Sensor-Konfiguration.

### 🔍 Debug-Informationen

Jeder Sensor zeigt in seinen Attributen:
- `api_path`: Der verwendete API-Pfad (z.B. "status -> statusCode")
- `raw_value`: Der ursprüngliche Wert aus der DHL API
- `tracking_number`: Die zugehörige Sendungsnummer
- `events`: Vollständiger Sendungsverlauf (nur bei bestimmten Sensoren)

### Debug-Logs aktivieren

Füge das zu deiner `configuration.yaml` hinzu:

```yaml
logger:
  default: info
  logs:
    custom_components.dhl_tracking: debug
```

### API-Daten verstehen

Die Integration gibt die DHL API-Daten **direkt** weiter, ohne Übersetzung:

**Beispiel API-Antwort Struktur:**
```json
{
  "status": {
    "status": "delivered",
    "statusCode": "OK", 
    "timestamp": "2025-09-12T14:25:00",
    "description": "Successfully delivered",
    "location": {...}
  },
  "service": "express",
  "details": {
    "product": {"productName": "DHL Express"},
    "totalNumberOfPieces": 1,
    "weight": {"value": 1.2, "unitText": "kg"}
  },
  "origin": {"address": {"countryCode": "DE", "addressLocality": "Hamburg"}},
  "destination": {"address": {"countryCode": "DE", "addressLocality": "München"}},
  "pickUpDate": "2025-09-10T10:00:00",
  "estimatedTimeOfDelivery": "2025-09-12T16:00:00",
  "serviceUrl": "https://www.dhl.de/...",
  "returnFlag": false
}
```

**Sensor-Mapping:** Jeder Sensor extrahiert einen spezifischen Wert aus dieser JSON-Struktur basierend auf seinem `api_path`.

## Beitragen

Beiträge sind willkommen! Bitte:

1. Forke das Repository
2. Erstelle einen Feature-Branch
3. Committe deine Änderungen
4. Erstelle eine Pull Request

### 🚀 Entwicklung

Das Projekt nutzt GitHub Actions für automatische Releases:
- **Release Pipeline**: Erstellt automatisch ZIP-Dateien für HACS bei neuen Tags
- **Version Bump**: Manuelle Workflows zum Erhöhen der Versionsnummer
- **CI/CD**: Automatische Tests und Validierung

## Changelog

### Version 0.0.3 (Current)
- ✅ **16 separate Sensoren** pro Sendung für alle API-Attribute
- ✅ Direkter Zugriff auf DHL API-Daten ohne Übersetzung
- ✅ Intelligentes Rate Limiting (250 Requests/Tag)
- ✅ Automatische Pausierung bei API-Limits
- ✅ Debug-Informationen mit API-Pfaden
- ✅ Verbesserte Fehlerbehandlung
- ✅ Update-Intervall auf 10 Minuten optimiert

### Version 0.0.2
- ✅ Deutsche Übersetzung der DHL-Statuscodes
- ✅ Mehrere Sensoren pro Sendung (Status, Standort, Produkt, Timing)
- ✅ Verbesserte Fehlerbehandlung für ungültige Tracking-Nummern
- ✅ CI/CD Pipeline für automatische Releases

### Version 0.0.1
- 🎉 Initiale Version mit grundlegender DHL-Tracking Funktionalität

## Lizenz

Dieses Projekt steht unter der MIT-Lizenz. Siehe [LICENSE](LICENSE) für Details.

## Haftungsausschluss

Diese Integration ist nicht offiziell von DHL unterstützt oder bestätigt. Sie nutzt die öffentliche DHL Tracking API.