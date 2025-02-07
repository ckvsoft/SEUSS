from smartswitches.abstract_classes.smartswitch import SmartSwitch
import requests

class Shelly(SmartSwitch):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Filter out disabled IPs
        self.ips = self.ips.split("|")
        self._filter_disabled_ips()

    def turn_on(self):
        """ Schaltet das Shelly-Gerät oder mehrere Geräte ein """
        self._send_request("on")

    def turn_off(self):
        """ Schaltet das Shelly-Gerät oder mehrere Geräte aus """
        self._send_request("off")

    def _send_request(self, action):
        """ Sendet HTTP-Requests für alle konfigurierten IP-Adressen """
        for ip in self.ips:
            url = f"http://{ip}/relay/0?turn={action}"
            try:
                if self.user and self.password:
                    response = requests.get(url, auth=(self.user, self.password), timeout=5)
                else:
                    response = requests.get(url, timeout=5)  # Ohne Authentifizierung

                response.raise_for_status()

                self.logger.log_debug(f"[{ip}] Request successful: {response.status_code}")
            except requests.exceptions.RequestException as e:
                self.logger.log_debug(f"[{ip}] Error while sending the request: {e}")

