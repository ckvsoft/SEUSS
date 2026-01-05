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

from core.config import Config
from design_patterns.factory.generic_loader_factory import GenericLoaderFactory

class SmartSwitchesManager:
    def __init__(self):
        self.devices = []
        self.config = Config()
        self.load_devices(self.config.config_data.get("smart_switches", []))

    def load_devices(self, devices_config):
        for device_info in devices_config:
            if not device_info.get("enabled", True):
                continue  # Überspringt deaktivierte Geräte

            device = GenericLoaderFactory.create_loader("smartswitches", device_info)
            if device:
                self.devices.append(device)

    def turn_on_all(self):
        for device in self.devices:
            device.turn_on()

    def turn_off_all(self):
        for device in self.devices:
            device.turn_off()
