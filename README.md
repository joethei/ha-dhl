# DHL Tracking – Home Assistant Custom Integration

Home-Assistant-Integration zur Verfolgung von DHL-Sendungen über die **offizielle**
[„Shipment Tracking – Unified" API](https://developer.dhl.com/api-reference/shipment-tracking)
von Deutsche Post DHL Group.

Sendungsnummern lassen sich **zur Laufzeit** hinzufügen und entfernen – über die
Benutzeroberfläche oder über Automatisierungen. Weder ein Neustart von Home
Assistant noch eine Neueingabe des API-Schlüssels ist nötig.

## Funktionsumfang

- 📦 Ein Gerät pro Sendung mit 18 Sensoren, gruppiert in der Home-Assistant-Oberfläche
- ➕ `dhl_tracking.add_shipment` / `dhl_tracking.remove_shipment` /
  `dhl_tracking.remove_delivered_shipments` als vollwertige Aktionen
- 🖱️ Options Flow unter *Einstellungen → Geräte & Dienste → DHL Tracking → Konfigurieren*
- 📅 Ereignisse `dhl_tracking_shipment_added`, `dhl_tracking_shipment_removed`,
  `dhl_tracking_status_changed` für Automatisierungen
- ⏱️ Adaptives Polling mit hartem Tagesbudget, damit das DHL-Kontingent nicht reißt
- 🔁 Exponentielles Backoff bei HTTP 429, keine aggressiven Retries
- 🌍 Deutsche und englische Übersetzungen
- 🔐 API-Schlüssel wird niemals geloggt; Diagnosedaten sind redigiert

## Installation

### HACS (empfohlen)

1. HACS öffnen → **Integrationen**
2. Menü (drei Punkte) → **Benutzerdefinierte Repositories**
3. `https://github.com/pascatl/ha-dhl` als Repository vom Typ *Integration* hinzufügen
4. „DHL Tracking" suchen und installieren
5. Home Assistant neu starten

### Manuelle Installation

1. `dhl_tracking.zip` aus den [Releases](https://github.com/pascatl/ha-dhl/releases) laden
2. Inhalt nach `config/custom_components/dhl_tracking/` entpacken
3. Home Assistant neu starten

Das Repository ist nach dem Standard-Layout aufgebaut:

```
custom_components/dhl_tracking/
├── __init__.py          # Setup, Migration, Update-Listener
├── api.py               # Async-Client für die offizielle DHL-API
├── config_flow.py       # Config Flow + Options Flow
├── const.py
├── coordinator.py       # DataUpdateCoordinator, Request-Budget, Backoff
├── diagnostics.py
├── manifest.json
├── models.py            # Datenmodell + Validierung
├── sensor.py
├── services.py
├── services.yaml
├── store.py             # Persistenter Laufzeitzustand
├── strings.json
└── translations/{de,en}.json
```

## Ersteinrichtung

### DHL-API-Schlüssel

1. Account im [DHL Developer Portal](https://developer.dhl.com/) anlegen
2. Eine App für die API **„Shipment Tracking – Unified"** erstellen
3. API-Key kopieren

### Integration hinzufügen

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen**
2. „DHL Tracking" auswählen
3. API-Schlüssel eintragen
4. Sendungsnummern sind **optional** – sie können jederzeit später ergänzt werden

Beim Einrichten wird **genau ein** API-Aufruf zur Prüfung des Schlüssels gemacht.

## Bedienung über die Oberfläche

**Einstellungen → Geräte & Dienste → DHL Tracking → Konfigurieren** öffnet ein Menü:

| Menüpunkt | Funktion |
|---|---|
| **Sendung hinzufügen** | Neue Sendungsnummer mit optionalem Anzeigenamen und Empfänger-PLZ |
| **Sendung bearbeiten** | Anzeigename und Empfänger-PLZ einer vorhandenen Sendung ändern |
| **Sendungen entfernen** | Mehrere Sendungen gleichzeitig entfernen |
| **Abfrage-Einstellungen** | Intervall, Antwortsprache, Umgang mit zugestellten Sendungen |

Options Flow und Aktionen schreiben in denselben Datenbestand (die Config-Entry-Options),
sind also immer synchron. Änderungen greifen sofort – der Config Entry wird dabei
**nicht** neu geladen.

Alternativ lässt sich eine Sendung auch entfernen, indem ihr Gerät in der
Geräteübersicht gelöscht wird.

## Aktionen

### `dhl_tracking.add_shipment`

```yaml
action: dhl_tracking.add_shipment
data:
  tracking_number: "00340434123456789012"
  name: "Ersatzteil"
  recipient_postal_code: "12345"
```

| Feld | Pflicht | Beschreibung |
|---|---|---|
| `tracking_number` | ja | Sendungsnummer. Leerzeichen werden entfernt, Kleinbuchstaben in Großbuchstaben gewandelt. |
| `name` | nein | Anzeigename; wird als Gerätename verwendet und ist später änderbar, ohne neue Entities zu erzeugen. |
| `recipient_postal_code` | nein | Empfänger-PLZ. DHL liefert für `parcel-de`/`parcel-nl` nur damit den vollen Datenumfang. |
| `config_entry_id` | nein | Nur nötig, wenn mehrere DHL-Tracking-Einträge existieren. |

Fehlerfälle (jeweils als `ServiceValidationError` mit übersetzter Meldung):

- leere Nummer → `empty_tracking_number`
- ungültiges Format → `invalid_tracking_number`
- Nummer bereits registriert → `already_tracked` (der gespeicherte Bestand bleibt unverändert)

### `dhl_tracking.remove_shipment`

```yaml
action: dhl_tracking.remove_shipment
data:
  tracking_number: "00340434123456789012"
```

Entfernt die Sendung aus dem persistenten Speicher, löscht die Entities aus der
Entity Registry und das zugehörige Gerät. Eine unbekannte Nummer führt zu
`not_tracked`.

### `dhl_tracking.remove_delivered_shipments`

```yaml
action: dhl_tracking.remove_delivered_shipments
data:
  older_than_days: 7
response_variable: aufgeraeumt
```

Entfernt alle Sendungen, deren Zustellung mindestens `older_than_days` Tage
zurückliegt (Standard: 7, `0` entfernt jede zugestellte Sendung sofort).
Die Aktion liefert eine Antwort:

```yaml
removed:
  - "00340434123456789012"
count: 1
```

Sendungen ohne Zustell-Zeitstempel werden nie automatisch entfernt.

## Ereignisse

| Ereignis | Wann |
|---|---|
| `dhl_tracking_shipment_added` | Sendung wurde registriert |
| `dhl_tracking_shipment_removed` | Sendung wurde entfernt |
| `dhl_tracking_status_changed` | `status.status` oder `status.statusCode` hat sich geändert |

Beispiel-Payload von `dhl_tracking_status_changed`:

```yaml
tracking_number: "00340434123456789012"
name: "Ersatzteil"
old_status: "In Zustellung"
new_status: "Zugestellt"
old_status_code: "transit"
new_status_code: "delivered"
```

Die Ereignisse enthalten bewusst **keine** API-Schlüssel, Adressen oder
Empfängernamen. Beim Start von Home Assistant wird für bereits bekannte
Sendungen **kein** Statusereignis gefeuert – der zuletzt bekannte Status wird
persistent gespeichert und nach dem Neustart wiederhergestellt.

## Beispielautomationen

### Sendungsnummer aus einer E-Mail übernehmen

```yaml
alias: DHL-Sendungsnummer aus E-Mail übernehmen
mode: queued
triggers:
  - trigger: event
    event_type: imap_content
conditions:
  - condition: template
    value_template: >-
      {{ trigger.event.data.text is search('\\b\\d{12,20}\\b') }}
actions:
  - variables:
      tracking_number: >-
        {{ trigger.event.data.text | regex_findall('\\b\\d{12,20}\\b') | first }}
  - action: dhl_tracking.add_shipment
    continue_on_error: true
    data:
      tracking_number: "{{ tracking_number }}"
      name: "{{ trigger.event.data.subject | truncate(80, true, '') }}"
```

> `continue_on_error: true` sorgt dafür, dass eine bereits registrierte Nummer
> die Automation nicht abbrechen lässt.

### Benachrichtigung bei Statusänderung

```yaml
alias: DHL-Statusänderung melden
triggers:
  - trigger: event
    event_type: dhl_tracking_status_changed
actions:
  - action: notify.persistent_notification
    data:
      title: "DHL: {{ trigger.event.data.name }}"
      message: >-
        {{ trigger.event.data.old_status | default('unbekannt') }}
        → {{ trigger.event.data.new_status }}
```

### Zugestellte Sendungen sieben Tage nach Zustellung aufräumen

```yaml
alias: DHL-Sendungen nach Zustellung aufräumen
triggers:
  - trigger: time
    at: "03:30:00"
actions:
  - action: dhl_tracking.remove_delivered_shipments
    data:
      older_than_days: 7
    response_variable: aufgeraeumt
  - if:
      - condition: template
        value_template: "{{ aufgeraeumt.count > 0 }}"
    then:
      - action: notify.persistent_notification
        data:
          title: "DHL Tracking aufgeräumt"
          message: >-
            {{ aufgeraeumt.count }} zugestellte Sendung(en) entfernt:
            {{ aufgeraeumt.removed | join(', ') }}
```

## Entities

Pro Sendung wird ein Gerät mit 18 Sensoren angelegt. Die Unique IDs haben das
Format `dhl_tracking_<sendungsnummer>_<sensor>` und sind gegenüber früheren
Versionen unverändert – vorhandene Entity-IDs bleiben also erhalten.

| Sensor | API-Feld | Kategorie |
|---|---|---|
| Status | `status.status` | – |
| Statuscode | `status.statusCode` (Enum) | Diagnose |
| Status-Zeitstempel | `status.timestamp` | – |
| Statusbeschreibung | `status.description` | – |
| Status-Standort | `status.location` (Ort, Land) | – |
| Service | `service` | Diagnose |
| Produkt | `details.product.productName` | – |
| Anzahl Stücke | `details.totalNumberOfPieces` | – |
| Gewicht | `details.weight.value` | – |
| Gewichtseinheit | `details.weight.unitText` | Diagnose |
| Herkunftsland | `origin.address.countryCode` | Diagnose |
| Herkunftsort | `origin.address.addressLocality` | – |
| Zielland | `destination.address.countryCode` | Diagnose |
| Zielort | `destination.address.addressLocality` | – |
| Abholdatum | `pickUpDate` | – |
| Geplante Zustellung | `estimatedTimeOfDelivery` | – |
| Service-URL | `serviceUrl` | Diagnose |
| Rücksendung | `returnFlag` (Enum `yes`/`no`) | Diagnose |

Zusätzlich existiert pro Konfigurationseintrag ein Dienst-Gerät „DHL Tracking"
mit dem Diagnosesensor **API-Anfragen heute**. Dessen Attribute zeigen das
Tagesbudget, das effektive Intervall und den geschätzten Tagesverbrauch.

Der Sensor **Status** trägt zusätzlich das Attribut `events` mit den letzten
zehn Sendungsereignissen (Zeitstempel, Status, Beschreibung, Ort auf
Stadtebene).

## API-Limits und Abfrageintervall

Der kostenlose DHL-Entwicklertarif erlaubt laut
[offizieller Dokumentation](https://developer.dhl.com/api-reference/shipment-tracking)
**250 Aufrufe pro Tag und maximal einen Aufruf alle fünf Sekunden**.

Die API kennt **keine Sammelabfrage**: `GET /shipments` akzeptiert laut
OpenAPI-Spezifikation 1.5.6 (siehe
[`docs/dhl-shipment-tracking-unified-openapi.yaml`](docs/dhl-shipment-tracking-unified-openapi.yaml))
genau **eine** `trackingNumber` pro Request. Jede Sendung kostet also einen
Aufruf pro Abfrage. Batch-Abfragen sind daher nicht implementiert.

### Berechnung des Tagesverbrauchs

Die Integration arbeitet mit einem eigenen Budget von **200 Aufrufen pro Tag**
(Sicherheitsabstand zu den 250 von DHL, damit Einrichtung, Reauth und manuelle
Aktualisierungen nie das Limit sprengen).

```
aktive Sendungen      A = Sendungen mit statusCode != "delivered"
zugestellte Sendungen Z = Sendungen mit statusCode == "delivered"

Budget für aktive Sendungen:  B = max(A, 200 − Z)
Aufrufe je aktiver Sendung:   C = B / A        (pro Tag)
Fair-Share-Intervall:         F = 86400 / C    (Sekunden)

effektives Intervall (aktiv):      max(eingestelltes Intervall, F)
effektives Intervall (zugestellt): 24 h  bzw. „nie", wenn abgeschaltet
```

Mit dem Standardintervall von 30 Minuten ergibt sich:

| Aktive Sendungen | Fair-Share-Intervall | Effektives Intervall | Aufrufe/Tag |
|---:|---:|---:|---:|
| 1 | 7,2 min | 30 min | 48 |
| 2 | 14,4 min | 30 min | 96 |
| 4 | 28,8 min | 30 min | 192 |
| 5 | 36 min | 36 min | 200 |
| 10 | 72 min | 72 min | 200 |
| 20 | 144 min | 144 min | 200 |

**Der Tagesverbrauch übersteigt 200 Aufrufe nie**, unabhängig von der Anzahl der
Sendungen: Ab fünf aktiven Sendungen begrenzt das Fair-Share-Intervall die
Abfragen. Zusätzlich zählt ein harter Zähler mit und bricht den Abfragezyklus
ab, sobald das Budget erschöpft ist. Zugestellte Sendungen kosten höchstens
einen Aufruf pro Tag und können über die Optionen ganz abgeschaltet werden.

Weitere Schutzmechanismen:

- Zwischen zwei Aufrufen liegen mindestens **6 Sekunden** (DHL erlaubt einen
  Aufruf alle 5 Sekunden).
- Bei **HTTP 429** pausiert die Integration mindestens 15 Minuten, bei
  wiederholten 429-Antworten verdoppelt sich die Pause bis maximal 6 Stunden.
  Ein `Retry-After`-Header wird berücksichtigt, verkürzt die Pause aber nie
  unter 15 Minuten.
- Ein **404** (DHL kennt die Nummer nicht) führt nicht zu sofortigen
  Wiederholungen: Die Entities werden `unavailable`, die nächste Abfrage
  erfolgt erst im regulären Intervall.
- Zähler und Zeitstempel der letzten Abfrage werden **persistent gespeichert**.
  Häufige Neustarts von Home Assistant können das Tagesbudget also nicht
  umgehen; nach einem Neustart sind die Sensorwerte sofort wieder da, ohne dass
  ein API-Aufruf nötig ist.

Das Intervall lässt sich unter *Konfigurieren → Abfrage-Einstellungen* zwischen
5 Minuten und 24 Stunden einstellen. Kürzere Werte werden vom Fair-Share-
Intervall überschrieben, sobald mehrere Sendungen aktiv sind.

## Datenmodell und Persistenz

Jede Sendung wird strukturiert gespeichert:

```json
{
  "tracking_number": "00340434123456789012",
  "name": "Ersatzteil",
  "recipient_postal_code": "12345",
  "created_at": "2026-09-23T12:00:00+00:00"
}
```

**Speicherort: die Config-Entry-Options.** Home Assistant empfiehlt, vom
Benutzer konfigurierbare Daten im Config Entry zu halten: Sie werden mit dem
Eintrag gesichert und wiederhergestellt, sind über den Options Flow editierbar,
lösen automatisch den Update-Listener aus und brauchen keine zweite
Datenquelle, die auseinanderlaufen könnte. Aktionen und Options Flow schreiben
deshalb beide über `hass.config_entries.async_update_entry(entry, options=…)`.

Ein zusätzlicher `Store` (`.storage/dhl_tracking.<entry_id>`) hält ausschließlich
**nicht benutzerkonfigurierbaren Laufzeitzustand**: Zeitpunkt der letzten
Abfrage je Sendung, verbrauchtes Tagesbudget, letzter bekannter Status und die
zuletzt empfangene API-Antwort. Genau dafür ist `Store` gedacht – und es sorgt
dafür, dass ein Neustart weder das Ratenlimit umgeht noch Statusereignisse
doppelt auslöst.

## Migration bestehender Installationen

Bestehende Einträge werden automatisch von Schema-Version 1 auf 2 migriert:

| vorher (Version 1) | nachher (Version 2) |
|---|---|
| `data.api_key` | `data.api_key` (unverändert) |
| `data.tracking_numbers` als Liste **oder** als kommagetrennter String | `options.shipments` als Liste strukturierter Objekte |
| – | `options.scan_interval`, `options.language`, `options.poll_delivered` |

- Die Nummern werden getrimmt, in Großbuchstaben gewandelt und dedupliziert.
- Ungültige Fragmente (z. B. einzelne Ziffern aus einem fehlerhaft
  gesplitteten String) werden verworfen, gültige Nummern gehen nicht verloren.
- Die Unique IDs der Entities (`dhl_tracking_<nummer>_<sensor>`) bleiben
  identisch. **Bestehende Entity-IDs, Verlaufsdaten und Automatisierungen
  funktionieren weiter.**

### Was sich für bestehende Nutzer ändert

- Die Sensoren gehören jetzt zu einem **Gerät pro Sendung**. Der angezeigte
  Name setzt sich aus Gerätename und Sensorname zusammen; die Entity-ID bleibt
  unverändert.
- **Rücksendung** liefert `yes`/`no` statt der fest deutschen Werte `Ja`/`Nein`
  (die Anzeige ist jetzt übersetzt). Templates, die auf `"Ja"` prüfen, müssen
  auf `"yes"` umgestellt werden.
- **Zeitstempel-Sensoren** liefern jetzt echte, zeitzonenbehaftete
  Datumswerte statt roher Zeichenketten.
- Die Debug-Attribute `api_path` und `raw_value` entfallen; stattdessen gibt es
  vollständige, redigierte **Diagnosedaten** pro Konfigurationseintrag.
- Das Standardintervall ist 30 Minuten statt 10 Minuten (siehe API-Limits).

## Datenschutz und Funktionsgrenzen

**Was die Integration nicht tut** – bewusst und dauerhaft:

- kein Login in ein privates „Post & DHL"-Konto
- kein Scraping der DHL-Webseite
- keine inoffiziellen Live-Tracking-Endpunkte
- keine Fahrzeugposition, keine „verbleibenden Stopps"
- keine Speicherung privater DHL-Zugangsdaten

Verwendet wird ausschließlich die offiziell dokumentierte Tracking-API mit einem
Entwickler-API-Schlüssel.

**Umgang mit Daten:**

- Der API-Schlüssel steht ausschließlich im `DHL-API-Key`-Request-Header. Er
  erscheint nicht in Logs, nicht in Fehlermeldungen, nicht in Ereignissen und
  ist in den Diagnosedaten redigiert. Bei einer 401-Antwort wird der Body nicht
  gelesen, weil er Anfragedetails spiegeln könnte.
- Als Unique ID des Config Entry dient ein nicht umkehrbarer SHA-256-Fingerprint
  des Schlüssels, nicht der Schlüssel selbst.
- Ereignisse enthalten nur Sendungsnummer, Anzeigename und Status.
- Standortangaben in Entity-Attributen sind auf Stadt und Land reduziert.
- Diagnosedaten redigieren Empfänger, Absender, Zustellnachweise und
  Postleitzahlen.
- Die rohe API-Antwort wird lokal im Home-Assistant-`Store` zwischengespeichert,
  damit Neustarts kein Kontingent verbrauchen. Sie verlässt das System nicht.

## Fehlerbehebung

| Symptom | Ursache / Abhilfe |
|---|---|
| Entities sind `unavailable` | DHL kennt die Nummer (noch) nicht. Frisch aufgegebene Sendungen erscheinen oft erst nach einigen Stunden. |
| Reauth-Hinweis in der Oberfläche | Der API-Schlüssel wurde abgelehnt. Neuen Schlüssel über den Reauth-Dialog eintragen. |
| Sensor „API-Anfragen heute" bei 200 | Das Tagesbudget ist erschöpft. Intervall verlängern oder zugestellte Sendungen entfernen. |
| Unvollständige Daten bei DHL-Paket (Deutschland) | Empfänger-PLZ ergänzen – DHL liefert den vollen Datensatz für `parcel-de` nur mit `recipientPostalCode`. |

Für Fehlerberichte bitte die **Diagnosedaten** des Eintrags herunterladen
(*Geräte & Dienste → DHL Tracking → ⋮ → Diagnose herunterladen*) – sie sind
bereits redigiert.

## Entwicklung

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

Die Tests laufen vollständig gegen Mock-Antworten und Home Assistants
`aioclient_mock`; **die echte DHL-API wird nie aufgerufen**.

`scripts/dhl_cli.py` ist ein eigenständiges Hilfsskript zum manuellen Abfragen
einer Sendungsnummer (benötigt `requirements.txt`) und ist nicht Teil der
Integration.

## Lizenz

Siehe [LICENSE](LICENSE).
