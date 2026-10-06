# DHL Tracking für Home Assistant

Diese Integration verfolgt DHL-Sendungen über die offizielle
["Shipment Tracking Unified" API](https://developer.dhl.com/api-reference/shipment-tracking)
von Deutsche Post DHL Group.

Sendungsnummern kommen und gehen zur Laufzeit, über die Oberfläche oder per
Automation. Home Assistant muss dafür nicht neu starten, und den API-Schlüssel
gibst du nur einmal ein.

## Funktionsumfang

- Ein Gerät pro Sendung mit 25 Sensoren und zwei Event-Entitäten
- Zustellmerkmale als eigene Felder: `signature_required`, `id_required`, `services`, Nachnahmebetrag
- Drei Statuscodes, die DHL nicht selbst liefert: `out_for_delivery` aus dem Zustellfenster, `delayed` bei abgelaufener Prognose und `ready_for_pickup` für Pakete in der Packstation
- Sensor "Abholort" mit Adresse und Nummer der Packstation
- Binärsensoren "Zustellung heute erwartet" und "Abholung wartet" für einfache Automationsbedingungen
- Attribut `delivery_type`, das eine Zustellung am Ablageort und eine Abholung aus der Packstation erkennt
- Prüfziffer-Kontrolle für 20-stellige Paketnummern und ein Reparaturhinweis, wenn DHL eine Nummer nicht kennt
- Die Aktionen `dhl_tracking.add_shipment`, `dhl_tracking.remove_shipment` und `dhl_tracking.remove_delivered_shipments`
- Options Flow unter *Einstellungen → Geräte & Dienste → DHL Tracking → Konfigurieren*
- Acht Ereignisse für Automationen, darunter jeder einzelne Scan und überfällige Zustellungen
- Ein hartes Tagesbudget, damit das DHL-Kontingent nicht reißt. Pakete in Zustellung fragt die Integration dreimal so oft ab wie andere.
- Exponentielles Backoff bei HTTP 429
- Deutsche und englische Übersetzungen
- Der API-Schlüssel landet nie im Log, und die Diagnosedaten sind redigiert

## Installation

### HACS

Der empfohlene Weg.

1. HACS öffnen → **Integrationen**
2. Menü mit den drei Punkten → **Benutzerdefinierte Repositories**
3. `https://github.com/pascatl/ha-dhl` als Repository vom Typ *Integration* hinzufügen
4. "DHL Tracking" suchen und installieren
5. Home Assistant neu starten

### Manuelle Installation

1. `dhl_tracking.zip` aus den [Releases](https://github.com/pascatl/ha-dhl/releases) laden
2. Inhalt nach `config/custom_components/dhl_tracking/` entpacken
3. Home Assistant neu starten

Das Repository folgt dem Standard-Layout:

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
2. Eine App für die API "Shipment Tracking Unified" erstellen
3. API-Key kopieren

### Integration hinzufügen

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen**
2. "DHL Tracking" auswählen
3. API-Schlüssel eintragen
4. Sendungsnummern sind optional, du kannst sie jederzeit später ergänzen

Die Einrichtung kostet genau einen API-Aufruf, mit dem die Integration den
Schlüssel prüft.

## Bedienung über die Oberfläche

**Einstellungen → Geräte & Dienste → DHL Tracking → Konfigurieren** öffnet ein Menü:

| Menüpunkt | Funktion |
|---|---|
| Sendung hinzufügen | Neue Sendungsnummer mit optionalem Anzeigenamen und Empfänger-PLZ |
| Sendung bearbeiten | Anzeigename und Empfänger-PLZ einer vorhandenen Sendung ändern |
| Sendungen entfernen | Mehrere Sendungen auf einmal entfernen |
| Abfrage-Einstellungen | Intervall, Antwortsprache, Umgang mit zugestellten Sendungen, automatisches Aufräumen |

Options Flow und Aktionen schreiben in dieselben Config-Entry-Options und sind
deshalb immer synchron. Änderungen greifen sofort, ohne dass der Config Entry
neu lädt.

Du kannst eine Sendung auch entfernen, indem du ihr Gerät in der
Geräteübersicht löschst.

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
| `tracking_number` | ja | Sendungsnummer. Die Integration entfernt Leerzeichen und wandelt Kleinbuchstaben in Großbuchstaben. |
| `name` | nein | Anzeigename. Er wird zum Gerätenamen und lässt sich später ändern, ohne dass neue Entities entstehen. |
| `recipient_postal_code` | nein | Empfänger-PLZ. Für `parcel-de` und `parcel-nl` liefert DHL nur damit den vollen Datensatz. |
| `config_entry_id` | nein | Nur nötig, wenn es mehrere DHL-Tracking-Einträge gibt. |

Bei ungültigen Eingaben bricht die Aktion mit einem `ServiceValidationError`
und einer übersetzten Meldung ab:

- leere Nummer → `empty_tracking_number`
- ungültiges Format → `invalid_tracking_number`
- falsche Prüfziffer bei einer 20-stelligen Nummer → `invalid_check_digit`
- Nummer schon registriert → `already_tracked`, der gespeicherte Bestand bleibt unverändert

### `dhl_tracking.remove_shipment`

```yaml
action: dhl_tracking.remove_shipment
data:
  tracking_number: "00340434123456789012"
```

Die Aktion entfernt die Sendung aus dem Speicher und löscht ihre Entities und
ihr Gerät. Eine unbekannte Nummer führt zu `not_tracked`.

### `dhl_tracking.remove_delivered_shipments`

```yaml
action: dhl_tracking.remove_delivered_shipments
data:
  older_than_days: 7
response_variable: aufgeraeumt
```

Die Aktion entfernt alle Sendungen, deren Zustellung mindestens
`older_than_days` Tage zurückliegt. Der Standard ist 7, bei `0` verschwindet
jede zugestellte Sendung sofort. Die Antwort sieht so aus:

```yaml
removed:
  - "00340434123456789012"
count: 1
```

Sendungen ohne Zustell-Zeitstempel bleiben immer stehen.

## Ereignisse

| Ereignis | Wann |
|---|---|
| `dhl_tracking_shipment_added` | Sendung wurde registriert |
| `dhl_tracking_shipment_removed` | Sendung wurde entfernt |
| `dhl_tracking_status_changed` | `status.status` oder `status.statusCode` hat sich geändert |
| `dhl_tracking_scan_added` | neuer Eintrag in `events[]`, also jeder Scan, auch ohne Statuswechsel |
| `dhl_tracking_delivery_changed` | Zustellfenster oder Zustelltag hat sich verschoben |
| `dhl_tracking_delivery_overdue` | Prognose seit mehr als zwei Stunden vorbei, Paket nicht zugestellt |
| `dhl_tracking_reroute_available` | DHL liefert einen Umleitungs-Link |
| `dhl_tracking_proof_of_delivery_available` | Zustellnachweis ist abrufbar |

Die Integration leitet alle Ereignisse aus dem Vergleich zweier API-Antworten
ab. Sie kosten also keinen zusätzlichen Aufruf. Der erste Datensatz einer
Sendung legt nur den Ausgangsstand fest. Weder ein Neustart noch eine Nummer,
die schon seit Tagen unterwegs ist, spielt die Historie als Ereignisse nach.

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
delivery_type: null                   # nach der Zustellung z. B. "drop_off"
timestamp: "2026-09-23T11:05:00+02:00" # wann DHL gescannt hat
delay_minutes: 37                     # so viel später hat HA davon erfahren
```

Dazu hat jede Sendung zwei [Event-Entitäten](#event-entitäten-je-sendung).

Ereignisse enthalten keine API-Schlüssel und keine Empfängernamen. Beim Start
von Home Assistant feuert für bekannte Sendungen kein Statusereignis, weil die
Integration den letzten Status speichert und nach dem Neustart wiederherstellt.

## Fallstricke bei Automationen

Die Integration ist kein Live-Tracking. Zwei Verzögerungen addieren sich.

1. **DHL.** Ein Scan erscheint erst mit Verzögerung in der Entwickler-API.
   Wie lange das dauert, dokumentiert DHL nicht. Die DHL-App ist meist
   schneller, siehe [unten](#die-app-zeigt-andere-zeiten-als-home-assistant).
2. **Abfragetakt.** Das Tageskontingent erlaubt pro Sendung nur eine Abfrage
   alle paar Minuten bis Stunden. Pakete in Zustellung kommen am häufigsten
   dran, angekündigte und abholbereite am seltensten, siehe
   [Priorität](#priorität-pakete-in-zustellung-werden-häufiger-abgefragt).

Ein Ereignis erreicht Home Assistant deshalb typischerweise Minuten bis über
eine Stunde nach dem echten Scan. Das hat Folgen.

| Fallstrick | Was passiert | Besser |
|---|---|---|
| Zwischenschritte fehlen | `dhl_tracking_status_changed` vergleicht nur zwei Abfragen. Wird ein Paket zwischen zwei Abfragen beladen *und* zugestellt, springt der Status direkt von `transit` auf `delivered`. Eine Automation auf `out_for_delivery` feuert dann nie. | Für Zwischenschritte `dhl_tracking_scan_added` nutzen, das feuert für jeden Scan. Oder den Zustand prüfen, statt auf den Übergang zu warten. Ein Beispiel steht unten. |
| Auslösezeit ist nicht Scanzeit | Die Automation läuft, wenn Home Assistant vom Scan erfährt. "Zugestellt" kommt an, wenn das Paket längst vor der Tür liegt. | Für Uhrzeiten `timestamp` aus dem Ereignis verwenden, das gibt es in `dhl_tracking_scan_added` und `dhl_tracking_status_changed`. `delay_minutes` im Statusereignis sagt, wie alt die Nachricht ist. Um dem Paketboten die Tür zu öffnen, taugt die Integration nicht. |
| Mehrere Scans auf einmal | Eine Abfrage kann mehrere neue Scans liefern, die direkt hintereinander feuern. Im Modus `single` gehen alle bis auf den ersten verloren. | `mode: queued` verwenden. |
| Entitäten verschwinden | Jede Sendung hat eigene Entitäten. Wird sie entfernt, auch automatisch nach der Zustellung, sind die Entitäten weg und Automationen auf eine feste Entity-ID brechen. | Auf die `dhl_tracking_*`-Ereignisse triggern und `trigger.event.data.name` oder `tracking_number` verwenden. Oder die Übersichts-Sensoren auswerten. |
| Abgeleitete Zustände sind Schätzungen | `out_for_delivery`, `delayed` und `ready_for_pickup` meldet DHL nicht selbst. `out_for_delivery` gibt es nur mit einem Zustellfenster für heute, und viele DHL-Pakete haben nur einen Zustelltag. `delayed` greift zwei Stunden nach Ende der Prognose und erst mit der nächsten Abfrage. | Nicht davon ausgehen, dass jedes Paket jeden Status durchläuft. |
| Packstation | Bei einem Packstation-Paket bedeutet `delivered` die Abholung, nicht das Einlegen. | Auf `ready_for_pickup` triggern. |
| Texte vergleichen | `status`, `description` und `remark` sind Freitext in der eingestellten Sprache. Codes wie `PO` sind undokumentiert. Ein Sprachwechsel oder eine Änderung bei DHL bricht die Automation. | Nur `status_code` oder den `event_type` der Event-Entitäten auswerten. |
| Neue Nummern | DHL kennt eine Sendung oft erst Stunden nach der Versandmail. Bis dahin sind die Sensoren leer und ein Reparaturhinweis erscheint. | Abwarten, das ist kein Fehler. |
| Funkstille | Ist das Tagesbudget erschöpft, gibt es bis Mitternacht keine Updates. Nach einem HTTP 429 pausiert die Integration bis zu sechs Stunden. Solange Home Assistant aus ist, fragt niemand ab. Die erste Abfrage danach holt die Änderungen nach. | Keine Automation bauen, die ein Ereignis innerhalb einer bestimmten Zeit braucht. |

## Beispielautomationen

### Jeden Scan mit Uhrzeit melden

Diese Automation feuert für jeden Scan, auch wenn mehrere mit einer Abfrage
ankommen. Die Meldung nennt die Uhrzeit des Scans, nicht die Auslösezeit.

```yaml
alias: DHL-Scan melden
mode: queued
triggers:
  - trigger: event
    event_type: dhl_tracking_scan_added
actions:
  - action: notify.persistent_notification
    data:
      title: "DHL: {{ trigger.event.data.name }}"
      message: >-
        {{ as_timestamp(trigger.event.data.timestamp)
           | timestamp_custom('%H:%M') }} Uhr:
        {{ trigger.event.data.description }}
```

### Morgen-Übersicht

Um 7 Uhr bekommen alle im Haus eine Nachricht mit den Paketen, die DHL für
heute erwartet. Dazu steht, ob jemand persönlich annehmen muss und wie viel
Bargeld eine Nachnahme kostet. Der Empfänger erfährt das auch aus der DHL-App,
die anderen im Haushalt aber nicht. Wer zu Hause ist, weiß so, dass ein Paket
kommt, das kein Nachbar annehmen darf.

Die Automation liest den Zustand und braucht deshalb kein Ereignis. Sie
funktioniert auch, wenn DHL nur den Tag kennt, und das ist bei den meisten
Paketen so. Um 7 Uhr ist das allerdings eine Prognose. Beladen wird das
Zustellfahrzeug meist erst später am Morgen, und dass das Paket wirklich
unterwegs ist, meldet dem Empfänger dann die DHL-App.

`notify.haushalt` ist eine
[Notify-Gruppe](https://www.home-assistant.io/integrations/group/#notify-groups)
mit den Handys aller im Haus. Gib den Sendungen Namen, an denen die anderen
erkennen, für wen das Paket ist, etwa "Wein (Anna)". Den Empfängernamen gibt
die Integration aus Datenschutzgründen nicht heraus.

```yaml
alias: DHL-Morgenübersicht
triggers:
  - trigger: time
    at: "07:00:00"
variables:
  heute: >-
    {{ state_attr('sensor.dhl_tracking_offene_sendungen', 'shipments')
       | default([], true)
       | selectattr('estimated_delivery_date', 'eq', now().date().isoformat())
       | list }}
conditions:
  - condition: template
    value_template: "{{ heute | count > 0 }}"
actions:
  - action: notify.haushalt
    data:
      title: "Heute {{ heute | count }} DHL-Paket(e)"
      message: |-
        {% for p in heute -%}
        {{ p.name }}
        {%- if p.id_required %}: nur persönlich, Ausweis bereithalten
        {%- elif p.signature_required %}: Unterschrift nötig
        {%- endif %}
        {%- if p.cash_on_delivery_amount %}, Nachnahme
        {{- ' %.2f' | format(p.cash_on_delivery_amount) | replace('.', ',') }}
        {{- ' ' ~ p.currency if p.currency }}
        {%- endif %}
        {% endfor %}
```

Die Nachricht sieht dann so aus:

```
Ersatzteil
Wein (Anna): nur persönlich, Ausweis bereithalten
Kamera: Unterschrift nötig, Nachnahme 49,90 EUR
```

### Packstation beim Rausgehen

Sobald du das Haus verlässt und ein Paket in der Packstation liegt, kommt eine
Erinnerung mit dem Abholort. `person.ich` und `notify.mobile_app_mein_handy`
musst du an deine Installation anpassen.

```yaml
alias: DHL-Packstation beim Rausgehen
triggers:
  - trigger: state
    entity_id: person.ich
    from: home
conditions:
  - condition: state
    entity_id: binary_sensor.dhl_tracking_abholung_wartet
    state: "on"
actions:
  - action: notify.mobile_app_mein_handy
    data:
      title: "Packstation nicht vergessen"
      message: |-
        {% for p in state_attr('binary_sensor.dhl_tracking_abholung_wartet', 'shipments') -%}
        {{ p.name }}: {{ p.pickup_location | default('Abholort unbekannt', true) }},
        abholen bis {{ as_datetime(p.estimated_pickup_deadline).strftime('%d.%m.') }}
        {% endfor %}
```

Die Automation feuert bei jedem Verlassen des Hauses, solange das Paket in der
Packstation liegt. Holst du es ab, meldet DHL `delivered` und die Erinnerungen
hören auf. Das passiert mit der üblichen Verzögerung, siehe
[Fallstricke](#fallstricke-bei-automationen).

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
      {{ trigger.event.data.text is search('\\b(JJD\\d{12,20}|\\d{12,20})\\b') }}
actions:
  - variables:
      tracking_number: >-
        {{ trigger.event.data.text
           | regex_findall('\\b(?:JJD\\d{12,20}|\\d{12,20})\\b') | first }}
  - action: dhl_tracking.add_shipment
    continue_on_error: true
    data:
      tracking_number: "{{ tracking_number }}"
      name: "{{ trigger.event.data.subject | truncate(80, true, '') }}"
```

> Die Regex findet reine Ziffernnummern und Nummern mit `JJD` vorne, wie sie
> DHL bei vielen Paketen verwendet. Mit `continue_on_error: true` bricht die
> Automation nicht ab, wenn die Nummer schon registriert ist.

### Benachrichtigung bei Statusänderung

```yaml
alias: DHL-Statusänderung melden
mode: queued
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

## Entities

Pro Sendung legt die Integration ein Gerät mit 25 Sensoren und zwei
Event-Entitäten an. Die Unique IDs haben das Format
`dhl_tracking_<sendungsnummer>_<sensor>` und sind seit den ersten Versionen
gleich. Vorhandene Entity-IDs bleiben also erhalten.

| Sensor | API-Feld | Kategorie |
|---|---|---|
| Status | `status.status` | |
| Statuscode | `status.statusCode` als Enum | Diagnose |
| Status-Zeitstempel | `status.timestamp` | |
| Statusbeschreibung | `status.description`, ohne HTML | |
| Abholort | Packstation oder Abholstelle aus `status.description` | |
| Nächste Schritte | `status.nextSteps` | |
| Kundenreferenz | `details.references[]`, bevorzugt `customer-order-number` | |
| Status-Standort | `status.location`, Ort und Land | |
| Service | `service` | Diagnose |
| Produkt | `details.product.productName` | |
| Anzahl Stücke | `details.totalNumberOfPieces` | |
| Gewicht | `details.weight.value` | |
| Gewichtseinheit | `details.weight.unitText` | Diagnose |
| Herkunftsland | `origin.address.countryCode` | Diagnose |
| Herkunftsort | `origin.address.addressLocality` | |
| Zielland | `destination.address.countryCode` | Diagnose |
| Zielort | `destination.address.addressLocality` | |
| Abholdatum | `pickUpDate`, nur mit echter Uhrzeit | |
| Abholtag | `pickUpDate` als Datum | |
| Geplante Zustellung | `estimatedDeliveryTimeFrame.estimatedFrom`, sonst `estimatedTimeOfDelivery` mit echter Uhrzeit | |
| Zustelltag | Zustelldatum ohne Uhrzeit | |
| Zustellprognose | `estimatedTimeOfDeliveryRemark`, DHLs Klartext | |
| Service-URL | `serviceUrl` | Diagnose |
| Umleitungs-URL | `rerouteUrl` | Diagnose |
| Rücksendung | `returnFlag` als Enum `yes`/`no` | Diagnose |

Jeder Konfigurationseintrag hat außerdem ein Dienst-Gerät "DHL Tracking" mit
dem Diagnosesensor "API-Anfragen heute". Seine Attribute zeigen das
Tagesbudget, den geschätzten Tagesverbrauch, die Zahl der Sendungen je
Priorität und das Intervall, das sich daraus je Priorität ergibt. Die
Attribute heißen `imminent_shipments`, `transit_shipments`,
`pre_transit_shipments`, `awaiting_pickup_shipments`,
`interval_minutes_imminent` und so weiter.

### Übersichts-Sensoren

Am Dienst-Gerät "DHL Tracking" hängen fünf Entitäten, die alle Sendungen
zusammenfassen:

| Entity-ID bei deutscher Oberfläche | Wert |
|---|---|
| `sensor.dhl_tracking_offene_sendungen` | Anzahl Sendungen mit Status ≠ `delivered` |
| `sensor.dhl_tracking_nachste_zustellung` | früheste konkrete Zustellzeit als `timestamp` |
| `sensor.dhl_tracking_api_anfragen_heute` | verbrauchtes Tagesbudget |
| `binary_sensor.dhl_tracking_zustellung_heute_erwartet` | an, solange DHL heute noch ein Paket an die Tür bringen will |
| `binary_sensor.dhl_tracking_abholung_wartet` | an, solange ein Paket in einer Packstation oder Abholstelle liegt |

Die beiden Binärsensoren beantworten die Frage, die viele Automationen
stellen, ohne dass jede selbst die Sendungsliste filtert. Ihr Attribut
`shipments` nennt die betroffenen Sendungen mit `tracking_number` und `name`,
bei "Abholung wartet" zusätzlich mit `pickup_location`.

"Zustellung heute erwartet" zählt Pakete, deren Zustelltag heute ist und die
noch nicht zugestellt sind. Pakete in der Packstation zählen nicht mit, auch
wenn DHL bei ihnen den Tag der Packstation-Fahrt stehen lässt. Um Mitternacht
rechnet der Sensor neu, ohne auf die nächste Abfrage zu warten. Ein Paket, das
gestern hätte kommen sollen und noch keinen neuen Zustelltag hat, zählt nicht.

> Home Assistant bildet die Entity-ID aus dem Gerätenamen "DHL Tracking",
> daher das Präfix `dhl_tracking_`. Aus `ä` macht die ID-Erzeugung `a`, daher
> `nachste`. Umbenennen kannst du jederzeit in den Entitäts-Einstellungen.

`offene_sendungen` hat das Attribut `shipments`, eine Liste mit einem Objekt
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
    forecast_expired: false
    pickup_location: null             # bei Packstation-Paketen der Abholort
    drop_off_planned: false           # DHL hat den Ablageort angekündigt
    signature_required: true
    id_required: false
    services: ["signature"]
    cash_on_delivery_amount: null     # bei Nachnahme der Betrag, z. B. 49.9
    currency: null
```

`nachste_zustellung` zeigt die früheste konkrete Zustellzeit, die noch
bevorsteht. DHL kennt bei Paketen oft nur den Tag, deshalb haben die Attribute
auch die Tagesebene: `earliest_date`, `earliest_date_tracking_number` und
`earliest_date_name`. Eine Sendung mit abgelaufener Prognose ist keine
"nächste" Zustellung mehr. Sie steht stattdessen im Attribut
`delayed_shipments` mit `tracking_number`, `name` und `overdue_minutes`.

Die Recorder-Datenbank speichert diese Attributlisten nicht.

### Zustellmerkmale

Unterschrift, Nachnahme und Wunschoptionen stehen als eigene Felder an den
Sensoren "Statuscode" und "Produkt". Ein Dashboard muss so keinen Produkttext
zerlegen.

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
| `return` | Rücksendung aus `returnFlag` | strukturiert |
| `signature` | Empfängerunterschrift | Produkttext |
| `ident_check` | Ident-Check oder Postident | Produkttext |
| `age_check` | Alterssichtprüfung | Produkttext |
| `preferred_day` | Wunschtag | Produkttext |
| `preferred_location` | Wunschort oder Abstellgenehmigung | Produkttext |
| `preferred_neighbour` | Wunschnachbar | Produkttext |
| `no_neighbour_delivery` | keine Nachbarschaftsabgabe, eigenhändig | Produkttext |

`signature_required` ist `true` bei Empfängerunterschrift, Ident-Check,
Alterssichtprüfung und Nachnahme. `id_required` ist `true`, wenn der Empfänger
einen Ausweis zeigen muss, also bei Ident-Check und Alterssichtprüfung.

Warum teilweise Text-Parsing? Das einzige strukturierte Feld der API ist
`details.valueAddedServices.services[].serviceType`. Sein Enum umfasst laut
OpenAPI 1.5.6 nur `bulky`, `pickup`, `gogreen`, `priority`, `extraInsurance`,
`directInjection`, `cashOnDelivery` und `importFees`. Empfängerunterschrift,
Ident-Check und die Wunschoptionen stehen nur im Freitext
`details.product.productName`, etwa `"DHL PAKET, Empfängerunterschrift"`. Das
strukturierte Feld hat immer Vorrang. Den Text wertet die Integration nur für
das aus, was das Feld nicht abdeckt. Was sie nicht erkennt, landet unverändert
in `services_raw`.

### Kundenreferenz und Bestellnummer

`details.references[]` enthält die Nummern, unter denen eine Sendung gebucht
wurde. Der Sensor "Kundenreferenz" zeigt die aussagekräftigste davon, in
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

So findest du die Sendung zu einer Shop-Bestellung, ohne über den
Anzeigenamen zu raten:

```yaml
{{ state_attr('sensor.dhl_tracking_offene_sendungen', 'shipments')
   | selectattr('customer_reference', 'eq', 'ORDER-4711') | first }}
```

Nicht veröffentlicht werden die Kontonummer-Typen `payer-account-number`,
`shipper-account-number` und `receiver-account-number`, außerdem jeder
Eintrag, den DHL über `@scope` als `secret` oder `sensitive` markiert. Diese
Nummern gehören zu einem Abrechnungskonto, nicht zum Paket.

### Sendung umleiten

Der Diagnosesensor "Umleitungs-URL" zeigt `rerouteUrl`. Laut Spec liefert DHL
das Feld nur, *"if available for the current status of the shipment"*. Dass es
da ist, sagt also schon etwas. Am Sensor "Statuscode" steht zusätzlich
`reroute_available` als Bool.

```yaml
type: markdown
content: >-
  {% if state_attr('sensor.paket_statuscode', 'reroute_available') %}
  [Sendung umleiten]({{ state_attr('sensor.paket_statuscode', 'reroute_url') }})
  {% endif %}
```

### Weitere Statustexte

DHL liefert bis zu vier Texte zum selben Status. "Status",
"Statusbeschreibung" und "Nächste Schritte" sind eigene Sensoren. Die übrigen
hängen als Attribute an "Statusbeschreibung" und "Statuscode":

| Attribut | API-Feld |
|---|---|
| `status_detailed` | `status.statusDetailed` |
| `status_remark` | `status.remark` |
| `next_steps` | `status.nextSteps` |

> Home Assistant lehnt States über 255 Zeichen ab. Die Integration kürzt
> längere Texte und hängt `…` an. Der vollständige Text steht dann im
> Attribut `full_value`.

### Status "In Zustellung"

Der Sensor "Statuscode" kennt neben den fünf Werten, die DHL dokumentiert,
den Wert `out_for_delivery`. Den unveränderten API-Wert findest du im
Attribut `status_code_api`.

Die Integration leitet ihn aus `estimatedDeliveryTimeFrame` ab. Ein
Zustellfenster, das am selben lokalen Tag beginnt und endet, und zwar heute,
ist die enge Tagesprognose, die DHL veröffentlicht, sobald ein Paket im
Zustellfahrzeug liegt. Eine Spanne über mehrere Tage zählt nicht. Nach
Fensterende bleibt der Status noch zwei Stunden, denn der Zusteller kann sich
verspäten.

Warum nicht am Statustext? DHLs Entwickler-Support schreibt, "Out for
Delivery" sei geplant, aber noch nicht in der API verfügbar. Zu den
Statusbeschreibungen heißt es: *"we do not have any concrete information
about that. It is completely depends on each division and their logic."*
Der Wert `PO`, der bei `parcel-de` auftaucht, steht weder in der
OpenAPI-Spezifikation noch in einem Support-Artikel. Darauf zu matchen hieße,
auf undokumentierten und übersetzten Daten zu raten.

### Status "Verspätet"

Die Entwickler-API zieht ein abgelaufenes Zustellfenster nicht nach. Bei
einem verspäteten Paket zeigte "Geplante Zustellung" deshalb eine Uhrzeit, die
längst vorbei war. Jetzt gilt:

- "Geplante Zustellung" und "Zustelltag" haben die Attribute
  `forecast_expired` und `overdue_minutes`. `forecast_expired` wird `true`,
  sobald das Fenster oder der Zustelltag vorbei ist. DHLs Wert bleibt sichtbar.
- Zwei Stunden nach Ende der Prognose wechselt der Statuscode auf `delayed`,
  angezeigt als "Verspätet". Im selben Moment feuert
  `dhl_tracking_delivery_overdue` und `out_for_delivery` endet. Bekommt die
  Sendung eine neue Prognose, wechselt der Status zurück.
- Zugestellte und abholbereite Pakete gelten nie als verspätet.

### Packstation und Abholstellen

Ein Paket in der Packstation meldet bei DHL weiter `statusCode: transit`, bis
es abgeholt ist. Erst dann kommt `delivered`. Unterscheiden lässt sich der
Fall nur an `statusDetailed`. Dieser Code ist undokumentiert, hängt aber nicht
von der Sprache ab. Er hat drei Teile, und der erste benennt die Art des Scans.

| `statusDetailed` | Bedeutung | Statuscode |
|---|---|---|
| `LDTMV_PCKST_PO` | auf dem Weg zur Packstation | `transit` |
| `HLDCC_LDPCK_LA` | liegt in der Packstation zur Abholung bereit | `ready_for_pickup` |

Für die ganze `HLDCC_`-Gruppe zeigt der Statuscode `ready_for_pickup`, und
beide Event-Entitäten haben dafür einen eigenen Event-Typ. Bis zur Abholung
ändert sich nichts mehr, deshalb fragt die Integration abholbereite Pakete
selten ab.

DHL schreibt die Packstation als HTML-Link in die Statusbeschreibung. Der
Sensor "Abholort" macht daraus Klartext:

```yaml
state: "Packstation 205, Christian-Hülsmeyer-Str. 3, 27472 Cuxhaven"
name: "Packstation 205"
address: "Christian-Hülsmeyer-Str. 3, 27472 Cuxhaven"
postal_code: "27472"
locker_id: "205"
url: "https://www.dhl.de/de/privatkunden/dhl-standorte-finden.html?address=27472:205&preferPackstation=true"
```

Sensoren, Attribute und Ereignisse geben alle Beschreibungstexte ohne HTML
aus.

Die Abholfrist liefert die API nicht. Die Integration schätzt sie aus dem
ersten Packstation-Scan. DHL hält ein Paket
[7 Kalendertage](https://www.paketda.de/empfangen/dhl-lagerfrist.html) in der
Packstation, der Einlegetag zählt mit. Der Sensor "Abholort" und
"Abholung wartet" haben dafür diese Attribute:

```yaml
waiting_since: "2026-10-01T12:33:00+02:00"
days_waiting: 5
estimated_pickup_deadline: "2026-10-07"   # letzter Tag zum Abholen
```

Wurde ein Paket nachträglich zur Packstation umgeleitet, gibt DHL 9 Tage.
Das steht nicht in den Daten, die Schätzung ist dann zwei Tage zu kurz.

### Zustellort nach der Zustellung

Sobald `statusCode` den Wert `delivered` hat, bekommen "Statuscode" und
"Status" diese Attribute:

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
delivery_type: "drop_off"
```

`delivery_type` sagt, wie das Paket angekommen ist. Es steht auch im
Ereignis `dhl_tracking_status_changed`, sodass eine Automation auf die
Zustellung direkt darauf reagieren kann.

| `delivery_type` | Bedeutung | Erkannt an |
|---|---|---|
| `drop_off` | am Ablageort abgelegt | `statusDetailed` beginnt mit `DLVRD_SECPL_` |
| `picked_up` | aus Packstation oder Abholstelle abgeholt | ein früherer Scan meldete `ready_for_pickup` |
| `null` | unbekannt, zum Beispiel an der Tür oder beim Nachbarn | kein bekannter Code |

Für die Abgabe beim Nachbarn habe ich noch keinen Code gesehen. Die
Integration rät deshalb nicht, sondern lässt den Wert leer.

Schon vor der Zustellung kündigt DHL einen Ablageort an, in den beobachteten
Fällen etwa eine Stunde vorher mit dem Code `ADVIS_PFLOC_DD`. Das Attribut
`drop_off_planned` am Statuscode-Sensor und in `offene_sendungen` wird dann
`true`. Ein Beispiel: Kamera oder Kontakt am Ablageort scharf schalten, bevor
das Paket kommt.

> **Datenschutz.** `delivered_to` kann den Namen eines Nachbarn enthalten.
> Das Attribut gibt es nur bei zugestellten Sendungen, und es erscheint weder
> in Ereignissen noch in Logs. Vor der Zustellung veröffentlicht die
> Integration nichts davon. `details.receiver` ist der Adressat, nicht wer das
> Paket angenommen hat, deshalb taucht er nie als `delivered_to` auf.

### Einzelne Tracking-Scans

Die fünf dokumentierten Statuscodes verschlucken viel. Eine Sendung wird
angekündigt, bearbeitet, erreicht die Zielregion und kommt ins
Zustellfahrzeug, und `statusCode` bleibt die ganze Zeit `transit`.

| Zeit | `status` | `statusCode` |
|---|---|---|
| 22.09. 10:44 | `VA` | `pre-transit` |
| 22.09. 19:01 | `AA` | `transit` |
| 23.09. 00:38 | `EE` | `transit` |
| 23.09. 08:24 | `PO` | `transit` |

`dhl_tracking_scan_added` feuert für jeden dieser Schritte:

```yaml
tracking_number: "00340434778681951569"
name: "Libre 3 Plus Sensoren"
status: "EE"
status_code: "transit"
status_detailed: "SRTED_NRQRD_PO"
description: "Die Sendung ist in der Region des Empfängers angekommen …"
location: "Bremen GVZ, DE"
timestamp: "2026-09-23T00:38:00+02:00"
```

DHL dokumentiert die Codes `VA`, `AA`, `EE` und `PO` nicht und sagt, sie
hingen von der jeweiligen Division ab. Die Integration reicht sie deshalb als
Attribut durch und macht keinen Event-Typ daraus. Ein unbekannter Code kann so
nichts kaputt machen.

### Event-Entitäten je Sendung

Jede Sendung hat zwei Event-Entitäten mit den Event-Typen `pre_transit`,
`transit`, `out_for_delivery`, `ready_for_pickup`, `delayed`, `delivered`,
`failure` und `unknown`:

| Entität | Feuert |
|---|---|
| `event.<name>_sendungsstatus` | nur bei einem Statuswechsel |
| `event.<name>_sendungsereignis` | bei jedem Tracking-Scan |

Beide eignen sich als Trigger:

```yaml
triggers:
  - trigger: state
    entity_id: event.ersatzteil_sendungsstatus
    attribute: event_type
    to: out_for_delivery
```

Beim Start von Home Assistant feuert keine der beiden. Nur echte
Statusänderungen zählen.

### Zustellprognose

Wie genau DHL die Zustellung vorhersagt, hängt vom Geschäftsbereich ab. Mal
kommt ein exakter Zeitpunkt, mal ein Zeitfenster, meistens nur ein
Kalendertag. Im letzten Fall steht in `estimatedTimeOfDelivery` ein
`00:00:00`, und das ist keine Uhrzeit. Deshalb gibt es drei Sensoren:

| Sensor | Zeigt | Wenn DHL nur den Tag kennt |
|---|---|---|
| Geplante Zustellung, Zeitstempel | Beginn des Zustellfensters, sonst echte Uhrzeit | `unknown`, die Integration erfindet keine Uhrzeit |
| Zustelltag, Datum | "23. September 2026" | gefüllt |
| Zustellprognose, Text | DHLs eigener Klartext | gefüllt, wenn DHL ihn liefert |

Die beiden ersten haben die Rohdaten als Attribute: `time_frame_from`,
`time_frame_through`, `remark` und `raw_estimated_time_of_delivery`.

Für "Abholdatum" gilt dasselbe. Der Zeitstempel bleibt leer, wenn DHL keine
Uhrzeit liefert, und "Abholtag" zeigt das Datum.

Der Sensor "Status" hat zusätzlich das Attribut `events` mit den letzten zehn
Sendungsereignissen: `timestamp` mit Zeitzone, `status`, `status_code`,
`status_detailed`, `description` und `location` auf Stadtebene.

## API-Limits und Abfrageintervall

Der kostenlose DHL-Entwicklertarif erlaubt laut
[offizieller Dokumentation](https://developer.dhl.com/api-reference/shipment-tracking)
250 Aufrufe pro Tag und höchstens einen Aufruf alle fünf Sekunden.

Eine Sammelabfrage gibt es nicht. `GET /shipments` akzeptiert laut
OpenAPI-Spezifikation 1.5.6 genau eine `trackingNumber` pro Request, siehe
[`docs/dhl-shipment-tracking-unified-openapi.yaml`](docs/dhl-shipment-tracking-unified-openapi.yaml).
Jede Sendung kostet also einen Aufruf pro Abfrage.

### Priorität: Pakete in Zustellung werden häufiger abgefragt

Ein Paket, das heute noch kommen soll, ändert seinen Status im Stundentakt.
Eines, das der Absender gerade erst angekündigt hat, tagelang nicht. Die
Integration verteilt das Tagesbudget deshalb nach Gewicht:

| Priorität | Bedingung | Gewicht | Untergrenze |
|---|---|---:|---|
| in Zustellung | Zustellprognose läuft gerade, steht in ≤ 8 h an oder ist ≤ 24 h überfällig | 6 | Intervall ÷ 3 |
| unterwegs | `statusCode` = `transit`, `failure` oder `unknown` | 2 | Intervall |
| angekündigt | `statusCode` = `pre-transit` | 1 | Intervall × 2 |
| wartet auf Abholung | liegt in der Packstation, `ready_for_pickup` | 1 | Intervall × 2 |
| zugestellt | `statusCode` = `delivered` | 0 | 24 h oder nie |

Eine Sendung in Zustellung kommt also dreimal so oft dran wie eine normal
unterwegs befindliche und sechsmal so oft wie eine bloß angekündigte.

#### Warum die Zustellprognose und nicht der Statustext?

Die Unified-API hat keinen Statuscode für "in Zustellung". Die Spezifikation
definiert `StatusCode` ausdrücklich als *"high-level grouping statuses"* mit
genau fünf Werten. Die feineren Felder `status`, `statusDetailed`,
`description`, `remark` und `nextSteps` sind alle `type: string` ohne Enum,
und DHL liefert sie in der Sprache, die der `language`-Parameter anfordert.
Ein Match auf `"In Zustellung"` bräche, sobald jemand auf Englisch umstellt.

Strukturiert und sprachunabhängig sind nur `estimatedTimeOfDelivery` und
`estimatedDeliveryTimeFrame`. Diese beiden Felder bestimmen die Priorität.
Eine Sendung ohne Prognose bleibt auf "unterwegs" und wird nie schlechter
behandelt als vorher.

Die 24 Stunden Kulanz nach dem Prognosezeitpunkt sind Absicht. Wenn eine
angekündigte Zustellung ausbleibt, will man gerade dann häufige Updates.

### Berechnung des Tagesverbrauchs

Die Integration rechnet mit einem eigenen Budget von 200 Aufrufen pro Tag. Der
Abstand zu DHLs 250 sorgt dafür, dass Einrichtung, Reauth und manuelle
Aktualisierungen nie das Limit sprengen.

```
Z = zugestellte Sendungen         → je 1 Aufruf/Tag (oder 0, wenn abgeschaltet)
B = max(1, 200 − Z)                 Budget für alles, was noch unterwegs ist
W = Σ Gewicht aller nicht zugestellten Sendungen

Aufrufe je Sendung s pro Tag:  C(s) = B · Gewicht(s) / W
Fair-Share-Intervall:          F(s) = 86400 / C(s)          [Sekunden]

effektives Intervall = max(Untergrenze der Priorität, F(s))
```

Weil Σ C(s) = B gilt, liegt der geplante Tagesverbrauch nie über
`B + Z = 200`. Haben alle Sendungen dieselbe Priorität, teilt die Formel das
Budget gleichmäßig auf. Ohne Zustellprognose ändert sich also nichts.

Mit dem Standardintervall von 30 Minuten:

| Szenario | effektives Intervall | Aufrufe/Tag |
|---|---|---:|
| 1× unterwegs | 30 min | 48 |
| 4× unterwegs | 30 min | 192 |
| 5× unterwegs | 36 min | 200 |
| 20× unterwegs | 144 min | 200 |
| 1× in Zustellung | 10 min | 144 |
| 1× in Zustellung + 4× unterwegs | 16,8 min / 50,4 min | 200 |
| 2× in Zustellung + 8× unterwegs | 33,6 min / 100,8 min | 200 |
| 1× in Zustellung + 5× unterwegs + 4× angekündigt | 24 / 72 / 144 min | 200 |
| 3× unterwegs + 20× zugestellt | 30 min + 1×/Tag | 164 |

Der Coordinator wacht so oft auf, wie es die dringendste Sendung verlangt.
Sonst könnte ein kürzeres Intervall nie greifen. Nach jedem Abfragezyklus
bestimmt er den Takt neu, weil sich die Priorität mit der Zustellprognose und
mit der Uhrzeit ändert.

Mehr als 200 Aufrufe plant die Integration nie, auch nicht bei 260 Sendungen.
Dann wächst eben das Intervall. Ein harter Zähler bricht den Abfragezyklus
zusätzlich ab, sobald das Budget erschöpft ist. Die Warteschlange ist nach
Priorität sortiert, Sendungen in Zustellung kommen zuerst dran, zugestellte
zuletzt.

Weitere Schutzmechanismen:

- Zwischen zwei Aufrufen liegen mindestens 6 Sekunden. DHL erlaubt einen
  Aufruf alle 5 Sekunden.
- Bei HTTP 429 pausiert die Integration mindestens 15 Minuten. Bei jeder
  weiteren 429-Antwort verdoppelt sich die Pause, bis höchstens 6 Stunden.
  Einen `Retry-After`-Header berücksichtigt sie, geht aber nie unter 15
  Minuten.
- Ein 404 bedeutet, dass DHL die Nummer nicht kennt. Die Integration fragt
  dann nicht sofort erneut, sondern erst im regulären Intervall. Die Entities
  werden `unavailable`, und solange DHL die Nummer noch nie gefunden hat,
  erscheint ein Reparaturhinweis.
- Zähler und Zeitpunkt der letzten Abfrage überstehen Neustarts. Häufiges
  Neustarten umgeht das Tagesbudget also nicht. Die Sensorwerte sind nach
  einem Neustart sofort wieder da, ohne API-Aufruf.

Das Intervall stellst du unter *Konfigurieren → Abfrage-Einstellungen*
zwischen 5 Minuten und 24 Stunden ein. Sind mehrere Sendungen aktiv,
überschreibt das Fair-Share-Intervall kürzere Werte.

## Zugestellte Sendungen automatisch entfernen

*Konfigurieren → Abfrage-Einstellungen → "Zugestellte Sendungen entfernen nach"*

| Wert | Verhalten |
|---|---|
| `0` | Zugestellte Sendungen bleiben dauerhaft |
| `n` | Eine Sendung verschwindet, sobald ihre Zustellung `n` Tage zurückliegt |

Der Standard ist 3 Tage. Seit 0.4.0 räumt die Integration also von selbst auf.
Wer das nicht will, stellt den Wert auf `0`.

Das Aufräumen entfernt dasselbe wie `dhl_tracking.remove_shipment`, also den
gespeicherten Eintrag, die Entities und das Gerät, und feuert
`dhl_tracking_shipment_removed`. Sendungen ohne Zustell-Zeitstempel bleiben
stehen.

Wer eigene Regeln will, ruft die Aktion `dhl_tracking.remove_delivered_shipments`
in einer eigenen Automation auf.

## Die App zeigt andere Zeiten als Home Assistant

Die DHL-App und die offizielle Entwickler-API sind zwei verschiedene
Datenquellen. Die App kennt dich als angemeldeten Empfänger und fragt einen
internen Dienst. Die Tracking-API hat einen eigenen Stand, der hinterherhinken
kann.

Ein Fall, den ich nachgemessen habe: Die App zeigte ein Zustellfenster von
14:30 bis 16:00. Die API lieferte zur selben Zeit 13:20 bis 14:50, egal ob mit
oder ohne `recipientPostalCode`.

Das lässt sich mit einem Aufruf nachprüfen:

```bash
curl -s -H "DHL-API-Key: $KEY" \
  "https://api-eu.dhl.com/track/shipments?trackingNumber=$TN&language=de" \
| python3 -c "import json,sys; d=json.load(sys.stdin)['shipments'][0]; \
print(d.get('estimatedDeliveryTimeFrame'), d.get('estimatedTimeOfDelivery'))"
```

Kommt dort dasselbe heraus wie in Home Assistant, reicht die Integration die
Daten korrekt durch. Häufigeres Abfragen hilft dann nicht, es holt nur öfter
denselben Stand. Die API hat kein Feld, das ihr eigenes Alter verrät.
`status.timestamp` ist der Zeitpunkt des Ereignisses, nicht der letzten
Aktualisierung.

An die App-Daten käme man nur über einen inoffiziellen Endpunkt, und den
nutzt die Integration absichtlich nicht, siehe
[Datenschutz und Funktionsgrenzen](#datenschutz-und-funktionsgrenzen).

Ein abgelaufenes Fenster markiert die Integration als `delayed`, siehe
[Status "Verspätet"](#status-verspätet).

## Wann wurde zuletzt aktualisiert?

Der Sensor "Statuscode" hat die Abfragediagnose als Attribute:

```yaml
last_polled: "2026-09-23T12:40:11+00:00"   # letzter Abrufversuch
last_updated: "2026-09-23T12:40:11+00:00"  # letzter *erfolgreicher* Abruf
next_update: "2026-09-23T12:50:11+00:00"
poll_interval_minutes: 10.0
last_error: null                            # z. B. "not_found", "api_error"
rate_limit_backoff_until: null              # nur bei HTTP 429
```

Damit klärst du "warum steht da noch der alte Wert" ohne Debug-Logging:

| Beobachtung | Bedeutung |
|---|---|
| `poll_interval_minutes` ist 30 statt 10 | DHL liefert kein Zustellfenster, die Sendung gilt als normal unterwegs. Prüfbar am Attribut `time_frame_from`. |
| `last_polled` ist aktuell, `last_updated` alt | Der Abruf läuft, schlägt aber fehl. Siehe `last_error`. |
| `rate_limit_backoff_until` ist gesetzt | HTTP 429, die Integration pausiert bis dahin |
| `remaining_today` am API-Sensor ist 0 | Tagesbudget erschöpft |

Ist die Entität `unavailable`, blendet Home Assistant alle Attribute aus. Dann
hilft *Geräte & Dienste → DHL Tracking → ⋮ → Diagnose herunterladen*.

## Datenmodell und Persistenz

Jede Sendung ist so gespeichert:

```json
{
  "tracking_number": "00340434123456789012",
  "name": "Ersatzteil",
  "recipient_postal_code": "12345",
  "created_at": "2026-09-23T12:00:00+00:00"
}
```

Die Sendungen liegen in den Config-Entry-Options. Home Assistant empfiehlt,
alles, was der Benutzer konfiguriert, im Config Entry zu halten. Dann sichert
und restauriert Home Assistant die Daten mit dem Eintrag, der Options Flow
kann sie bearbeiten, der Update-Listener reagiert automatisch, und es gibt
keine zweite Datenquelle, die auseinanderlaufen könnte. Aktionen und Options
Flow schreiben deshalb beide über
`hass.config_entries.async_update_entry(entry, options=…)`.

Ein zusätzlicher `Store` in `.storage/dhl_tracking.<entry_id>` hält nur den
Laufzeitzustand, den niemand von Hand konfiguriert: Zeitpunkt der letzten
Abfrage je Sendung, verbrauchtes Tagesbudget, letzter Status und die letzte
API-Antwort. Dafür ist `Store` gedacht. Er sorgt auch dafür, dass ein Neustart
weder das Ratenlimit umgeht noch Statusereignisse doppelt auslöst.

## Migration bestehender Installationen

Bestehende Einträge migriert die Integration automatisch von Schema-Version 1
auf 2:

| vorher, Version 1 | nachher, Version 2 |
|---|---|
| `data.api_key` | `data.api_key`, unverändert |
| `data.tracking_numbers` als Liste oder als kommagetrennter String | `options.shipments` als Liste strukturierter Objekte |
| gab es nicht | `options.scan_interval`, `options.language`, `options.poll_delivered` |

- Die Migration trimmt die Nummern, wandelt sie in Großbuchstaben und
  entfernt Duplikate.
- Ungültige Fragmente wie einzelne Ziffern aus einem falsch zerlegten String
  fallen weg. Gültige Nummern gehen nicht verloren.
- Die Unique IDs der Entities, `dhl_tracking_<nummer>_<sensor>`, bleiben
  gleich. Entity-IDs, Verlaufsdaten und Automationen funktionieren weiter.

### Was sich für bestehende Nutzer ändert

- Die Sensoren gehören jetzt zu einem Gerät pro Sendung. Der angezeigte Name
  setzt sich aus Gerätename und Sensorname zusammen, die Entity-ID bleibt.
- "Rücksendung" liefert `yes`/`no` statt der fest deutschen Werte `Ja`/`Nein`,
  die Anzeige ist übersetzt. Templates, die auf `"Ja"` prüfen, müssen auf
  `"yes"` umgestellt werden.
- Zeitstempel-Sensoren liefern echte Datumswerte mit Zeitzone statt roher
  Zeichenketten.
- "Geplante Zustellung" und "Abholdatum" erfinden keine Uhrzeit mehr. Kennt
  DHL nur den Kalendertag, bleiben diese Zeitstempel leer, und die neuen
  Sensoren "Zustelltag" und "Abholtag" haben das Datum. Automationen, die mit
  `00:00` gerechnet haben, sollten auf den Datums-Sensor umsteigen.
- Die Debug-Attribute `api_path` und `raw_value` gibt es nicht mehr. Dafür hat
  jeder Konfigurationseintrag vollständige, redigierte Diagnosedaten.
- Das Standardintervall ist 30 statt 10 Minuten, siehe API-Limits.
- Seit 0.4.0 steht "Zugestellte Sendungen entfernen nach" auf 3 Tagen.
  Zugestellte Sendungen verschwinden also automatisch. Mit `0` schaltest du
  das ab.
- Seit 0.4.0 melden Sendungen im Zustellfahrzeug `out_for_delivery` statt
  `transit`. Dashboards, die auf `transit` filtern, sollten beide Werte
  berücksichtigen. Der rohe API-Wert steht im Attribut `status_code_api`.
- `time_frame_from` und `time_frame_through` haben seit 0.4.0 eine Zeitzone.
  Die unveränderten API-Strings stehen in `raw_time_frame_from` und
  `raw_time_frame_through`.

## Datenschutz und Funktionsgrenzen

Diese Dinge tut die Integration nicht, und das bleibt so:

- kein Login in ein privates "Post & DHL"-Konto
- kein Scraping der DHL-Webseite
- keine inoffiziellen Live-Tracking-Endpunkte
- keine Fahrzeugposition, keine "verbleibenden Stopps"
- keine Speicherung privater DHL-Zugangsdaten

Sie nutzt nur die offiziell dokumentierte Tracking-API mit einem
Entwickler-API-Schlüssel.

So geht sie mit Daten um:

- Der API-Schlüssel steht nur im Request-Header `DHL-API-Key`. Er erscheint
  nicht in Logs, Fehlermeldungen oder Ereignissen, und die Diagnosedaten
  redigieren ihn. Bei einer 401-Antwort liest die Integration den Body nicht,
  weil er Anfragedetails spiegeln könnte.
- Die Unique ID des Config Entry ist ein SHA-256-Fingerprint des Schlüssels,
  nicht der Schlüssel selbst.
- Ereignisse enthalten Sendungsnummer, Anzeigename, Status, DHLs
  Beschreibungstext und den Ort auf Stadtebene. Bei Packstation-Paketen nennt
  der Text die Adresse der Packstation. Empfängernamen enthalten sie nie.
- Standortangaben in Entity-Attributen sind auf Stadt und Land reduziert.
  Die Ausnahme ist der Abholort, weil man die Packstation sonst nicht findet.
- Die Diagnosedaten redigieren Empfänger, Absender, Zustellnachweise und
  Postleitzahlen.
- Die rohe API-Antwort liegt lokal im `Store` von Home Assistant, damit
  Neustarts kein Kontingent kosten. Sie verlässt das System nicht.

## Fehlerbehebung

| Symptom | Ursache und Abhilfe |
|---|---|
| Entities sind `unavailable`, Reparaturhinweis "DHL kennt die Sendung nicht" | DHL hat die Nummer noch nie gefunden. Meist ist es ein Tippfehler, ein Zeichen zu viel oder zu wenig. Frisch aufgegebene Sendungen erscheinen aber oft auch erst nach einigen Stunden. Der Hinweis verschwindet, sobald DHL die Sendung kennt. |
| "Die Prüfziffer stimmt nicht" beim Hinzufügen | 20-stellige Paketnummern wie `00340…` enthalten eine Prüfziffer. Die Nummer ist vertippt. |
| Reauth-Hinweis in der Oberfläche | DHL hat den API-Schlüssel abgelehnt. Neuen Schlüssel über den Reauth-Dialog eintragen. |
| Sensor "API-Anfragen heute" steht bei 200 | Das Tagesbudget ist erschöpft. Intervall verlängern oder zugestellte Sendungen entfernen. |
| Paket in Zustellung wird nicht häufiger abgefragt | DHL liefert für diese Sendung keine `estimatedTimeOfDelivery`. Ohne Prognose bleibt sie auf "unterwegs", nachprüfbar am Attribut `imminent_shipments`. |
| App zeigt andere Zustellzeiten als Home Assistant | Zwei verschiedene Datenquellen, siehe [oben](#die-app-zeigt-andere-zeiten-als-home-assistant) |
| Unvollständige Daten bei DHL-Paket in Deutschland | Empfänger-PLZ ergänzen. Für `parcel-de` liefert DHL den vollen Datensatz nur mit `recipientPostalCode`. |

Für Fehlerberichte lade bitte die Diagnosedaten des Eintrags herunter, unter
*Geräte & Dienste → DHL Tracking → ⋮ → Diagnose herunterladen*. Sie sind schon
redigiert.

Die Diagnosedaten enthalten auch `observed_status_codes`: jeden
`statusDetailed`-Code, den die Integration je gesehen hat, mit einem
Beispieltext und dem ersten und letzten Auftreten. Die Liste bleibt erhalten,
wenn die Sendung längst entfernt ist. Weil DHL diese Codes nicht dokumentiert,
ist das die Grundlage, um neue Fälle wie die Abgabe beim Nachbarn zu erkennen.
Die Beispieltexte stammen von DHL und können Ortsangaben enthalten, etwa die
Adresse einer Packstation.

## HACS-Standardstore

Die Integration wird als Custom Repository installiert, siehe oben. Dafür
braucht es keine HACS-Validierung.

Für den HACS-Standardstore fehlen vier Punkte. Keiner davon hat mit dem Code
zu tun, deshalb überspringt der CI-Workflow sie per `ignore:`.

| Prüfung | Was fehlt |
|---|---|
| `description` | Repository-Beschreibung in den GitHub-Einstellungen |
| `topics` | Mindestens ein Repository-Topic, z. B. `home-assistant`, `hacs`, `dhl` |
| `issues` | Issues müssen im Repository aktiviert sein |
| `brands` | Markenlogo, siehe unten |

Die `brands`-Prüfung sucht zuerst
`custom_components/dhl_tracking/brand/icon.png` und prüft dabei nur, ob die
Datei existiert. Sonst fragt sie `brands.home-assistant.io/domains.json` ab.
Unter den 4232 Custom-Domains dort fehlt `dhl_tracking` bisher.

Ein Beitrag an [home-assistant/brands](https://github.com/home-assistant/brands)
braucht `custom_integrations/dhl_tracking/icon.png` mit 256×256 px und
`icon@2x.png` mit 512×512 px, als PNG, am besten transparent. Custom
Integrations dürfen keine Home-Assistant-Markenbilder verwenden, und ein
nachgebautes DHL-Logo wäre ein Markenrechtsproblem. Ich erfinde hier deshalb
kein Logo.

## Entwicklung

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

Die Tests laufen nur gegen Mock-Antworten und Home Assistants
`aioclient_mock`. Die echte DHL-API rufen sie nie auf.

`scripts/dhl_cli.py` ist ein eigenständiges Skript, mit dem du eine
Sendungsnummer von Hand abfragen kannst. Es braucht `requirements.txt` und
gehört nicht zur Integration.

## Lizenz

Siehe [LICENSE](LICENSE).
