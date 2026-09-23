# Changelog

Alle nennenswerten Änderungen an dieser Integration.
Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [0.4.0] – 2026-09-23

### Hinzugefügt

- **Strukturierte Zustellmerkmale.** Die Sensoren **Statuscode** und **Produkt**
  tragen jetzt `services`, `signature_required`, `id_required`, `services_raw`
  sowie `cash_on_delivery_amount` und `currency`. Bevorzugt aus dem
  dokumentierten `details.valueAddedServices`; alles, was dessen Enum nicht
  abdeckt (Empfängerunterschrift, Ident-Check, Alterssichtprüfung, Wunschtag/
  -ort/-nachbar), wird case-insensitive aus dem Produkttext gelesen.
  Nicht erkannte Textfragmente bleiben unter `services_raw` erhalten.
- **Statuswert `out_for_delivery`** als sechste Option des Sensors
  **Statuscode**, abgeleitet aus dem strukturierten `estimatedDeliveryTimeFrame`.
  Der rohe API-Wert bleibt als Attribut `status_code_api` erhalten.
- **Übersichts-Sensoren** pro Konfigurationseintrag:
  `Offene Sendungen` (Anzahl + Attribut `shipments`) und
  `Nächste Zustellung` (device_class `timestamp`).
- **Event-Entität pro Sendung** (`event.<sendung>_sendungsstatus`) mit den
  Event-Typen `pre_transit`, `transit`, `out_for_delivery`, `delivered`,
  `failure`, `unknown`. Beim Start von Home Assistant wird nichts ausgelöst.
- **Zustelldetails nach Zustellung**: `delivered_to`, `delivery_location`
  (inkl. Packstation/Filiale), `delivered_at` und `proof_of_delivery_url`.
- **Attribut `name`** an allen Sendungssensoren – der reine Sendungsname ohne
  Entitäts-Suffix.
- **Option „Zugestellte Sendungen entfernen nach"** im Options-Flow
  (Standard 3 Tage, 0 = nie).
- Attribut `time_frame_remark` sowie `raw_time_frame_from` /
  `raw_time_frame_through`.

### Geändert

- `time_frame_from` und `time_frame_through` sind jetzt **zeitzonenbehaftete**
  ISO-Strings. DHL liefert sie ohne Offset; naive Werte werden in der in Home
  Assistant konfigurierten Zeitzone verankert. Die unveränderten API-Strings
  stehen weiterhin unter `raw_time_frame_from` / `raw_time_frame_through`.
- Das Bus-Event `dhl_tracking_status_changed` enthält zusätzlich `description`,
  `old_status_code_api` und `new_status_code_api`. `old_status_code` /
  `new_status_code` melden jetzt den abgeleiteten Wert, können also
  `out_for_delivery` enthalten.
- Sendungen in Zustellung werden mit der höchsten Priorität abgefragt.
- Die Attribute `shipments` und `events` werden nicht mehr in der Datenbank
  aufgezeichnet.

### Verhaltensänderung für bestehende Installationen

- Die neue Option **„Zugestellte Sendungen entfernen nach"** ist mit
  **3 Tagen** vorbelegt. Zugestellte Sendungen werden damit nach dem Update
  automatisch entfernt. Wer das nicht will, stellt den Wert unter
  *Konfigurieren → Abfrage-Einstellungen* auf `0`.
- Ein Dashboard, das auf `status_code == 'transit'` filtert, sieht Sendungen in
  Zustellung künftig als `out_for_delivery`.

## [0.3.0] – 2026-09-23

### Hinzugefügt

- Sensoren **Zustelltag** (`date`), **Zustellprognose** (Klartext von DHL) und
  **Abholtag** (`date`).
- Attribute `time_frame_from`, `time_frame_through`, `remark` und
  `raw_estimated_time_of_delivery` an den Zustell-Sensoren.
- Priorisierung: Pakete mit anstehender Zustellprognose werden dreimal so oft
  abgefragt wie normal unterwegs befindliche, angekündigte halb so oft.

### Behoben

- **Geplante Zustellung** und **Abholdatum** zeigten `00:00`, wenn DHL nur
  einen Kalendertag lieferte. Es wird keine Uhrzeit mehr erfunden; die
  Zeitstempel bleiben leer und die neuen Datums-Sensoren tragen den Tag.
- Das Abfragebudget wurde bei mehr Sendungen als Aufrufen überzogen.

## [0.2.0] – 2026-09-23

### Hinzugefügt

- Sendungen zur Laufzeit hinzufügen und entfernen – über die Aktionen
  `dhl_tracking.add_shipment`, `dhl_tracking.remove_shipment`,
  `dhl_tracking.remove_delivered_shipments` und über den Options-Flow.
- Ein Gerät pro Sendung, Ereignisse `dhl_tracking_shipment_added` /
  `_removed` / `_status_changed`, Reauth-Flow, redigierte Diagnosedaten,
  deutsche und englische Übersetzungen.

### Geändert

- Adaptives Polling mit hartem Tagesbudget statt fester zehn Minuten je
  Sendung, exponentielles Backoff bei HTTP 429.
- Blockierendes `requests` durch aiohttp ersetzt; `requests` und
  `python-dotenv` sind keine Abhängigkeiten der Integration mehr.
- Repository auf das Standard-Layout `custom_components/dhl_tracking/`
  umgestellt.

### Migration

- Schema-Version 1 → 2: `data.tracking_numbers` (Liste **oder**
  kommagetrennter String) wird nach `options.shipments` überführt. Unique IDs
  und damit Entity-IDs bleiben unverändert.
