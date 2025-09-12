# DHL Tracking Home Assistant Integration

Eine Home Assistant Custom Component zur Verfolgung von DHL-Sendungen über die offizielle DHL Tracking API.

## Features

- 📦 Verfolge mehrere DHL-Sendungen gleichzeitig
- 🔄 Automatische Aktualisierung alle 5 Minuten
- 🌍 Unterstützt internationale DHL-Sendungen
- 📱 Einfache Konfiguration über die Home Assistant UI
- 📊 Detaillierte Sendungsinformationen als Sensor-Attribute

## Installation

### HACS (Empfohlen)

1. Öffne HACS in Home Assistant
2. Gehe zu "Integrations"
3. Klicke auf die drei Punkte oben rechts und wähle "Custom repositories"
4. Füge `https://github.com/pascatl/ha-dhl` als Repository hinzu
5. Suche nach "DHL Tracking" und installiere es
6. Starte Home Assistant neu

### Manuelle Installation

1. Erstelle einen Ordner `dhl_tracking` in deinem Home Assistant `custom_components` Verzeichnis
2. Kopiere alle Dateien aus diesem Repository in den `custom_components/dhl_tracking` Ordner
3. Starte Home Assistant neu

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

Nach der Einrichtung werden für jede Sendungsnummer Sensoren erstellt:

- **Sensor-Name**: `sensor.dhl_tracking_<sendungsnummer>`
- **Status**: Aktueller Sendungsstatus
- **Attribute**: Detaillierte Sendungsinformationen

### Beispiel Sensor-Attribute

```yaml
tracking_number: "00340434175969812466"
product: "DHL Paket"
total_pieces: 1
weight: "2.5 kg"
origin: "Köln, DE"
destination: "Berlin, DE"
status_code: "transit"
status_timestamp: "2025-09-12T10:30:00"
status_description: "Die Sendung ist unterwegs zum Ziel-Paketzentrum"
service_url: "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode=00340434175969812466"
events: [...] # Vollständiger Sendungsverlauf
```

## Automatisierung

Du kannst Automatisierungen basierend auf Sendungsstatus erstellen:

```yaml
automation:
  - alias: "DHL Paket zugestellt"
    trigger:
      - platform: state
        entity_id: sensor.dhl_tracking_00340434175969812466
        to: "delivered"
    action:
      - service: notify.mobile_app
        data:
          message: "Dein DHL Paket wurde zugestellt!"
```

## Fehlerbehebung

### Häufige Probleme

1. **Ungültiger API-Schlüssel**: Überprüfe deinen DHL API-Schlüssel
2. **Keine Daten**: Stelle sicher, dass die Sendungsnummer korrekt ist
3. **Rate Limiting**: Die DHL API hat Begrenzungen - reduziere die Aktualisierungsfrequenz

### Debug-Logs aktivieren

Füge das zu deiner `configuration.yaml` hinzu:

```yaml
logger:
  logs:
    custom_components.dhl_tracking: debug
```

## Beitragen

Beiträge sind willkommen! Bitte:

1. Forke das Repository
2. Erstelle einen Feature-Branch
3. Committe deine Änderungen
4. Erstelle eine Pull Request

## Lizenz

Dieses Projekt steht unter der MIT-Lizenz. Siehe [LICENSE](LICENSE) für Details.

## Haftungsausschluss

Diese Integration ist nicht offiziell von DHL unterstützt oder bestätigt. Sie nutzt die öffentliche DHL Tracking API.