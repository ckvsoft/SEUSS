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
        # DEPRECATED: replaced by skip_charge_when_battery_covers_expensive_phase
        "skip_charge_when_battery_sufficient": False,
        # DEPRECATED: never useful in practice, replaced
        "skip_charge_when_battery_covers_overnext": False,
        # New: abort charge when the battery covers the entire upcoming
        # expensive phase until the next charge cluster (any price).
        "skip_charge_when_battery_covers_expensive_phase": False,
        # New: skip the current charge attempt when a STRICTLY cheaper
        # future charge cluster exists AND the pack can bridge the gap
        # to it AND the pack + that cheaper cluster's recharge can
        # cover the following expensive phase without emptying.
        # Meant for the case: SEUSS is inside a cheap cluster (e.g.
        # 23 ct) but a much cheaper cluster is coming in a few hours
        # (e.g. 19 ct), with plenty of PV/SOC available right now.
        # Runs a full forward simulation across the shelter chain so
        # it only skips when the horizon plan is actually safe.
        "skip_charge_when_cheaper_cluster_coming": False,
        # New: skip charging the current quarter when at least one
        # upcoming quarter is priced below zero AND the battery will
        # have enough headroom to absorb it (current free Wh +
        # consumption until then >= chargeable Wh during the negative
        # window). Lets you avoid paying for charge now when you can
        # be paid for it shortly.
        "skip_charge_for_upcoming_negative_prices": False,
        # New: when battery is too small to cover the full expensive
        # phase, prioritise discharge to the most expensive blocks only;
        # cheaper expensive-phase hours fall back to grid.
        "smart_discharge_priority_to_expensive_hours": False,
        "delay_grid_charging_below_active_soc_limit": False,
        "stats_history_retention_days": 400,
        "solar_adj_ewma_alpha": 0.3,
        "solar_adj_min_theoretical_wh": 1000.0,
        "solar_adj_min_sun_hours": 4.0,
        "solar_adj_max_daily_change": 0.20,
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

        ],
        "solar_forecast_providers": [
            {
                "name": "OpenMeteo",
                "primary": True,
                "enabled": True
            },
            {
                "name": "Solcast",
                "primary": False,
                "enabled": False,
                "api_key": "",
                "resource_ids": "",
                "min_interval_minutes": 90
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
            self.solar_forecast_providers = []
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
            # Top-level boolean flags. Defaults are duplicated in
            # DEFAULT_CONFIG_TEMPLATE; the load_config loop reads them
            # from the actual config.json on startup.
            self.use_solar_forecast_to_abort = False
            self.skip_charge_when_battery_sufficient = False
            self.skip_charge_when_battery_covers_overnext = False
            self.skip_charge_when_battery_covers_expensive_phase = False
            self.skip_charge_when_cheaper_cluster_coming = False
            self.skip_charge_for_upcoming_negative_prices = False
            self.smart_discharge_priority_to_expensive_hours = False
            self.delay_grid_charging_below_active_soc_limit = False
            # Days of per-day history to retain (energy_costs_by_day,
            # consumption_wh_by_day, etc.). 400 covers a full year-over-
            # year comparison plus a month buffer. Set to 0 to disable
            # cleanup entirely. The actual cleanup runs in save_day()
            # right after the rotation, so old entries fall off one
            # midnight at a time without a noticeable spike.
            self.stats_history_retention_days = 400
            # Solar forecast adjustment-factor tunables. See README and
            # solar/openmeteo.py for what each does. These fields exist
            # so getattr() in openmeteo gets a value even if config.json
            # is older than this build (migration adds them on next save).
            self.solar_adj_ewma_alpha = 0.3
            self.solar_adj_min_theoretical_wh = 1000.0
            self.solar_adj_min_sun_hours = 4.0
            self.solar_adj_max_daily_change = 0.20
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

        # Top-level boolean flags -- read explicitly so getattr() in
        # downstream code returns the real value, not just the default
        # baked into _init. These are not part of the `prices` block.
        for attr, default in (
            ("use_solar_forecast_to_abort", False),
            ("skip_charge_when_battery_sufficient", False),
            ("skip_charge_when_battery_covers_overnext", False),
            ("skip_charge_when_battery_covers_expensive_phase", False),
            ("skip_charge_when_cheaper_cluster_coming", False),
            ("skip_charge_for_upcoming_negative_prices", False),
            ("smart_discharge_priority_to_expensive_hours", False),
            ("delay_grid_charging_below_active_soc_limit", False),
        ):
            raw = config_data.get(attr, default)
            # Accept both real bools and the string "off"/"on" that the
            # editor's hidden checkbox-pair scheme produces.
            if isinstance(raw, str):
                setattr(self, attr, raw.strip().lower() in ("on", "true", "1", "yes"))
            else:
                setattr(self, attr, bool(raw))

        # Solar adjustment-factor tunables -- top-level, with type-safe
        # fallback to the in-memory default if the config value is bogus.
        for attr, default in (
            ("solar_adj_ewma_alpha", 0.3),
            ("solar_adj_min_theoretical_wh", 1000.0),
            ("solar_adj_min_sun_hours", 4.0),
            ("solar_adj_max_daily_change", 0.20),
            ("stats_history_retention_days", 400),
        ):
            raw = config_data.get(attr, default)
            try:
                setattr(self, attr, float(raw))
            except (TypeError, ValueError):
                setattr(self, attr, default)
        # Clamp alpha to [0, 1] -- alpha=1 reproduces old behaviour,
        # alpha=0 freezes the factor entirely. Negative or >1 would
        # destabilise the EWMA so we silently snap them.
        self.solar_adj_ewma_alpha = max(0.0, min(1.0, self.solar_adj_ewma_alpha))

        self.markets = config_data.get("markets", [])
        self.failback_market = config_data.get("failback_market", "")

        self.ess_units = config_data.get("ess_unit", [])
        self.pv_panels = config_data.get("pv_panels", [])
        # New: list of forecast providers (OpenMeteo, Solcast, ...).
        # Empty/missing -> SolarForecastManager falls back to OpenMeteo
        # only (legacy behaviour).
        self.solar_forecast_providers = config_data.get("solar_forecast_providers", [])

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

        # Sanity warnings: if charge + discharge counts together leave
        # a big chunk of the day unassigned, the price chart will show
        # grey hours and there is a good chance the user just typo'd
        # the config (e.g. 4 instead of 8 for charging). Log it once
        # at startup so it's findable -- not an error, just a hint.
        try:
            from core.log import CustomLogger
            log = CustomLogger().log
            charge_count = int(getattr(self, "number_of_lowest_prices_for_charging", 0) or 0)
            discharge_count = int(getattr(self, "number_of_highest_prices_for_discharging", 0) or 0)
            assigned = charge_count + discharge_count
            if assigned > 0 and assigned < 24:
                log.warning(
                    f"Config: number_of_lowest_prices_for_charging "
                    f"({charge_count}) + number_of_highest_prices_for_discharging "
                    f"({discharge_count}) = {assigned} hours. "
                    f"{24 - assigned} hour(s) per day stay unassigned and will "
                    f"appear grey in the price chart. If you wanted full "
                    f"coverage, increase one of the two counts."
                )
            elif assigned > 24:
                log.warning(
                    f"Config: number_of_lowest_prices_for_charging "
                    f"({charge_count}) + number_of_highest_prices_for_discharging "
                    f"({discharge_count}) = {assigned} hours, exceeding the "
                    f"24-hour day. Charging takes precedence over discharging "
                    f"on overlap, but you may not see all expected discharge "
                    f"hours."
                )
        except Exception:
            # Defensive: never let validation break startup.
            pass

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
