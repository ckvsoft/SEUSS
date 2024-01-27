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

from core.config import Config
from core.log import CustomLogger
from spotmarket.abstract_classes.item import Item


class ConditionResult:
    def __init__(self):
        self.execute = False
        self.condition = ""

class Conditions:
    def __init__(self, itemlist):
        self.items = itemlist
        self.config = Config()
        self.logger = CustomLogger()
        self.current_price = itemlist.get_current_price()
        self.charging_price_limit = Item.convert_to_millicents(self.config.charging_price_limit)
        self.available_operation_modes = ["charging", "discharging"]
        self.conditions_by_operation_mode = {mode: {} for mode in self.available_operation_modes}
        self.charging_conditions = {}
        self.discharge_conditions = {}
        self.charging_descriptions = ""
        self.discharge_descriptions = ""
        self.add_additional_charging_conditions()
        self.add_additional_discharging_conditions()


    def info(self):
        self.logger.log_info(f"Current price: {self.items.get_current_price(True)} Cent/kWh")
        self.logger.log_info(f"Average price: {self.items.get_average_price(True)} Cent/kWh")

        result = self.items.get_lowest_prices(self.config.number_of_lowest_prices_for_charging)
        if result:
            lowest_prices_count = self.config.number_of_lowest_prices_for_charging
            if isinstance(lowest_prices_count, float):
                formatted_price = f"{lowest_prices_count * 100}%"
            else:
                formatted_price = str(lowest_prices_count)
            self.logger.log_info(f"Today's lowest {formatted_price} prices are:")

            for item in result:
                self.logger.log_info(f"..... Time: {item.get_start_datetime(True)}, Price: {item.get_price(True)} Cent/kWh")

        result = self.items.get_highest_prices(self.config.number_of_highest_prices_for_discharging)
        if result:
            highest_prices_count = self.config.number_of_highest_prices_for_discharging
            if isinstance(highest_prices_count, float):
                formatted_price = f"{highest_prices_count * 100}%"
            else:
                formatted_price = str(highest_prices_count)
            self.logger.log_info(f"Today's highest {formatted_price} prices are:")
            for item in result:
                self.logger.log_info(f"..... Time: {item.get_start_datetime(True)}, Price: {item.get_price(True)} Cent/kWh")

    @staticmethod
    def create_condition(description, condition_function):
        return {
            "condition": condition_function,
            "description": f"{description}"
        }

    def create_condition_function(self, threshold, comparison_operator):
        def condition():
            return comparison_operator(threshold, self.current_price)

        return condition

    def add_additional_charging_conditions(self):
        # Weitere Bedingungen für Aufladung hinzufügen
        additional_conditions = {
            f"charging_price_limit ({Item.millicent_to_cent(self.charging_price_limit)}) > {Item.millicent_to_cent(self.current_price)}": self.create_condition_function(
                self.charging_price_limit, lambda x, y: x > y),
            # Füge weitere Bedingungen hier hinzu
        }

        self.conditions_by_operation_mode["charging"].update(additional_conditions)

        additional_prices = self.items.get_lowest_prices(self.config.number_of_lowest_prices_for_charging)
        for i, item in enumerate(additional_prices):
            price = item.get_price(False)
            start_time = item.get_start_datetime(True)
            key = f"lowestprice_{i + 1} {start_time} ({item.get_price()} Cent/kWh) == {item.millicent_to_cent(self.current_price)} Cent/kWh"
            condition_function = self.create_condition_function(price, lambda x, y: x == y)
            self.conditions_by_operation_mode["charging"][key] = condition_function

        count = self.items.get_valid_items_count_until_midnight(additional_prices)
        message = f"There {'is' if count == 1 else 'are'} still {count} {'cheap price' if count == 1 else 'cheap prices'} available today."
        self.logger.log_info(message)

        # Aktualisieren der Beschreibungen
        self.charging_descriptions = [condition["description"] for condition in
                                      self.conditions_by_operation_mode["charging"].values() if
                                      isinstance(condition, dict)]

    def add_additional_discharging_conditions(self):
        additional_prices = self.items.get_highest_prices(self.config.number_of_highest_prices_for_discharging)
        for i, item in enumerate(additional_prices):
            price = item.get_price(False)
            start_time = item.get_start_datetime(True)
            key = f"highestprice_{i + 1} {start_time} ({item.get_price()} Cent/kWh) == {item.millicent_to_cent(self.current_price)} Cent/kWh"
            condition_function = self.create_condition_function(price, lambda x, y: x == y)
            self.conditions_by_operation_mode["discharging"][key] = condition_function

        count = self.items.get_valid_items_count_until_midnight(additional_prices)
        message = f"There {'is' if count == 1 else 'are'} still {count} {'expensive price' if count == 1 else 'expensive prices'} available today."
        self.logger.log_info(message)

        # Weitere Bedingungen für Entladung hinzufügen
        additional_conditions = {
            # Füge weitere Bedingungen hier hinzu
        }
        self.conditions_by_operation_mode["discharging"].update(additional_conditions)

        # Aktualisieren der Beschreibungen
        self.discharge_descriptions = [condition["description"] for condition in
                                       self.conditions_by_operation_mode["discharging"].values() if
                                       isinstance(condition, dict)]

    def evaluate_conditions(self, condition_result, operation_mode):
        if operation_mode not in self.available_operation_modes:
            self.logger.log_error(f"Invalid operation mode: {operation_mode}")
            return

        conditions_to_evaluate = self.conditions_by_operation_mode.get(operation_mode, {})

        for condition_key, condition_function in conditions_to_evaluate.items():
            result = False
            try:
                result = condition_function()
                self.logger.log_debug(
                    f"Evaluating condition: {condition_key} - Result: {result}")
            except Exception as e:
                self.logger.log_error(
                    f"Error while evaluating condition: {e}")

            if result and not condition_result.condition:
                condition_result.execute = True
                condition_result.condition = condition_key
                if self.config.log_level != "DEBUG":
                    break
