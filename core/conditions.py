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

from core.config import Config
from core.statsmanager import StatsManager
from core.log import CustomLogger
from core.timeutilities import TimeUtilities
from core.utils import Utils
from spotmarket.abstract_classes.item import Item
from datetime import datetime, timedelta, timezone


class ConditionResult:
    def __init__(self):
        self.execute = False
        self.condition = ""


class Conditions:
    def __init__(self, itemlist, essunit):
        self.items = itemlist
        self.essunit = essunit
        self.config = Config()
        self.logger = CustomLogger()
        self.statsmanager = StatsManager()
        self.available_surplus = 0.0
        self.current_price = itemlist.get_current_price()
        self.charging_price_limit = Utils.convert_to_millicents(self.config.charging_price_limit)
        self.charging_price_hard_cap = Utils.convert_to_millicents(self.config.charging_price_hard_cap)
        self.available_operation_modes = ["switching", "charging", "discharging"]
        self.conditions_by_operation_mode = {mode: {} for mode in self.available_operation_modes}
        self.abort_conditions_by_operation_mode = {mode + "_abort": {} for mode in self.available_operation_modes}
        self.switching_descriptions = ""
        self.charging_descriptions = ""
        self.discharge_descriptions = ""
        self.add_additional_charging_conditions()
        self.add_additional_discharging_conditions()
        self.add_abort_conditions()

    def info(self):
        self.logger.log.info(f"Current price: {self.items.get_current_price(True)} Cent/kWh")
        avg_today, avg_tomorrow = self.items.get_average_price_by_date(True)
        self.logger.log.info(f"Average price Today: {avg_today} Cent/kWh")
        if avg_tomorrow:
            self.logger.log.info(f"Average price Tomorrow: {avg_tomorrow} Cent/kWh")

        lowest_prices = self.items.get_lowest_prices(self.config.number_of_lowest_prices_for_charging)
        if lowest_prices:
            self.logger.log.info("Today's lowest prices for charging:")
            for item in lowest_prices:
                self.logger.log.info(f"Time: {item.get_start_datetime(True)}, Price: {item.get_price(True)} Cent/kWh")

        highest_prices = self.items.get_highest_prices(self.config.number_of_highest_prices_for_discharging)
        if highest_prices:
            self.logger.log.info("Today's highest prices for discharging:")
            for item in highest_prices:
                self.logger.log.info(f"Time: {item.get_start_datetime(True)}, Price: {item.get_price(True)} Cent/kWh")

        # Aktueller SOC
        soc_wh = self.essunit.get_battery_current_wh()
        min_soc_wh = self.essunit.get_battery_min_wh()
        self.logger.log.info(f"Current SOC: {soc_wh / 1000:.2f} kWh, Min SOC: {min_soc_wh / 1000:.2f} kWh")

    @staticmethod
    def create_condition(description, condition_function):
        return {"condition": condition_function, "description": description}

    def create_condition_function(self, threshold, comparison_operator):
        return lambda: comparison_operator(threshold, self.current_price)

    def add_additional_charging_conditions(self):
        self.conditions_by_operation_mode["charging"].update({
            f"charging_price_limit ({Utils.millicent_to_cent(self.charging_price_limit)}) > {Utils.millicent_to_cent(self.current_price)}":
                self.create_condition_function(self.charging_price_limit, lambda x, y: x > y)
        })

        lowest_prices = self.items.get_lowest_prices(self.config.number_of_lowest_prices_for_charging)
        for i, item in enumerate(lowest_prices):
            price = item.get_price(False)
            start_time = item.get_start_datetime(True)
            key = f"lowestprice_{i+1} {start_time} ({item.get_price()} Cent/kWh) == {Utils.millicent_to_cent(self.current_price)} Cent/kWh"
            func = self.create_condition_function(price, lambda x, y: x == y)
            self.conditions_by_operation_mode["charging"][key] = func
            self.conditions_by_operation_mode["switching"][key] = func

    def add_additional_discharging_conditions(self):
        highest_prices = self.items.get_highest_prices(self.config.number_of_highest_prices_for_discharging)
        for i, item in enumerate(highest_prices):
            price = item.get_price(False)
            start_time = item.get_start_datetime(True)
            key = f"highestprice_{i+1} {start_time} ({item.get_price()} Cent/kWh) == {Utils.millicent_to_cent(self.current_price)} Cent/kWh"
            func = self.create_condition_function(price, lambda x, y: x == y)
            self.conditions_by_operation_mode["discharging"][key] = func

        future_high_prices = self.items.get_future_high_prices_until_next_low(highest_prices)
        current_soc, min_soc, required_capacity = self._calculate_available_surplus(future_high_prices)

        self.conditions_by_operation_mode["discharging"].update({
            f"Discharge allowed: {self.available_surplus/1000:.2f} kWh surplus (SOC: {current_soc/1000:.2f} kWh, Expensive hours: {len(future_high_prices)}, Req. Capacity: {required_capacity/1000:.2f} kWh)":
                lambda: self._calculate_discharge_conditions(future_high_prices)
        })

    def add_abort_conditions(self):
        available_soc_wh = self.essunit.get_battery_current_wh() - self.essunit.get_battery_min_wh()
        self.abort_conditions_by_operation_mode["charging_abort"].update({
            "Abort charge condition - Price exceeds hard cap": lambda: self.current_price > self.charging_price_hard_cap
        })
        self.abort_conditions_by_operation_mode["discharging_abort"].update({
            "Abort discharge while charging is allowed": lambda: any(c() for c in self.conditions_by_operation_mode.get("charging", {}).values())
        })

    def evaluate_conditions(self, condition_result, operation_mode):
        if operation_mode not in self.available_operation_modes:
            self.logger.log.error(f"Invalid operation mode: {operation_mode}")
            return

        matched = False
        for key, func in self.conditions_by_operation_mode.get(operation_mode, {}).items():
            try:
                result = func()
                self.logger.log.debug(f"Evaluating condition: {key} - Result: {result}")
                if result and not condition_result.condition:
                    condition_result.execute = True
                    condition_result.condition = key
                    matched = True
                    if self.config.log_level != "DEBUG":
                        break
            except Exception as e:
                self.logger.log.error(f"Error evaluating condition {key}: {e}")

        if not matched:
            self.logger.log.debug("No conditions matched. Skipping abort conditions.")
            return

        for key, func in self.abort_conditions_by_operation_mode.get(operation_mode+"_abort", {}).items():
            try:
                if func():
                    condition_result.execute = False
                    condition_result.condition = key
                    break
            except Exception as e:
                self.logger.log.error(f"Error evaluating abort condition {key}: {e}")

    def _calculate_required_capacity(self, upcoming_hours):
        avg_list = self.statsmanager.get_data("powerconsumption", "hourly_watt_average")
        avg_consumption = round(avg_list[0], 2) if avg_list else 0
        required_capacity = upcoming_hours * avg_consumption * 1.10
        self.logger.log.debug(f"Required capacity: {required_capacity:.2f} Wh")
        return required_capacity

    def _calculate_available_surplus(self, upcoming_high_prices):
        current_soc = self.essunit.get_battery_current_wh()
        min_soc = self.essunit.get_battery_min_wh()
        required_capacity = self._calculate_required_capacity(len(upcoming_high_prices))
        buffer = 0.10 * current_soc
        self.available_surplus = max(0, current_soc - min_soc - buffer - required_capacity)
        self.logger.log.debug(f"Available surplus: {self.available_surplus:.2f} Wh")
        return current_soc, min_soc, required_capacity

    def _calculate_discharge_conditions(self, upcoming_high_prices):
        current_soc, min_soc, required_capacity = self._calculate_available_surplus(upcoming_high_prices)
        if upcoming_high_prices:
            max_dischargeable = current_soc - (required_capacity + min_soc)
            if max_dischargeable < 0:
                return False
            return min(self.available_surplus, max_dischargeable) > 0
        return self.available_surplus > 0
