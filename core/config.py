#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2025 Christian Kvasny chris(at)ckvsoft.at
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
import json

from design_patterns.singleton import Singleton
from design_patterns.observer.config_observer import ConfigObserver


class Info:
    def __init__(self, required_fields, **kwargs):
        if not required_fields.issubset(kwargs):
            raise ValueError(f"Missing required fields. Required: {required_fields}")

        self.name = kwargs["name"]
        self.enabled = kwargs["enabled"]

        for key, value in kwargs.items():
            setattr(self, key, value)


class Config(Singleton):
    DEFAULT_CONFIG_TEMPLATE = {
        "time_zone": "Europe/Vienna",
        "tariff_resolution": "hourly",
        "log_file_path": "/tmp/seuss.log",
        "log_level": "INFO",
        "use_solar_forecast_to_abort": False,
        "delay_grid_charging_below_active_soc_limit": False,
        "prices": [
            {
                "use_second_day": False,
                "number_of_lowest_prices_for_charging": 0,
                "number_of_highest_prices_for_discharging": 0,
                "number_of_lowest_prices_for_switching": 0,
                "charging_block_minutes": 60,
                "discharging_block_minutes": 60,
                "switching_block_minutes": 60,
                "fill_gaps_with_short_clusters": True,
                "charging_price_limit": -999,
                "charging_price_hard_cap": 999
            }
        ],
        "pv_panels": [
            {
                "name": "Panels 1",
                "locLat": "-78.26509",
                "locLong": "158.32421",
                "angle": 0,
                "direction": -90,
                "totPower": 1.6,
                "total_area": 0,
                "efficiency": 20,
                "damping_morning": 0,
                "damping_evening": 0,
                "enabled": False
            },
            {
                "name": "Panels 2",
                "locLat": "-78.26509",
                "locLong": "158.32421",
                "angle": 0,
                "direction": 0,
                "totPower": 1.6,
                "total_area": 0,
                "efficiency": 20,
                "damping_morning": 0,
                "damping_evening": 0,
                "enabled": False
            },
            {
                "name": "Panels 3",
                "locLat": "-78.26509",
                "locLong": "158.32421",
                "angle": 0,
                "direction": 90,
                "totPower": 1.6,
                "total_area": 0,
                "efficiency": 20,
                "damping_morning": 0,
                "damping_evening": 0,
                "enabled": False
            }
        ],
        "ess_unit": [
            {
                "name": "Victron",
                "use_vrm": False,
                "unit_id": "",
                "ip_address": "venus.local",
                "user": "",
                "password": "",
                "max_discharge_power": -1,
                "only_observation": False,
                "enabled": False
            }
        ],
        "markets": [
            {
                "name": "Awattar",
                "country": "AT",
                "fee": "3% + 1.5",
                "primary": True,
                "enabled": True
            },
            {
                "name": "Entsoe",
                "api_token": "enter_your_entsoe_apikey_here",
                "in_domain": "10YAT-APG------L",
                "out_domain": "10YAT-APG------L",
                "fee": "",
                "primary": False,
                "enabled": False
            },
            {
                "name": "Tibber",
                "api_token": "enter_your_tibber_apikey_here",
                "price_unit": "energy",
                "fee": "",
                "primary": False,
                "enabled": False
            }
        ],
        "smart_switches": [
            {
                "name": "Shelly",
                "ips": "10.1.1.20 | 10.1.1.21",
                "lowest_prices_per_ip": "",
                "block_minutes_per_ip": "",
                "user": "",
                "password": "",
                "enabled": False
            },
            {
                "name": "Tasmota",
                "ips": "10.1.1.30",
                "lowest_prices_per_ip": "",
                "block_minutes_per_ip": "",
                "user": "admin",
                "password": "YWRtaW4",
                "enabled": False
            },
            {
                "name": "Fritz",
                "ips": "192.168.178.1 | 10.1.1.23",
                "ains": "1234,3443,2333 | 1234,4456,7866,3421",
                "lowest_prices_per_ip": "",
                "block_minutes_per_ip": "",
                "user": "admin",
                "password": "YWRtaW4",
                "enabled": False
            },
            {
                "name": "RemoteGPIO",
                "ips": "192.168.1.10 | 192.168.1.11 | !192.168.1.12",
                "pins": "17,18 | 21 | 20",
                "lowest_prices_per_ip": "",
                "block_minutes_per_ip": "",
                "user": "",
                "password": "",
                "enabled": False
            }

        ]
    }

    def _init(self):
        if not self._initialized:
            main_script_path = os.path.abspath(sys.argv[0])
            main_script_directory = os.path.dirname(main_script_path)
            self.config_file = os.path.join(main_script_directory, 'config.json')
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
            self.number_of_lowest_prices_for_switching = 0
            self.charging_block_minutes = 60
            self.discharging_block_minutes = 60
            self.switching_block_minutes = 60
            self.fill_gaps_with_short_clusters = True
            self.charging_price_limit = -999
            self.charging_price_hard_cap = float('inf')
            self.converter_efficiency = 1.0
            self.time_zone = "Europe/Vienna"
            self.use_second_day = False
            self.tariff_resolution = "hourly"
            self.load_config()
            self.update_config_with_template()

            self._initialized = True

    def find_failback_market(self):
        for market in self.markets:
            if not market["primary"] and market["enabled"]:
                return market
        return None

    def find_ess_unit(self):
        for ess_unit in self.ess_units:
            if ess_unit["enabled"]:
                return ess_unit
        return None

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as file:
                config_data = json.load(file)
        else:
            config_data = self.DEFAULT_CONFIG_TEMPLATE
            self.save_config(config_data)

        self.config_data = config_data
        self.log_file_path = config_data.get("log_file_path", "")
        self.log_level = config_data.get("log_level", "INFO")

        # tariff_resolution lives at top level (it's a market-level
        # property, not a price-strategy one). Read it directly. For
        # backward compatibility with fix13/13b configs that wrote it
        # into the `prices` block, the per-price loop below will pick
        # it up too -- the last value wins, which means a top-level
        # value gets overridden by a stale prices-block value if both
        # exist. To avoid that, we re-apply the top-level value AFTER
        # the prices loop further down.
        top_level_tariff_resolution = config_data.get("tariff_resolution")

        if not os.path.exists(self.log_file_path):
            # touch
            with open(self.log_file_path, 'w'):
                pass

        for item in config_data.get("prices", []):
            for key, value in item.items():
                setattr(self, key, value)

        # Top-level tariff_resolution wins over any stale value still
        # sitting inside the prices block (from older configs).
        if top_level_tariff_resolution is not None:
            self.tariff_resolution = top_level_tariff_resolution

        self.markets = config_data.get("markets", [])
        self.failback_market = config_data.get("failback_market", "")

        self.ess_units = config_data.get("ess_unit", [])
        self.pv_panels = config_data.get("pv_panels", [])

        self.essunit = self.find_ess_unit()

        if not self.failback_market:
            self.failback_market = self.find_failback_market()

        # Normalize block-minute settings: snap to multiples of 15min,
        # minimum 15. We allow arbitrarily long blocks (no upper cap) --
        # if the user wants to charge for 10 hours straight, that's their
        # call.
        for attr in ("charging_block_minutes",
                     "discharging_block_minutes",
                     "switching_block_minutes"):
            value = getattr(self, attr, 60)
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 60
            # Round to nearest 15min, minimum 15
            if value < 15:
                value = 15
            else:
                value = max(15, ((value + 7) // 15) * 15)
            setattr(self, attr, value)

        # Normalize tariff_resolution: only "hourly" or "quarterly" are
        # valid. Anything else falls back to "hourly" -- which matches
        # the typical Austrian retail contract (Awattar, Tibber default
        # tariff) where billing is per-hour even when the spot data is
        # quarter-hour. "quarterly" is for the rare 15-minute tariffs.
        tr = getattr(self, "tariff_resolution", "hourly")
        if isinstance(tr, str):
            tr = tr.strip().lower()
        if tr not in ("hourly", "quarterly"):
            tr = "hourly"
        self.tariff_resolution = tr

        self._set_os_timezone()

    def get_market_info(self, market_name):
        for market in self.markets:
            if market["name"] == market_name:
                return market
        return {}

    def get_essunit_info(self, unit_name):
        for essunit in self.ess_units:
            if essunit["name"] == unit_name:
                return essunit
        return {}

    @staticmethod
    def get_unit_id(config):
        for unit in config['ess_unit']:
            if unit.get('enabled', False) and 'unit_id' in unit:
                return unit['unit_id']
        return 0

    def get_pv_panels(self):
        return [panel for panel in self.pv_panels if panel["enabled"]]

    def update_config_with_template(self):
        # Migration: tariff_resolution moved from prices block to top
        # level in fix14. If an old config has it inside prices, copy
        # the value up (if top level is missing) and drop it from prices.
        prices_block = self.config_data.get("prices", [])
        if isinstance(prices_block, list):
            for price_item in prices_block:
                if isinstance(price_item, dict) and "tariff_resolution" in price_item:
                    legacy_value = price_item.pop("tariff_resolution")
                    if "tariff_resolution" not in self.config_data:
                        self.config_data["tariff_resolution"] = legacy_value

        # Check and add missing keys and sections from the template
        for key, value in self.DEFAULT_CONFIG_TEMPLATE.items():
            if key not in self.config_data:
                self.config_data[key] = value
            elif isinstance(value, list) and isinstance(self.config_data[key], list):
                for item_template in value:
                    if "name" in item_template:
                        template_name = item_template["name"]
                        for sub_item in self.config_data[key]:
                            if "name" in sub_item and sub_item["name"] == template_name:
                                for item_key, item_value in item_template.items():
                                    if item_key != "name" and item_key not in sub_item:
                                        sub_item[item_key] = item_value
                        if not any(sub_item.get("name") == template_name for sub_item in self.config_data[key]):
                            self.config_data[key].append(item_template)
                    else:
                        for sub_item in self.config_data[key]:
                            for item_key, item_value in item_template.items():
                                if item_key not in sub_item:
                                    sub_item[item_key] = item_value

        self.move_key_to_end(self.config_data['markets'], 'primary')

        self.move_key_to_end(self.config_data['pv_panels'], 'enabled')
        self.move_key_to_end(self.config_data['ess_unit'], 'enabled')
        self.move_key_to_end(self.config_data['markets'], 'enabled')

        self.save_config(self.config_data)

    def move_key_to_end(self, data, key):
        if isinstance(data, list):
            for item in data:
                if key in item:
                    value = item.pop(key)
                    item[key] = value

    def save_config(self, config_data):
        with open(self.config_file, 'w') as file:
            json.dump(config_data, file, indent=4)

        self.observer.notify_observers(config_data=config_data)

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
