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

from core.log import CustomLogger

class SmartSwitch:
    def __init__(self, **kwargs) -> None:
        self.logger = CustomLogger()
        self.name = kwargs.get("name", "")
        self.ips = kwargs.get("ips", "")
        self.user = kwargs.get("user", "")
        self.password = kwargs.get("password", "")
        self.enabled = kwargs.get("enable", "")
        # Filter out disabled IPs
        self.active_ips = [ip.strip() for ip in self.ips.split("|") if not ip.startswith("!")]


    def turn_on(self):
        pass

    def turn_off(self):
        pass

    def _filter_disabled_ips(self):
        """Filtert deaktivierte IPs, die mit '!' markiert sind"""
        active_ips = []

        for ip in self.ips:
            ip = ip.strip()  # Entfernt unnötige Leerzeichen
            if ip and not ip.startswith("!"):  # Wenn die IP nicht deaktiviert ist und nicht leer ist
                active_ips.append(ip)  # Füge sie zur Liste der aktiven IPs hinzu

        # Aktualisiere die Instanz-Variable mit der Liste der aktiven IPs
        self.ips = active_ips
