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
from spotmarket.abstract_classes.item import Item
from datetime import datetime, timedelta, timezone


class ConditionResult:
    def __init__(self):
        self.execute = False
        self.condition = ""


class Conditions:
    def __init__(self, itemlist, solardata):
        self.items = itemlist
        self.solardata = solardata
        self.config = Config()
        self.logger = CustomLogger()
        self.available_surplus = 0.0
        self.current_price = itemlist.get_current_price()
        self.charging_price_limit = Item.convert_to_millicents(self.config.charging_price_limit)
        self.charging_price_hard_cap = Item.convert_to_millicents(self.config.charging_price_hard_cap)
        self.available_operation_modes = ["charging", "discharging"]
        self.conditions_by_operation_mode = {mode: {} for mode in self.available_operation_modes}
        self.abort_conditions_by_operation_mode = {mode + "_abort": {} for mode in self.available_operation_modes}
        self.charging_conditions = {}
        self.discharge_conditions = {}
        self.charging_descriptions = ""
        self.discharge_descriptions = ""
        self.add_additional_charging_conditions()
        self.add_additional_discharging_conditions()
        self.add_abort_conditions()

    def info(self):
        self.logger.log_info(f"Current price: {self.items.get_current_price(True)} Cent/kWh")
        average_price_today, average_price_tomorrow = self.items.get_average_price_by_date(True)
        self.logger.log_info(f"Average price Today: {average_price_today} Cent/kWh")
        if average_price_tomorrow:
            self.logger.log_info(f"Average price Tomorrow: {average_price_tomorrow} Cent/kWh")

        result = self.items.get_lowest_prices(self.config.number_of_lowest_prices_for_charging)
        if result:
            lowest_prices_count = self.config.number_of_lowest_prices_for_charging
            if isinstance(lowest_prices_count, float):
                formatted_price = f"{int(round(lowest_prices_count * 100, 0))}%"
            else:
                formatted_price = str(lowest_prices_count)

            # Trenne die Items in "heute" und "morgen"
            today_items = [item for item in result if self.items.is_today(item)]
            tomorrow_items = [item for item in result if not self.items.is_today(item)]

            # Logge die Items für heute
            if today_items:
                self.logger.log_info(f"Today's lowest {formatted_price} prices are:")
                for item in today_items:
                    self.logger.log_info(
                        f"..... Time: {item.get_start_datetime(True)}, Price: {item.get_price(True)} Cent/kWh"
                    )

            # Logge die Items für morgen, falls vorhanden
            if tomorrow_items:
                self.logger.log_info(f"Tomorrow's lowest {formatted_price} prices are:")
                for item in tomorrow_items:
                    self.logger.log_info(
                        f"..... Time: {item.get_start_datetime(True)}, Price: {item.get_price(True)} Cent/kWh"
                    )

        result = self.items.get_highest_prices(self.config.number_of_highest_prices_for_discharging)
        if result:
            highest_prices_count = self.config.number_of_highest_prices_for_discharging
            if isinstance(highest_prices_count, float):
                formatted_price = f"{int(round(highest_prices_count * 100, 0))}%"
            else:
                formatted_price = str(highest_prices_count)

            # Trenne die Items in "heute" und "morgen"
            today_items = [item for item in result if self.items.is_today(item)]
            tomorrow_items = [item for item in result if not self.items.is_today(item)]

            # Logge die Items für heute
            if today_items:
                self.logger.log_info(f"Today's highest {formatted_price} prices are:")
                for item in today_items:
                    self.logger.log_info(
                        f"..... Time: {item.get_start_datetime(True)}, Price: {item.get_price(True)} Cent/kWh"
                    )

            # Logge die Items für morgen, falls vorhanden
            if tomorrow_items:
                self.logger.log_info(f"Tomorrow's highest {formatted_price} prices are:")
                for item in tomorrow_items:
                    self.logger.log_info(
                        f"..... Time: {item.get_start_datetime(True)}, Price: {item.get_price(True)} Cent/kWh"
                    )

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
        # additional_conditions = {
        #     "Soc is greater than the required Soc": lambda: self.solardata.soc is not None and self.solardata.need_soc is not None and self.solardata.soc > self.solardata.need_soc,
        #     # Füge weitere Bedingungen hier hinzu
        # }

        future_high_prices = [item for item in additional_prices if not item.is_expired(True)]
        current_soc_wh, min_soc_wh, required_capacity = self._calculate_available_surplus(future_high_prices)

        additional_conditions = {
            f"Discharge allowed: {self.available_surplus / 1000:.2f} kWh surplus (SOC: {self.solardata.soc or 0:.2f}% ({current_soc_wh / 1000:.2f} kWh), Expensive hours: {len(future_high_prices)}, Req. Capacity: {required_capacity / 1000:.2f} kWh)": lambda: self._calculate_discharge_conditions(
                future_high_prices)

            #            f"Discharge allowed based on SOC ({self.solardata.soc:.2f}% [{current_soc_wh:.2f} Wh]) and forecasted high prices ({len(future_high_prices)} [{required_capacity:.2f} Wh]). Available surplus: {self.available_surplus:.2f} Wh": lambda: self._calculate_discharge_conditions(
            #                future_high_prices)
        }
        self.conditions_by_operation_mode["discharging"].update(additional_conditions)

        # Aktualisieren der Beschreibungen
        self.discharge_descriptions = [condition["description"] for condition in
                                       self.conditions_by_operation_mode["discharging"].values() if
                                       isinstance(condition, dict)]

    def add_abort_conditions(self):

        required_capacity = self._calculate_required_capacity_for_period()
        available_soc_wh, _, min_soc_wh = self._calculate_current_soc_wh()
        available_soc_wh -= min_soc_wh
        additional_prices = self.items.get_lowest_prices(self.config.number_of_lowest_prices_for_charging)

        # Abbruchbedingungen für das Laden
        charging_abort_conditions = {
            "Abort charge condition - Price exceeds hard cap": lambda: (
                    self.current_price > self.charging_price_hard_cap
            ),

            f"Abort charge condition - Required capacity ({required_capacity / 1000:.2f} kWh) is lower than available SOC ({available_soc_wh / 1000:.2f} kWh)": lambda: (
                    required_capacity < available_soc_wh
                    and any(
                item.price < self.current_price
                and item.starttime > datetime.utcnow().replace(tzinfo=timezone.utc)
                for item in additional_prices
            )
            ) if self.config.config_data.get('use_solar_forecast_to_abort') else False,
        }

        discharging_abort_conditions = {}
        if self.solardata.soc is not None and self.solardata.need_soc is not None:
            additional_prices = self.items.get_highest_prices(self.config.number_of_highest_prices_for_discharging)
            current_price = self.items.get_current_price()
            now = TimeUtilities.get_now()
            tomorrow_start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

            # Filtere die Items, um nur solche zu bekommen, die heute starten (>= now und < morgen)
            valid_items = [
                item for item in additional_prices
                if now <= item.get_start_datetime() < tomorrow_start
            ]

            # Wenn current_price nicht in der Liste der höchsten Preise ist, wird die Bedingung überprüft
            discharging_abort_conditions[
                "Abort discharge condition - Outside sunshine hours and Soc is lower than the required Soc"] = lambda: (
                    self.solardata.outside_sun_hours() and self.solardata.soc < self.solardata.need_soc
                    and all(current_price != item.get_price() for item in valid_items)
            ) if self.config.config_data.get('use_solar_forecast_to_abort') else False

            discharging_abort_conditions[
                "Abort discharge condition - Soc is lower or equal the minimum Soc Limit"] = lambda: self.solardata.soc <= self.solardata.battery_minimum_soc_limit

        # Fügen Sie die Abbruchbedingungen den entsprechenden Dictionarys hinzu
        self.abort_conditions_by_operation_mode["charging_abort"].update(charging_abort_conditions)
        self.abort_conditions_by_operation_mode["discharging_abort"].update(discharging_abort_conditions)

    def evaluate_conditions(self, condition_result, operation_mode):
        if operation_mode not in self.available_operation_modes:
            self.logger.log_error(f"Invalid operation mode: {operation_mode}")
            return

        conditions_to_evaluate = self.conditions_by_operation_mode.get(operation_mode, {})
        condition_matched = False  # Variable, um den Status zu verfolgen

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
                condition_matched = True  # Bedingung erfolgreich ausgewertet
                if self.config.log_level != "DEBUG":
                    break

        # Überspringe die Abbruchbedingungen, wenn keine Bedingung erfolgreich war
        if not condition_matched:
            self.logger.log_debug("No conditions matched. Skipping abort conditions.")
            return

        # Execute abort conditions (set execute to False)
        abort_conditions = self.abort_conditions_by_operation_mode.get(operation_mode + "_abort", {})
        for condition_key, condition_function in abort_conditions.items():
            result = False
            try:
                result = condition_function()
                self.logger.log_debug(
                    f"Evaluating abort condition: {condition_key} - Result: {result}")
            except Exception as e:
                self.logger.log_error(
                    f"Error while evaluating abort condition: {e}")

            if result:
                condition_result.execute = not result
                condition_result.condition = condition_key
                break

    def _calculate_required_capacity(self, upcoming_hours):
        average_consumption = 0.0
        average_consumption_list = StatsManager.get_data('gridmeters', 'forward_hourly')
        if average_consumption_list is not None:
            average_consumption = round(average_consumption_list[0], 2)

        # Calculate the required capacity based on the number of upcoming high-price periods
        required_capacity = upcoming_hours * average_consumption * 1.10  # Add 10% buffer - Multiply by average hourly consumption
        self.logger.log_debug(f"Required capacity: {required_capacity:.2f} Wh")
        return required_capacity

    def _calculate_current_soc_wh(self):
        try:
            # Check if the relevant data is present and valid
            if self.solardata.soc is None or self.solardata.soc < 0:
                raise ValueError("SOC value is missing or invalid.")
            if self.solardata.battery_capacity is None or self.solardata.battery_capacity <= 0:
                raise ValueError("Battery capacity is missing or invalid.")
            if self.solardata.battery_minimum_soc_limit is None or self.solardata.battery_minimum_soc_limit < 0:
                raise ValueError("Minimum SOC limit is missing or invalid.")

            efficiency = self.config.converter_efficiency

            # Calculate the full capacity
            full_capacity = (
                                    self.solardata.battery_capacity / self.solardata.soc) * 100 * efficiency if self.solardata.soc > 0 else 0.0
            battery_capacity_wh = full_capacity * 54.20 * efficiency # Battery capacity in Wh

            # Calculate the current SOC in Wh
            current_soc_wh = ((self.solardata.soc or 0) / 100) * battery_capacity_wh

            # Calculate the minimum SOC in Wh (including the minimum SOC limit)
            min_soc_wh = (self.solardata.battery_minimum_soc_limit / 100) * battery_capacity_wh

            return current_soc_wh, battery_capacity_wh, min_soc_wh

        except ZeroDivisionError:
            # Error handling for division by zero when SOC is 0
            self.logger.log_error("Division by zero during the calculation of full capacity.")
            return 0.0, 0.0, 0.0

        except ValueError as e:
            # Error handling for invalid or missing inputs
            self.logger.log_error(f"Error during SOC calculation: {str(e)}")
            return 0.0, 0.0, 0.0

    def _calculate_available_surplus(self, upcoming_high_prices):
        current_soc_wh, akkukapazitaet_wh, min_soc_wh = self._calculate_current_soc_wh()

        required_capacity = self._calculate_required_capacity(len(upcoming_high_prices))

        # Add a 10% buffer to the required capacity to maintain a safety margin
        buffer = 0.10 * current_soc_wh

        # Calculate the available surplus energy with the buffer
        self.available_surplus = current_soc_wh - min_soc_wh - buffer - required_capacity
        self.available_surplus = max(0, self.available_surplus)  # Ensure surplus is not negative

        self.logger.log_debug(
            f"Current SOC: {current_soc_wh:.2f} Wh, Min SOC: {min_soc_wh:.2f} Wh, Buffer: {buffer:.2f} Wh")
        self.logger.log_debug(f"Available Surplus: {self.available_surplus:.2f} Wh")

        return current_soc_wh, min_soc_wh, required_capacity

    def _calculate_discharge_conditions(self, upcoming_high_prices):
        """Helper function to encapsulate the discharge calculation logic."""

        current_soc_wh, min_soc_wh, required_capacity = self._calculate_available_surplus(upcoming_high_prices)
        # Calculate the required capacity based on future high prices
        if upcoming_high_prices:

            # Calculate the maximum dischargeable amount without falling below the required capacity
            max_dischargeable_amount = current_soc_wh - (required_capacity + min_soc_wh)
            self.logger.log_debug(f"Max Dischargeable Amount: {max_dischargeable_amount:.2f} Wh")

            if max_dischargeable_amount < 0:
                return False  # Not enough SOC for future high prices, discharging not allowed
            else:
                dischargeable_amount = min(self.available_surplus, max_dischargeable_amount)
                return dischargeable_amount > 0  # Discharge allowed if there's available energy to discharge
        else:
            # No future high prices, allow discharge if there's enough available surplus energy
            dischargeable_amount = self.available_surplus
            if dischargeable_amount > 0:
                return True
            else:
                return False  # Not enough SOC or surplus energy for discharging

    def _calculate_required_capacity_for_period(self):
        """
        Berechnet die erforderliche Kapazität für die Zeit vor und nach Mitternacht basierend auf Sonnenuntergang und -aufgang.
        Nutzt die Solarvorhersage, um den Bedarf abzuschätzen.
        """

        current_time = TimeUtilities.get_now()

        # Versuch sunset und sunrise zu parsen, falls nicht verfügbar, Standardzeiten verwenden
        try:
            sunset = datetime.strptime(self.solardata.sunset_current_day, "%Y-%m-%dT%H:%M").replace(
                tzinfo=TimeUtilities.TZ)
        except (TypeError, ValueError):
            self.logger.log_warning("Sunset data is invalid or not available, using default sunset time.")
            sunset = current_time.replace(hour=18, minute=0, second=0,
                                          microsecond=0)  # Standardzeit für Sonnenuntergang

        try:
            sunrise = datetime.strptime(self.solardata.sunrise_current_day, "%Y-%m-%dT%H:%M").replace(
                tzinfo=TimeUtilities.TZ)
        except (TypeError, ValueError):
            self.logger.log_warning("Sunrise data is invalid or not available, using default sunrise time.")
            sunrise = current_time.replace(hour=6, minute=0, second=0, microsecond=0)  # Standardzeit für Sonnenaufgang

        # Definiere midnight (Mitternacht des aktuellen Tages)
        midnight = current_time.replace(hour=0, minute=0, second=0, microsecond=0)

        expected_solar_energy = self.solardata.total_current_day
        required_capacity = 0.0  # Anfangswert für die erforderliche Kapazität

        remaining_description = ""
        # Berechne benötigte Kapazität bis Sonnenuntergang
        if current_time < sunset:
            remaining_until_sunset = (sunset - current_time).total_seconds() / 3600
            remaining_description = f"/ remaining until sunset: {remaining_until_sunset:.2f} hour"
            required_capacity += self._calculate_required_capacity(remaining_until_sunset)

        # Nach Sonnenuntergang
        elif current_time >= sunset:
            # Vor Mitternacht
            if current_time < midnight:
                remaining_until_midnight = (midnight - current_time).total_seconds() / 3600  # Stunden bis Mitternacht
                remaining_description = f"/ remaining until midnight: {remaining_until_midnight:.2f} hour"
                required_capacity += self._calculate_required_capacity(remaining_until_midnight)

            # Ab Mitternacht bis Sonnenaufgang
            if midnight <= current_time < sunrise:
                # Nutze Solarvorhersage ab Mitternacht bis Sonnenaufgang
                required_capacity = max(0, required_capacity - expected_solar_energy)

        # Berechnung für den nächsten Tag (nach Sonnenaufgang)
        if current_time >= sunrise:
            # Berechne den benötigten Verbrauch bis zum nächsten Sonnenaufgang
            remaining_until_next_sunrise = (sunrise + timedelta(days=1) - current_time).total_seconds() / 3600
            remaining_description = f"/ remaining until next sunrise: {remaining_until_next_sunrise:.2f} hour"

            required_capacity += self._calculate_required_capacity(remaining_until_next_sunrise)

        # Ausgabe des Logs mit benötigter Kapazität und aktuellem SOC
        self.logger.log_info(
            f"Required capacity for period: {required_capacity:.2f} Wh {remaining_description} / current SOC {self.solardata.soc}% ({self._calculate_current_soc_wh()[0]:.2f} Wh)")

        return required_capacity
