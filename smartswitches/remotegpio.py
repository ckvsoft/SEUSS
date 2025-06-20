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
from requests.auth import HTTPBasicAuth

class Remotegpio(SmartSwitch):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # User/Pass optional, leer = keine Auth
        self.user = kwargs.get("user", "")
        self.password = kwargs.get("password", "")

        self.ips = self.ips.split("|") if "|" in self.ips else [self.ips]
        self.pin_groups = [grp.split(",") for grp in kwargs.get("pins", "").split("|")]

        self.ips, self.pin_groups = self._filter_ips_and_pins(self.ips, self.pin_groups)

    def _filter_ips_and_pins(self, ips, pin_groups):
        active_ips = []
        active_pin_groups = []
        for ip, pins in zip(ips, pin_groups):
            ip = ip.strip()
            if ip.startswith("!"):
                continue
            active_ips.append(ip)
            active_pin_groups.append([int(pin) for pin in pins if pin.isdigit()])
        return active_ips, active_pin_groups

    def turn_on(self):
        self._send_request("on")

    def turn_off(self):
        self._send_request("off")

    def _send_request(self, action):
        auth = None
        if self.user and self.password:
            auth = HTTPBasicAuth(self.user, self.password)
        for ip, pins in zip(self.ips, self.pin_groups):
            for pin in pins:
                url = f"http://{ip}/gpio/{pin}/{action}"
                try:
                    response = requests.post(url, auth=auth, timeout=5)
                    response.raise_for_status()
                    self.logger.log.debug(f"[{ip}] GPIO {pin} -> {action.upper()} OK")
                except requests.exceptions.RequestException as e:
                    self.logger.log.warning(f"[{ip}] GPIO {pin} -> {action.upper()} FAILED: {e}")
