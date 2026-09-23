import os

from dotenv import load_dotenv
import requests

# Lade Umgebungsvariablen aus .env Datei
load_dotenv()


class DHLTracker:
    """
    Eine Klasse zur Verfolgung von DHL-Sendungen über die DHL Tracking API.
    """

    def __init__(self, api_key=None):
        """
        Initialisiert den DHL Tracker mit einem API-Schlüssel.

        Args:
            api_key (str, optional): Der DHL API-Schlüssel.
                                   Falls nicht angegeben, wird DHL_API_KEY aus der .env Datei gelesen.
        """
        if api_key is None:
            api_key = os.getenv("DHL_API_KEY")
            if not api_key:
                raise ValueError(
                    "API-Key nicht gefunden. Bitte DHL_API_KEY in .env Datei setzen oder api_key Parameter übergeben."
                )

        self.api_key = api_key
        self.base_url = "https://api-eu.dhl.com/track"

    def track_shipment(self, tracking_number, service=None, language="de"):
        """
        Verfolgt eine Sendung anhand der Sendungsnummer.

        Args:
            tracking_number (str): Die Sendungsnummer
            service (str, optional): Der Service-Typ
            language (str): Die Sprache für die Antwort (Standard: "de")

        Returns:
            dict: Die API-Antwort mit den Sendungsinformationen

        Raises:
            requests.HTTPError: Bei API-Fehlern
        """
        url = f"{self.base_url}/shipments"
        headers = {"DHL-API-Key": self.api_key, "Accept": "application/json"}
        params = {"trackingNumber": tracking_number, "language": language}
        if service:
            params["service"] = service

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def print_shipment_info(self, shipment):
        """
        Gibt detaillierte Informationen über eine Sendung aus.

        Args:
            shipment (dict): Die Sendungsdaten aus der API-Antwort
        """
        print("=== DHL Sendungsverfolgung ===")
        print(f"Sendungsnummer: {shipment.get('id')}")
        print(
            f"Produkt: {shipment.get('details', {}).get('product', {}).get('productName', 'Unbekannt')}"
        )
        print(
            f"Anzahl Stücke: {shipment.get('details', {}).get('totalNumberOfPieces', 'Unbekannt')}"
        )
        print(
            f"Gewicht: {shipment.get('details', {}).get('weight', {}).get('value', 'Unbekannt')} {shipment.get('details', {}).get('weight', {}).get('unitText', '')}"
        )
        print(f"Rücksendung: {'Ja' if shipment.get('returnFlag') else 'Nein'}")
        print(f"Service: {shipment.get('service')}")
        print(
            f"Herkunft: {shipment.get('origin', {}).get('address', {}).get('countryCode', 'Unbekannt')}"
        )
        print(
            f"Ziel: {shipment.get('destination', {}).get('address', {}).get('countryCode', 'Unbekannt')}"
        )
        print(f"Tracking-Link: {shipment.get('serviceUrl', 'Kein Link verfügbar')}")
        print()

        self._print_current_status(shipment)
        self._print_shipment_history(shipment)

    def _print_current_status(self, shipment):
        """
        Gibt den aktuellen Status einer Sendung aus.

        Args:
            shipment (dict): Die Sendungsdaten
        """
        status = shipment.get("status", {})
        print("Aktueller Status:")
        print(f"  - {status.get('status', '')} ({status.get('statusCode', '')})")
        print(f"  - Zeitpunkt: {status.get('timestamp', '')}")
        print(f"  - Beschreibung: {status.get('description', '')}")
        print(f"  - Details: {status.get('remark', '')}")
        print()

    def _print_shipment_history(self, shipment):
        """
        Gibt den Verlauf einer Sendung aus.

        Args:
            shipment (dict): Die Sendungsdaten
        """
        print("=== Verlauf ===")
        for event in shipment.get("events", []):
            print(f"{event.get('timestamp', '-')}:")
            print(
                f"  Status: {event.get('status', '')} ({event.get('statusCode', '')})"
            )
            print(f"  Beschreibung: {event.get('description', '')}")
            if event.get("location", {}).get("address", {}).get("addressLocality"):
                print(f"  Ort: {event['location']['address']['addressLocality']}")
            print("---")

    def track_and_display(self, tracking_number, service=None, language="de"):
        """
        Verfolgt eine Sendung und zeigt alle Informationen an.

        Args:
            tracking_number (str): Die Sendungsnummer
            service (str, optional): Der Service-Typ
            language (str): Die Sprache für die Antwort (Standard: "de")
        """
        try:
            result = self.track_shipment(tracking_number, service, language)

            shipments = result.get("shipments", [])
            if not shipments:
                print("Keine Sendungsinformationen gefunden.")
                return

            for shipment in shipments:
                self.print_shipment_info(shipment)

        except requests.HTTPError as e:
            print(f"API-Fehler: {e}")
        except Exception as e:
            print(f"Fehler beim Abrufen der Sendungsinformationen: {e}")


def main():
    """
    Hauptfunktion zum Ausführen des DHL Trackers.
    """
    # DHL Tracker erstellen
    tracker = DHLTracker()

    # Beispiel: Trackingnummer verfolgen
    tracking_number = "00340434175969812466"
    tracker.track_and_display(tracking_number)


if __name__ == "__main__":
    main()
