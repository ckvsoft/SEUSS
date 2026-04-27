from smartswitches.abstract_classes.smartswitch import SmartSwitch
import requests


class Shelly(SmartSwitch):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Filter out disabled IPs
        self.ips = self.ips.split("|")
        self._filter_disabled_ips()

    def turn_on(self):
        """Switch the Shelly device or several devices on."""
        for ip in self.ips:
            self._send_one_request(ip, "on")

    def turn_off(self):
        """Switch the Shelly device or several devices off."""
        for ip in self.ips:
            self._send_one_request(ip, "off")

    def turn_on_ip(self, ip):
        """Switch a single Shelly IP on."""
        if ip in self.ips:
            self._send_one_request(ip, "on")
        else:
            self.logger.log.debug(
                f"[{ip}] not in active IP list for {self.name}, skipping turn_on_ip"
            )

    def turn_off_ip(self, ip):
        """Switch a single Shelly IP off."""
        if ip in self.ips:
            self._send_one_request(ip, "off")
        else:
            self.logger.log.debug(
                f"[{ip}] not in active IP list for {self.name}, skipping turn_off_ip"
            )

    def _send_one_request(self, ip, action):
        """Send a single HTTP request to one IP."""
        url = f"http://{ip}/relay/0?turn={action}"
        try:
            if self.user and self.password:
                response = requests.get(url, auth=(self.user, self.password), timeout=5)
            else:
                response = requests.get(url, timeout=5)

            response.raise_for_status()
            self.logger.log.debug(f"[{ip}] Request successful: {response.status_code}")
        except requests.exceptions.RequestException as e:
            self.logger.log.debug(f"[{ip}] Error while sending the request: {e}")
