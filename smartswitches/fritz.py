#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2025 Christian Kvasny chris(at)ckvsoft.at
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#  THE SOFTWARE.
#
#  Project: [SEUSS -> Smart Ess Unit Spotmarket Switcher
#

from smartswitches.abstract_classes.smartswitch import SmartSwitch
import requests
import xml.etree.ElementTree as ET

class Fritz(SmartSwitch):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Aufteilen der IPs und AIN-Gruppen
        self.ips = self.ips.split("|") if "|" in self.ips else [self.ips]
        self.ain_groups = [group.split(",") for group in kwargs.get("ains", "").split("|")]

        # Filtert deaktivierte IPs und deren zugehörige AIN-Gruppen
        self.ips, self.ain_groups = self._filter_ips_and_ains(self.ips, self.ain_groups)

    def _filter_ips_and_ains(self, ips, ain_groups):
        """Filtert deaktivierte IPs und deren zugehörige AIN-Gruppen"""
        active_ips = []
        active_ain_groups = []

        for ip, ains in zip(ips, ain_groups):
            ip = ip.strip()
            if ip.startswith("!"):
                continue  # Überspringe deaktivierte IPs und deren AIN-Gruppen
            active_ips.append(ip)
            active_ain_groups.append(ains)  # AIN-Gruppen beibehalten, wenn die IP aktiv ist

        return active_ips, active_ain_groups

    def turn_on(self):
        """Schaltet alle AINs für jede FritzBox-IP ein"""
        self._send_request("setswitchon")

    def turn_off(self):
        """Schaltet alle AINs für jede FritzBox-IP aus"""
        self._send_request("setswitchoff")

    def _send_request(self, action):
        """Sendet HTTP-Requests für alle konfigurierten IPs und AINs"""
        for ip, ains in zip(self.ips, self.ain_groups):
            sid = self._get_sid(ip)
            if not sid:
                self.logger.log_debug(f"[{ip}] Error: No valid session ID received.")
                continue

            for ain in ains:
                url = f"http://{ip}/webservices/homeautoswitch.lua?sid={sid}&switchcmd={action}&ain={ain}"
                try:
                    response = requests.get(url, timeout=5)
                    response.raise_for_status()
                    self.logger.log_debug(f"[{ip} - AIN {ain}] Success: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    self.logger.log_debug(f"[{ip} - AIN {ain}] Error: {e}")

    def _get_sid(self, ip):
        """Holt eine Session-ID über Hash-Authentifizierung"""
        login_url = f"http://{ip}/login_sid.lua"
        try:
            response = requests.get(login_url, timeout=5)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            challenge = root.find("Challenge").text
            if not challenge:
                return None

            if self.user and self.password:
                hash_response = self._calculate_hash(challenge, self.password)
                sid_url = f"{login_url}?username={self.user}&response={hash_response}"
                sid_response = requests.get(sid_url, timeout=5)
                sid_response.raise_for_status()
                sid_root = ET.fromstring(sid_response.text)
                sid = sid_root.find("SID").text
                return sid if sid and sid != "0000000000000000" else None

            return None
        except requests.exceptions.RequestException as e:
            self.logger.log_debug(f"[{ip}] Error while retrieving the session ID: {e}")
            return None

    def _calculate_hash(self, challenge, password):
        """Berechnet den FritzBox-Login-Hash"""
        import hashlib
        response = f"{challenge}-{password}".encode("utf-16le")
        return f"{challenge}-{hashlib.md5(response).hexdigest()}"
