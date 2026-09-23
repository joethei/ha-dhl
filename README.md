# DHL Tracking – Home Assistant Custom Integration

Home-Assistant-Integration zur Verfolgung von DHL-Sendungen über die **offizielle**
[„Shipment Tracking – Unified" API](https://developer.dhl.com/api-reference/shipment-tracking)
von Deutsche Post DHL Group.

Sendungsnummern lassen sich **zur Laufzeit** hinzufügen und entfernen – über die
Benutzeroberfläche oder über Automatisierungen. Weder ein Neustart von Home
Assistant noch eine Neueingabe des API-Schlüssels ist nötig.

## Funktionsumfang

- 📦 Ein Gerät pro Sendung mit 24 Sensoren und einer Event-Entität, gruppiert in der Home-Assistant-Oberfläche
- 🏷️ Zustellmerkmale strukturiert: `signature_required`, `id_required`, `services`, Nachnahmebetrag
- 🚚 Eigener Status `out_for_delivery`, abgeleitet aus dem Zustellfenster
- ➕ `dhl_tracking.add_shipment` / `dhl_tracking.remove_shipment` /
  `dhl_tracking.remove_delivered_shipments` als vollwertige Aktionen
- 🖱️ Options Flow unter *Einstellungen → Geräte & Dienste → DHL Tracking → Konfigurieren*
- 📅 Ereignisse `dhl_tracking_shipment_added`, `dhl_tracking_shipment_removed`,
  `dhl_tracking_status_changed` für Automatisierungen
- ⏱️ Adaptives Polling mit hartem Tagesbudget, damit das DHL-Kontingent nicht reißt
- 🚚 Pakete in Zustellung werden dreimal so oft abgefragt wie normal unterwegs befindliche
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
| **Abfrage-Einstellungen** | Intervall, Antwortsprache, Umgang mit zugestellten Sendungen, automatisches Aufräumen |

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
old_status: "PO"                      # status.status, Freitext von DHL
new_status: "Zugestellt"
old_status_code: "out_for_delivery"   # abgeleiteter Wert
new_status_code: "delivered"
old_status_code_api: "transit"        # unveraenderter API-Wert
new_status_code_api: "delivered"
description: "Die Sendung wurde zugestellt."
```

Zusaetzlich gibt es je Sendung eine [Event-Entitaet](#event-entitaet-je-sendung).

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

Pro Sendung wird ein Gerät mit 24 Sensoren und einer Event-Entität angelegt. Die Unique IDs haben das
Format `dhl_tracking_<sendungsnummer>_<sensor>` und sind gegenüber früheren
Versionen unverändert – vorhandene Entity-IDs bleiben also erhalten.

| Sensor | API-Feld | Kategorie |
|---|---|---|
| Status | `status.status` | – |
| Statuscode | `status.statusCode` (Enum) | Diagnose |
| Status-Zeitstempel | `status.timestamp` | – |
| Statusbeschreibung | `status.description` | – |
| Nächste Schritte | `status.nextSteps` | – |
| Kundenreferenz | `details.references[]` (bevorzugt `customer-order-number`) | – |
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
| Abholdatum | `pickUpDate`, nur mit echter Uhrzeit | – |
| Abholtag | `pickUpDate` als Datum | – |
| Geplante Zustellung | `estimatedDeliveryTimeFrame.estimatedFrom`, sonst `estimatedTimeOfDelivery` mit echter Uhrzeit | – |
| Zustelltag | Zustelldatum als reines Datum | – |
| Zustellprognose | `estimatedTimeOfDeliveryRemark` (Klartext von DHL) | – |
| Service-URL | `serviceUrl` | Diagnose |
| Umleitungs-URL | `rerouteUrl` | Diagnose |
| Rücksendung | `returnFlag` (Enum `yes`/`no`) | Diagnose |

Zusätzlich existiert pro Konfigurationseintrag ein Dienst-Gerät „DHL Tracking"
mit dem Diagnosesensor **API-Anfragen heute**. Dessen Attribute zeigen das
Tagesbudget, den geschätzten Tagesverbrauch, die Anzahl Sendungen je Priorität
(`imminent_shipments`, `transit_shipments`, `pre_transit_shipments`) und das
daraus resultierende Intervall je Priorität (`interval_minutes_imminent` usw.).

### Übersichts-Sensoren

Am Dienst-Gerät „DHL Tracking" hängen drei Sensoren, die alle Sendungen
zusammenfassen:

| Entity-ID (deutsche Oberfläche) | Wert |
|---|---|
| `sensor.dhl_tracking_offene_sendungen` | Anzahl Sendungen mit Status ≠ `delivered` |
| `sensor.dhl_tracking_nachste_zustellung` | früheste konkrete Zustellzeit (`timestamp`) |
| `sensor.dhl_tracking_api_anfragen_heute` | verbrauchtes Tagesbudget |

> Das Präfix ist `dhl_tracking_`, weil Home Assistant die Entity-ID aus dem
> Gerätenamen („DHL Tracking") ableitet, und `nachste` ohne Umlaut, weil die
> ID-Erzeugung `ä` zu `a` reduziert. Umbenennen geht jederzeit über die
> Entitäts-Einstellungen.

`offene_sendungen` trägt das Attribut `shipments` – eine Liste mit einem Objekt
je offener Sendung:

```yaml
shipments:
  - tracking_number: "00340434123456789012"
    name: "Ersatzteil"
    status_code: out_for_delivery
    status: "PO"
    description: "Die Sendung wurde in das Zustellfahrzeug geladen."
    estimated_delivery: "2026-09-23T13:20:00+02:00"
    estimated_delivery_date: "2026-09-23"
    time_frame_from: "2026-09-23T13:20:00+02:00"
    time_frame_through: "2026-09-23T14:50:00+02:00"
    signature_required: true
    id_required: false
    services: ["signature"]
```

`nachste_zustellung` liefert die früheste **konkrete** Zustellzeit. Da DHL bei
Paketen oft nur einen Tag kennt, tragen die Attribute zusätzlich die
Tagesebene: `earliest_date`, `earliest_date_tracking_number`,
`earliest_date_name`.

Beide Attributlisten werden bewusst **nicht** in der Datenbank aufgezeichnet.

### Zustellmerkmale (Unterschrift, Nachnahme, Wunschoptionen)

Die Sensoren **Statuscode** und **Produkt** tragen die Zustellmerkmale
strukturiert, damit ein Dashboard nicht den Produkttext parsen muss:

```yaml
services: ["signature"]
signature_required: true
id_required: false
services_raw: ["DHL PAKET"]
cash_on_delivery_amount: 49.9     # nur bei Nachnahme
currency: "EUR"
```

| Schlüssel | Bedeutung | Quelle |
|---|---|---|
| `bulky` | Sperrgut | strukturiert |
| `cash_on_delivery` | Nachnahme | strukturiert |
| `pickup`, `gogreen`, `priority` | gebuchte Zusatzleistungen | strukturiert |
| `extra_insurance`, `direct_injection`, `import_fees` | gebuchte Zusatzleistungen | strukturiert |
| `return` | Rücksendung (`returnFlag`) | strukturiert |
| `signature` | Empfängerunterschrift | Produkttext |
| `ident_check` | Ident-Check / Postident | Produkttext |
| `age_check` | Alterssichtprüfung | Produkttext |
| `preferred_day` | Wunschtag | Produkttext |
| `preferred_location` | Wunschort / Abstellgenehmigung | Produkttext |
| `preferred_neighbour` | Wunschnachbar | Produkttext |
| `no_neighbour_delivery` | keine Nachbarschaftsabgabe / eigenhändig | Produkttext |

`signature_required` ist `true` bei Empfängerunterschrift, Ident-Check,
Alterssichtprüfung und Nachnahme. `id_required` ist `true`, wenn ein Ausweis
gezeigt werden muss (Ident-Check, Alterssichtprüfung).

**Warum teils Text-Parsing?** Das einzige strukturierte Feld der API ist
`details.valueAddedServices.services[].serviceType`, und dessen Enum umfasst
laut OpenAPI 1.5.6 nur `bulky`, `pickup`, `gogreen`, `priority`,
`extraInsurance`, `directInjection`, `cashOnDelivery` und `importFees`.
Empfängerunterschrift, Ident-Check und die Wunschoptionen liefert DHL
ausschließlich im Freitext `details.product.productName`
(`"DHL PAKET, Empfängerunterschrift"`). Das strukturierte Feld hat immer
Vorrang; der Text wird nur für das ausgewertet, was es nicht abdecken kann.
Nicht erkannte Fragmente landen unverändert in `services_raw`.

### Kundenreferenz und Bestellnummer

`details.references[]` trägt die Nummern, unter denen eine Sendung gebucht
wurde. Der Sensor **Kundenreferenz** zeigt die aussagekräftigste davon, in
dieser Reihenfolge: `customer-order-number`, `customer-reference`,
`ecommerce-number`, `customer-confirmation-number`, `local-tracking-number`,
`domestic-consignment-id`, `shipment-id`, `reference`.

```yaml
state: "ORDER-4711"
references:
  - type: "customer-order-number"
    number: "ORDER-4711"
  - type: "housebill"
    number: "HB-1"
```

Damit lässt sich eine Sendung einer Shop-Bestellung zuordnen, ohne über den
Anzeigenamen zu raten:

```yaml
{{ state_attr('sensor.dhl_tracking_offene_sendungen', 'shipments')
   | selectattr('customer_reference', 'eq', 'ORDER-4711') | first }}
```

**Nicht veröffentlicht werden:** die Kontonummer-Typen
`payer-account-number`, `shipper-account-number`, `receiver-account-number`
sowie jeder Eintrag, den DHL über `@scope` als `secret` oder `sensitive`
markiert. Die identifizieren ein Abrechnungskonto, nicht das Paket.

### Sendung umleiten

Der Diagnosesensor **Umleitungs-URL** trägt `rerouteUrl`. DHL liefert das Feld
laut Spec nur, *„if available for the current status of the shipment"* – seine
Anwesenheit ist damit selbst ein Signal. Am Sensor **Statuscode** steht
zusätzlich `reroute_available` als Bool.

```yaml
type: markdown
content: >-
  {% if state_attr('sensor.paket_statuscode', 'reroute_available') %}
  [Sendung umleiten]({{ state_attr('sensor.paket_statuscode', 'reroute_url') }})
  {% endif %}
```

### Weitere Statustexte

DHL liefert bis zu vier Textvarianten zum selben Status. **Status** und
**Statusbeschreibung** sind eigene Sensoren, **Nächste Schritte** ebenfalls;
die beiden restlichen hängen als Attribute an **Statusbeschreibung** und
**Statuscode**:

| Attribut | API-Feld |
|---|---|
| `status_detailed` | `status.statusDetailed` |
| `status_remark` | `status.remark` |
| `next_steps` | `status.nextSteps` |

> Home Assistant lehnt States über 255 Zeichen ab. Längere Texte werden
> gekürzt (erkennbar am `…`), der vollständige Text steht dann im Attribut
> `full_value`.

### Status „In Zustellung"

Der Sensor **Statuscode** kennt einen sechsten Wert `out_for_delivery`,
zusätzlich zu den fünf von DHL dokumentierten. Der unveränderte API-Wert steht
weiterhin im Attribut `status_code_api`.

**Woraus abgeleitet?** Aus dem strukturierten `estimatedDeliveryTimeFrame`:
Ein Zustellfenster, das **am selben lokalen Tag beginnt und endet** und dessen
Tag heute ist, ist die enge Tagesprognose, die DHL veröffentlicht, sobald ein
Paket im Zustellfahrzeug liegt. Eine mehrtägige Spanne zählt bewusst nicht.
Nach Fensterende bleibt der Status noch zwei Stunden bestehen – der Zusteller
kann sich verspäten.

**Warum nicht am Statustext?** DHLs Entwickler-Support schreibt, dass
„Out for Delivery" zwar geplant, aber **noch nicht in der API verfügbar** ist,
und zu den Statusbeschreibungen: *„we do not have any concrete information
about that. It is completely depends on each division and their logic."*
Der bei `parcel-de` auftauchende Wert `PO` ist weder in der OpenAPI-
Spezifikation noch in einem Support-Artikel dokumentiert. Darauf zu matchen
wäre Raterei auf undokumentierten, zudem lokalisierten Daten.

### Zustellort nach der Zustellung

Sobald `statusCode` = `delivered` ist, tragen **Statuscode** und **Status**
zusätzlich:

```yaml
delivered_to: "Erika Mustermann"        # aus details.proofOfDelivery.signed
delivered_at: "2026-09-23T11:05:00+02:00"
delivery_location:
  city: "Hamburg"
  postal_code: "20095"
  country: "DE"
  service_point: "Packstation 123"      # falls Packstation/Filiale
  service_point_url: "https://www.dhl.de/..."
proof_of_delivery_url: "https://webpod.dhl.com/pod?token=..."
```

> **Datenschutzhinweis:** `delivered_to` kann den Namen eines Nachbarn
> enthalten. Das Attribut existiert nur bei zugestellten Sendungen und
> erscheint **nicht** in Ereignissen oder Logs. Vor der Zustellung wird nichts
> veröffentlicht – insbesondere wird `details.receiver` (der Adressat) *nicht*
> als `delivered_to` ausgegeben, denn das wäre geraten.

### Event-Entität je Sendung

Jede Sendung hat zusätzlich eine Event-Entität (`event.<name>_sendungsstatus`)
mit den Event-Typen `pre_transit`, `transit`, `out_for_delivery`, `delivered`,
`failure` und `unknown`. Sie eignet sich als Automationstrigger:

```yaml
triggers:
  - trigger: state
    entity_id: event.ersatzteil_sendungsstatus
    attribute: event_type
    to: out_for_delivery
```

Beim Start von Home Assistant wird **kein** Event ausgelöst – nur echte
Statusänderungen zählen.

### Zustellprognose

DHL liefert die Zustellprognose je nach Geschäftsbereich unterschiedlich genau:
mal als exakten Zeitpunkt, mal als Zeitfenster, meistens aber nur als
Kalendertag – dann steht in `estimatedTimeOfDelivery` ein `00:00:00`, das
*keine* Uhrzeitangabe ist. Deshalb sind es drei Sensoren:

| Sensor | Zeigt | Wenn DHL nur den Tag kennt |
|---|---|---|
| **Geplante Zustellung** (Zeitstempel) | Beginn des Zustellfensters, sonst echte Uhrzeit | `unknown` – es wird keine Uhrzeit erfunden |
| **Zustelltag** (Datum) | „23. September 2026" | gefüllt |
| **Zustellprognose** (Text) | DHLs eigener Klartext | gefüllt, sofern DHL ihn liefert |

Beide Zustell-Sensoren tragen die Rohdaten als Attribute:
`time_frame_from`, `time_frame_through`, `remark` und
`raw_estimated_time_of_delivery`.

Für **Abholdatum** gilt dasselbe: Der Zeitstempel bleibt leer, wenn DHL keine
Uhrzeit liefert; **Abholtag** zeigt das Datum.

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

### Priorität: Pakete in Zustellung werden häufiger abgefragt

Nicht jede Sendung braucht dieselbe Aufmerksamkeit. Ein Paket, das heute noch
kommen soll, ändert seinen Status im Stundentakt; eines, das der Absender
gerade erst angekündigt hat, tagelang gar nicht. Die Integration verteilt das
Tagesbudget deshalb **gewichtet**:

| Priorität | Bedingung | Gewicht | Untergrenze |
|---|---|---:|---|
| **in Zustellung** | Zustellprognose läuft gerade, steht in ≤ 8 h an oder ist ≤ 24 h überfällig | 6 | Intervall ÷ 3 |
| **unterwegs** | `statusCode` = `transit`, `failure` oder `unknown` | 2 | Intervall |
| **angekündigt** | `statusCode` = `pre-transit` | 1 | Intervall × 2 |
| **zugestellt** | `statusCode` = `delivered` | – | 24 h bzw. nie |

Eine Sendung in Zustellung wird also **dreimal so oft** abgefragt wie eine
normal unterwegs befindliche und **sechsmal so oft** wie eine bloß angekündigte.

#### Warum die Zustellprognose und nicht der Statustext?

Die Unified-API kennt **keinen** Statuscode für „in Zustellung". `StatusCode`
ist in der Spezifikation ausdrücklich als *„high-level grouping statuses"* mit
genau fünf Werten definiert. Die feineren Felder – `status`, `statusDetailed`,
`description`, `remark`, `nextSteps` – sind durchweg `type: string` **ohne
Enum** und werden in der Sprache geliefert, die über den `language`-Parameter
angefordert wird. Auf `"In Zustellung"` zu matchen würde also brechen, sobald
jemand die Sprache auf Englisch umstellt.

Strukturiert und sprachunabhängig sind nur `estimatedTimeOfDelivery` und
`estimatedDeliveryTimeFrame`. Genau diese beiden Felder bestimmen die
Priorität. Eine Sendung ohne Prognose bleibt schlicht auf „unterwegs" – sie
wird nie schlechter behandelt als vorher.

Die Kulanz von 24 Stunden nach dem Prognosezeitpunkt ist Absicht: Wenn die
Zustellung angekündigt war und *nicht* stattgefunden hat, ist das genau der
Moment, in dem man häufige Updates will.

### Berechnung des Tagesverbrauchs

Die Integration arbeitet mit einem eigenen Budget von **200 Aufrufen pro Tag**
(Sicherheitsabstand zu den 250 von DHL, damit Einrichtung, Reauth und manuelle
Aktualisierungen nie das Limit sprengen).

```
Z = zugestellte Sendungen         → je 1 Aufruf/Tag (oder 0, wenn abgeschaltet)
B = max(1, 200 − Z)                 Budget für alles, was noch unterwegs ist
W = Σ Gewicht aller nicht zugestellten Sendungen

Aufrufe je Sendung s pro Tag:  C(s) = B · Gewicht(s) / W
Fair-Share-Intervall:          F(s) = 86400 / C(s)          [Sekunden]

effektives Intervall = max(Untergrenze der Priorität, F(s))
```

Da Σ C(s) = B gilt, ist der geplante Tagesverbrauch **per Konstruktion**
höchstens `B + Z = 200`. Sind alle Sendungen gleich priorisiert, reduziert sich
die Formel auf eine gleichmäßige Aufteilung – das Verhalten ohne
Zustellprognose ist also unverändert.

Mit dem Standardintervall von 30 Minuten:

| Szenario | effektives Intervall | Aufrufe/Tag |
|---|---|---:|
| 1× unterwegs | 30 min | 48 |
| 4× unterwegs | 30 min | 192 |
| 5× unterwegs | 36 min | 200 |
| 20× unterwegs | 144 min | 200 |
| 1× **in Zustellung** | 10 min | 144 |
| 1× in Zustellung + 4× unterwegs | 16,8 min / 50,4 min | 200 |
| 2× in Zustellung + 8× unterwegs | 33,6 min / 100,8 min | 200 |
| 1× in Zustellung + 5× unterwegs + 4× angekündigt | 24 / 72 / 144 min | 200 |
| 3× unterwegs + 20× zugestellt | 30 min + 1×/Tag | 164 |

**Der geplante Tagesverbrauch übersteigt 200 Aufrufe nie** – auch nicht bei 260
Sendungen; dann wächst das Intervall entsprechend, statt das Budget zu
überziehen. Ein harter Zähler bricht den Abfragezyklus zusätzlich ab, sobald
das Budget erschöpft ist, und die Warteschlange ist nach Priorität sortiert:
Sendungen in Zustellung werden zuerst bedient, zugestellte zuletzt.

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

## Zugestellte Sendungen automatisch entfernen

*Konfigurieren → Abfrage-Einstellungen → „Zugestellte Sendungen entfernen nach"*

| Wert | Verhalten |
|---|---|
| `0` | Zugestellte Sendungen bleiben dauerhaft erhalten |
| `n` | Eine Sendung wird entfernt, sobald ihre Zustellung `n` Tage zurückliegt |

**Standard ist 3 Tage.** Nach dem Update auf 0.4.0 räumt die Integration also
von selbst auf. Wer das nicht möchte, stellt den Wert auf `0`.

Entfernt wird dasselbe wie bei `dhl_tracking.remove_shipment`: Eintrag im
persistenten Speicher, Entities aus der Entity Registry und das Gerät. Das
Ereignis `dhl_tracking_shipment_removed` wird gefeuert. Sendungen ohne
Zustell-Zeitstempel werden nie automatisch entfernt.

Die Aktion `dhl_tracking.remove_delivered_shipments` bleibt unverändert
verfügbar, falls das Aufräumen lieber über eine eigene Automation laufen soll.

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
- **Geplante Zustellung** und **Abholdatum** zeigen keine erfundene Uhrzeit
  mehr. Liefert DHL nur einen Kalendertag, bleiben diese Zeitstempel leer und
  die neuen Sensoren **Zustelltag** / **Abholtag** tragen das Datum.
  Automationen, die bisher auf `00:00` gerechnet haben, sollten auf den
  jeweiligen Datums-Sensor umgestellt werden.
- Die Debug-Attribute `api_path` und `raw_value` entfallen; stattdessen gibt es
  vollständige, redigierte **Diagnosedaten** pro Konfigurationseintrag.
- Das Standardintervall ist 30 Minuten statt 10 Minuten (siehe API-Limits).
- Seit 0.4.0 ist **„Zugestellte Sendungen entfernen nach" auf 3 Tage
  vorbelegt** – zugestellte Sendungen verschwinden also automatisch. Auf `0`
  stellen, um das abzuschalten.
- Seit 0.4.0 melden Sendungen im Zustellfahrzeug den Statuscode
  `out_for_delivery` statt `transit`. Dashboards, die auf `transit` filtern,
  sollten beide Werte berücksichtigen; der rohe API-Wert steht im Attribut
  `status_code_api`.
- `time_frame_from` / `time_frame_through` sind seit 0.4.0
  zeitzonenbehaftet. Die unveränderten API-Strings stehen unter
  `raw_time_frame_from` / `raw_time_frame_through`.

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
| Paket in Zustellung wird nicht häufiger abgefragt | DHL liefert für diese Sendung keine `estimatedTimeOfDelivery`. Ohne Prognose bleibt sie auf „unterwegs“ – nachprüfbar über das Attribut `imminent_shipments`. |
| Unvollständige Daten bei DHL-Paket (Deutschland) | Empfänger-PLZ ergänzen – DHL liefert den vollen Datensatz für `parcel-de` nur mit `recipientPostalCode`. |

Für Fehlerberichte bitte die **Diagnosedaten** des Eintrags herunterladen
(*Geräte & Dienste → DHL Tracking → ⋮ → Diagnose herunterladen*) – sie sind
bereits redigiert.

## HACS-Standardstore

Die Integration wird als **Custom Repository** installiert (siehe oben). Dafür
ist keine HACS-Validierung nötig.

Für eine Aufnahme in den HACS-**Standardstore** müssten zusätzlich vier Punkte
erfüllt sein, die nichts mit dem Code zu tun haben und deshalb im CI-Workflow
über `ignore:` übersprungen werden:

| Prüfung | Was fehlt |
|---|---|
| `description` | Repository-Beschreibung in den GitHub-Einstellungen |
| `topics` | Mindestens ein Repository-Topic, z. B. `home-assistant`, `hacs`, `dhl` |
| `issues` | Issues müssen im Repository aktiviert sein |
| `brands` | Markenlogo (siehe unten) |

Die `brands`-Prüfung sucht zuerst nach
`custom_components/dhl_tracking/brand/icon.png` (nur Existenz, keine
Größenprüfung) und fragt sonst `brands.home-assistant.io/domains.json` ab.
`dhl_tracking` ist dort aktuell in keinem der 4232 Custom-Domains gelistet.

Für einen Beitrag an [home-assistant/brands](https://github.com/home-assistant/brands)
gelten: `custom_integrations/dhl_tracking/icon.png` mit 256×256 px und
`icon@2x.png` mit 512×512 px, PNG, Transparenz bevorzugt. Wichtig: Custom
Integrations dürfen **keine** Home-Assistant-Markenbilder verwenden, und ein
nachgebautes DHL-Logo wäre eine Markenrechtsfrage – hier wird bewusst kein
Asset erfunden.

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
