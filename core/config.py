#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024 Christian Kvasny chris(at)ckvsoft.at
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

import os
import sys
import toml

from design_patterns.singleton import Singleton
from design_patterns.observer.config_observer import ConfigObserver

DEFAULT_CONFIG_TEMPLATE = f"""
time_zone = "Europe/Vienna"
log_file_path = "/tmp/seuss.log"
log_level = "INFO"
# failback_market = ""

[[prices]]
use_second_day = false
number_of_lowest_prices_for_charging = 0
number_of_highest_prices_for_discharging = 0
charging_price_limit = -999

[[pv_panels]]
name = "Panels 1"
locLat = "-78.26509" # Latitude
locLong = "158.32421"  # Longitude
angle = 0          # Angle of your panels 0 (horizontal) … 90 (vertical)
direction = -90     # Plane azimuth, -180 … 180 (-180 = north, -90 = east, 0 = south, 90 = west, 180 = north)
totPower = 1.6      # installed modules power in kilo watt
enabled = false

[[pv_panels]]
name = "Panels 2"
locLat = "-78.26509" # Latitude
locLong = "158.32421"  # Longitude
angle = 0          # Angle of your panels 0 (horizontal) … 90 (vertical)
direction = 0       # Plane azimuth, -180 … 180 (-180 = north, -90 = east, 0 = south, 90 = west, 180 = north)
totPower = 1.6      # installed modules power in kilo watt
enabled = false

[[pv_panels]]
name = "Panels 3"
locLat = "-78.26509" # Latitude
locLong = "158.32421"  # Longitude
angle = 0          # Angle of your panels 0 (horizontal) … 90 (vertical)
direction = 90      # Plane azimuth, -180 … 180 (-180 = north, -90 = east, 0 = south, 90 = west, 180 = north)
totPower = 1.6      # installed modules power in kilo watt
enabled = false

[[ess_unit]]
name = "Victron"
use_vrm = false
unit_id = ""
ip_address = "venus.local"
user = ""
password = ""
max_discharge_power = "-1"
enabled = false

[[markets]]  # Kommentar für markets
name = "Awattar"
country = "AT"
primary = true
enabled = true

[[markets]]
name = "Entsoe"
api_token = "enter_your_entsoe_apikey_here"
in_domain = "10YAT-APG------L"  # Default is AT
out_domain = "10YAT-APG------L" # Default is AT
primary = false
enabled = false

[[markets]]
name = "Tibber"
api_token = "enter_your_tibber_apikey_here"
price_unit = "energy"
primary = false
enabled = false

"""


class Info:

    def __init__(self, required_fields, **kwargs):
        if not required_fields.issubset(kwargs):
            raise ValueError(f"Missing required fields. Required: {required_fields}")

        self.name = kwargs["name"]
        self.enabled = kwargs["enabled"]

        for key, value in kwargs.items():
            setattr(self, key, value)


class Config(Singleton):
    DEFAULT_CONFIG_TEMPLATE = toml.loads(DEFAULT_CONFIG_TEMPLATE)
    EXPECTED_KEYS = set(DEFAULT_CONFIG_TEMPLATE.keys())

    def _init(self):
        if not self._initialized:
            main_script_path = os.path.abspath(sys.argv[0])
            main_script_directory = os.path.dirname(main_script_path)
            self.config_file = os.path.join(main_script_directory, 'config.toml')
            self.observer = ConfigObserver()

            self.log_file_path = ""
            self.log_level = "INFO"
            self.failback_market = ""
            self.config_data = {}
            self.markets = []
            self.pv_panels = []
            self.ess_units = []
            self.essunit = None
            self.number_of_lowest_prices_for_charging = 0
            self.number_of_highest_prices_for_discharging = 0
            self.charging_price_limit = -999
            self.time_zone = "Europe/Vienna"
            self.use_second_day = False
            self.load_config()

            self._initialized = True

    def find_failback_market(self):
        for market in self.markets:
            if not market.primary and market.enabled:
                return market
        return None

    def find_ess_unit(self):
        for ess_unit in self.ess_units:
            if ess_unit.enabled:
                return ess_unit.__dict__
        return None

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as file:
                config_data = toml.load(file)

            self.update_config_with_template(config_data)
        else:
            config_data = self.DEFAULT_CONFIG_TEMPLATE
            self.save_config(config_data)

        self.config_data = config_data
        self.log_file_path = config_data.get("log_file_path", "")
        self.log_level = config_data.get("log_level", "INFO")

        if not os.path.exists(self.log_file_path):
            # touch
            with open(self.log_file_path, 'w') as file:
                pass

        prices_dict = config_data.get("prices", [{}])[0]
        for key, value in prices_dict.items():
            setattr(self, key, value)

        required_market_fields = {"name", "primary", "enabled"}
        self.markets = [Info(required_market_fields, **market) for market in config_data.get("markets", [])]
        self.failback_market = config_data.get("failback_market", "")

        required_essunit_fields = {"name", "enabled"}
        self.ess_units = [Info(required_essunit_fields, **essunit) for essunit in config_data.get("ess_unit", [])]

        required_pvpanels_fields = {"name", "enabled"}
        self.pv_panels = [Info(required_pvpanels_fields, **pvpanel) for pvpanel in config_data.get("pv_panels", [])]

        self.essunit = self.find_ess_unit()

        if len(self.failback_market) == 0:
            self.failback_market = self.find_failback_market()

        self._set_os_timezone()

    def get_market_info(self, market_name):
        for market in self.markets:
            if market.name == market_name:
                return market.__dict__
        return {}

    def get_essunit_info(self, unit_name):
        for essunit in self.ess_units:
            if essunit.name == unit_name:
                return essunit.__dict__
        return {}

    def get_pv_panels(self):
        return [panel for panel in self.pv_panels if panel.enabled]

    def update_config_with_template(self, config_data):
        missing_keys = [key for key in self.EXPECTED_KEYS if key not in config_data]

        if missing_keys:
            for key in missing_keys:
                config_data[key] = self.DEFAULT_CONFIG_TEMPLATE[key]

            self.save_config(config_data)

    def save_config(self, config_data):
        self.observer.notify_observers(config_data=config_data)
        with open(self.config_file, 'w') as file:
            # Kommentare aus der ursprünglichen Vorlage extrahieren
            comments = toml.dumps(self.DEFAULT_CONFIG_TEMPLATE).splitlines()
            for line in comments:
                if line.strip().startswith("#"):
                    file.write(line + "\n")

            # Aktuelle Konfiguration speichern
            toml.dump(config_data, file)

    def _set_os_timezone(self):
        uid = os.getuid()
        if uid > 0:
            return
        timezone = self.time_zone
        target = f'/usr/share/zoneinfo/{timezone}'
        link = f'/etc/localtime'
        if os.path.islink(link) and os.path.isfile(target):
            current_target = os.readlink(link)
            current_timezone = os.path.relpath(current_target, '/usr/share/zoneinfo')
            if current_timezone != timezone:
                try:
                    os.remove(link)
                    os.symlink(target, link)
                except OSError as e:
                    print(f"localtime NOT set to: {timezone}, error {e}")

    @staticmethod
    def find_venus_unique_id():
        try:
            with open('/data/conf/settings.xml', 'r') as file:
                for line in file:
                    if 'unique-id="' in line:
                        start_index = line.find('unique-id="') + len('unique-id="')
                        end_index = line.find('"', start_index)
                        unique_id = line[start_index:end_index]
                        return unique_id
        except FileNotFoundError:
            return None
