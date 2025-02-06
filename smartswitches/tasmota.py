from smartswitches.abstract_classes.smartswitch import SmartSwitch
import requests


class Tasmota(SmartSwitch):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Filter out disabled IPs
        self.ips = self.ips.split("|")
        self._filter_disabled_ips()

    def turn_on(self):
        """ Schaltet das Tasmota-Gerät oder mehrere Geräte ein """
        self._send_request("ON")

    def turn_off(self):
        """ Schaltet das Tasmota-Gerät oder mehrere Geräte aus """
        self._send_request("OFF")

    def _send_request(self, action):
        """ Sendet HTTP-Requests für alle konfigurierten IP-Adressen """
        for ip in self.ips:
            url = f"http://{ip}/cm?cmnd=Power%20{action}"
            try:
                if self.user and self.password:
                    response = requests.get(url, auth=(self.user, self.password), timeout=5)
                else:
                    response = requests.get(url, timeout=5)  # Ohne Authentifizierung

                response.raise_for_status()
                print(f"[{ip}] Request erfolgreich: {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"[{ip}] Fehler beim Senden der Anfrage: {e}")
