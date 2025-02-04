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
# -*- coding: utf-8 -*-

import os
import signal
import sys
import threading
import time
import random
import json
from datetime import datetime, timedelta

import core.version as version
from core.statsmanager import StatsManager
from core.websocketserver import WebSocketServer
from solar.openmeteo import OpenMeteo
from solar.solardata import Solardata
from solar.solarbatterycalculator import SolarBatteryCalculator
from core.conditions import Conditions, ConditionResult
from core.config import Config
from core.log import CustomLogger
from design_patterns.factory.generic_loader_factory import GenericLoaderFactory
from spotmarket.abstract_classes.itemlist import Itemlist
from core.seussweb import SEUSSWeb
from core.timeutilities import TimeUtilities
from powerconsumption.powerconsumptionmanager import PowerConsumptionManager

class SEUSS:
    def __init__(self):
        self.config = Config()
        self.logger = CustomLogger()
        self.svs_thread = None
        self.ws_server = WebSocketServer()
        self.seuss_web = SEUSSWeb()
        self.power_consumption_manager = PowerConsumptionManager()
        self.statsmanager = StatsManager()
        self.statsmanager.remove_unused_datagroups()

        self.no_data = [0]
        self.svs_thread_stop_flag = threading.Event()
        self.solardata = Solardata()
        self.items = Itemlist.create_item_list([])
        self.current_time = datetime.now()

    def handle_config_update(self, config_data):
        self.logger.log_info("Run checks while configuration was changed")
        self.load_configuration()
        self.run_markets()

    def run_markets(self):
        self.items = self.update_items()
        self.seuss_web.set_item_list(self.items)
        self.run_essunit()

    def run_essunit(self):
        essunit = self.initialize_essunit()
        if essunit is not None:
            unit_config = essunit.get_config()
            active_soc_limit = essunit.get_active_soc_limit()
            soc = essunit.get_soc()
            delay_active_soc_limit = self.config.config_data.get("delay_grid_charging_below_active_soc_limit", False)
            self.logger.log_info(f"Active Soc Limit: {active_soc_limit} Soc: {soc} Delay: {delay_active_soc_limit} ")

            if delay_active_soc_limit and soc < active_soc_limit:
                check_limit = self.statsmanager.get_data("ess_unit", "soc_limit")
                if check_limit is None:
                    self.statsmanager.set_status_data("ess_unit", "soc_limit", active_soc_limit)

                self.statsmanager.set_status_data("ess_unit", "soc_delay", 1)
                t_soc = (soc // 5) * 5
                if t_soc < active_soc_limit:
                    essunit.set_active_soc_limit(t_soc)

            else:
                check_limit = self.statsmanager.get_data("ess_unit", "soc_limit")

                if check_limit is not None:
                    if soc > active_soc_limit:
                        t_soc = (soc // 5) * 5
                        if t_soc < check_limit:
                            essunit.set_active_soc_limit(t_soc)

                    if abs(soc - check_limit) <= 1:
                        if active_soc_limit > check_limit:
                            self.statsmanager.set_status_data("ess_unit", "soc_limit", active_soc_limit)
                        else:
                            # Auf gespeicherten Wert zurücksetzen und Delay beenden
                            essunit.set_active_soc_limit(check_limit)
                            self.statsmanager.remove_data("ess_unit", "soc_limit")
                            self.statsmanager.set_status_data("ess_unit", "soc_delay", 0)

            self.power_consumption_manager.update_instance(unit_config)
            if self.ws_server:
                power_consumption_instance = self.power_consumption_manager.get_instance()
                if power_consumption_instance:
                    power_consumption_instance.set_ws_server(self.ws_server)

            # if essunit is not None:
            #    essunit.get_data()
            total_solar = self.process_solar_data(essunit)
            self.process_solar_forecast(total_solar)
            if self.items.get_item_count() > 0:
                self.evaluate_conditions_and_control_charging_discharging(essunit)
            else:
                self.handle_no_data(essunit)

            next_minute = (self.current_time.minute // 15 + 1) * 15
            if next_minute >= 60:
                next_hour = self.current_time.replace(second=0, microsecond=0, minute=0) + timedelta(hours=1)
            else:
                next_hour = self.current_time.replace(second=0, microsecond=0, minute=next_minute)
            next_run_time = next_hour
            self.logger.log_info(f"Next {essunit.get_name()} check at {next_run_time.strftime('%H:%M')}")
            return

        self.power_consumption_manager.stop_instance()
        self.logger.log_info("No enabled essunit found.")

    def run_svs(self):
        self.load_configuration()
        self.initialize_logging()
        self.config.observer.add_observer("seuss", self)
        lasttime_minute = None  # Startwert bleibt None, damit die erste Ausführung sofort möglich ist

        try:
            while True:
                self.current_time = datetime.now()

                if (self.current_time.minute == 0 and self.current_time.second == 5) or self.items.get_item_count() == 0:
                    self.run_markets()
                    if self.items:
                        next_hour = self.current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                        self.logger.log_info(f"Next price check at {next_hour.strftime('%H:%M')}")
                        self.logger.log_info(
                            f"Current Spotmarket: {self.items.current_market_name}, failback: {self.items.failback_market_name}"
                        )

                interval_minutes = 15
                if self.current_time.minute % interval_minutes == 0 and self.current_time.minute != 0 and self.current_time.minute != lasttime_minute:
                    lasttime_minute = self.current_time.minute

                    if self.config.use_second_day and 13 < self.current_time.hour < 15 and self.items.get_item_count() < 25:
                        self.run_markets()
                    else:
                        self.run_essunit()

                    if self.items:
                        next_hour = self.current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                        self.logger.log_info(f"Next price check at {next_hour.strftime('%H:%M')}")
                        self.logger.log_info(
                            f"Current Spotmarket: {self.items.current_market_name}, failback: {self.items.failback_market_name}"
                        )

                self.perform_test_run()
                self.handle_no_data_sleep()

                self.current_time = datetime.now()
                sleep_time = 1 - (self.current_time.microsecond / 1_000_000)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.graceful_exit(signal.SIGINT, None)

    def load_configuration(self):
        self.config.load_config()

    def initialize_logging(self):
        self.logger.log_info(f"SEUSS v{version.__version__} started...")
        self.logger.log_info(f"{self.config.config_data}")

    def update_items(self):
        return self.items.perform_update(self.items)

    def initialize_essunit(self):
        if self.config.essunit is None:
            self.logger.log_warning(f"essunit is None. Try to reload config")
            self.config.load_config()

        return GenericLoaderFactory.create_loader("essunit", self.config.essunit)

    def process_solar_data(self, essunit):
        total_solar = 0.0
        if essunit is not None:
            total_solar = self.get_total_solar_yield(essunit)

        return total_solar

    def get_total_solar_yield(self, essunit):
        self.solardata.update_soc(essunit.get_soc())
        self.solardata.update_battery_capacity(essunit.get_battery_capacity())
        self.solardata.update_battery_minimum_soc_limit(essunit.get_battery_minimum_soc_limit())
        self.solardata.update_battery_current_voltage(essunit.get_battery_current_voltage())

        gridmeters = essunit.get_grid_meters()
        inverters = essunit.get_solar_energy()
        total_solar = 0.0
        total_forward_hourly = 0.0

        for key_outer, value_outer in gridmeters.gridmeters.items():
            customname = gridmeters.get_value(key_outer, 'CustomName')
            productname = gridmeters.get_value(key_outer, 'ProductName')
            forward = gridmeters.get_forward_kwh(key_outer)
            forward_hourly = gridmeters.get_hourly_kwh(key_outer)
            self.logger.log_debug(f"Found Gridmeter:  {productname} {customname}.")
            self.logger.log_info(
                f"{productname} {customname} today:  {round(forward, 2)} Wh, average hour: {round(forward_hourly, 2)} Wh")

            for key_inner, value_inner in value_outer.items():
                self.logger.log_debug(f"  {key_inner}: {json.loads(value_inner)['value']}")

        total_forward_hourly_list = self.statsmanager.get_data("powerconsumption","hourly_watt_average")
        total_forward_hourly = total_forward_hourly_list[0] if total_forward_hourly_list else 0.0
        manager_instance = self.power_consumption_manager.get_instance()
        if manager_instance:
            value = manager_instance.get_hourly_average()
            consumption = manager_instance.get_daily_wh()
            total_forward_hourly = (total_forward_hourly + value) / 2
            self.logger.log_info(
                f"Consumption today: {round(consumption, 2):.2f} Wh, forecast today: {total_forward_hourly * 24:.2f} Wh average hour: {round(total_forward_hourly, 2):.2f} Wh")

            self.statsmanager.update_percent_status_data('gridmeters', 'forward_hourly', total_forward_hourly)

        for key_outer, value_outer in inverters.inverters.items():
            customname = inverters.get_value(key_outer, 'CustomName')
            productname = inverters.get_value(key_outer, 'ProductName')
            forward = inverters.get_forward_kwh(key_outer)
            total_solar += float(forward)
            self.logger.log_debug(f"Found PV Inverter:  {productname} {customname}.")
            self.logger.log_info(f"{productname} {customname} yield today:  {round(forward, 2)} Wh.")

            for key_inner, value_inner in value_outer.items():
                self.logger.log_debug(f"  {key_inner}: {json.loads(value_inner)['value']}")

        self.logger.log_info(f"All Inverters yield today:  {round(total_solar, 2)} Wh.")
        self.solardata.update_current_hour_solar_yield(round(total_solar, 2))
        return total_solar

    def process_solar_forecast(self, total_solar):
        forecast = OpenMeteo()  # Forecastsolar()
        # self.solardata = Solardata()
        total_forecast = forecast.forecast(self.solardata)
        calculator = SolarBatteryCalculator(self.solardata)
        self.solardata.update_need_soc(calculator.calculate_battery_percentage())
        self.logger.log_info(f"Needed Charging SOC: {self.solardata.need_soc}%.")

        if total_forecast is not None and total_forecast > 0.0:
            percentage = (total_solar / total_forecast) * 100
            efficiency = None
            sunset_time = datetime.strptime(self.solardata.sunset_current_day, "%Y-%m-%dT%H:%M").time()
            current_time = TimeUtilities.get_now().time()

            if current_time < sunset_time and total_solar > 0.0:
                efficiency = self.statsmanager.update_percent_status_data('solar', 'efficiency', percentage)
            else:
                efficiency_list = self.statsmanager.get_data('solar', 'efficiency')
                if efficiency_list is not None:
                    efficiency = round(efficiency_list[0], 2)
            rounded_percentage = round(percentage, 2)
            self.logger.log_info(f"Solar current percent: {rounded_percentage}%. average: {efficiency}%")
        else:
            self.logger.log_info("Solar forecast is zero or not available.")

    def evaluate_conditions_and_control_charging_discharging(self, essunit):
        only_observation = False
        if essunit:
            info = self.config.get_essunit_info(essunit.get_name())
            only_observation = info.get("only_observation", False)

        if not only_observation:
            condition_charging_result = ConditionResult()
            condition_discharging_result = ConditionResult()
            conditions_instance = Conditions(self.items, self.solardata, essunit)
            conditions_instance.info()
            conditions_instance.evaluate_conditions(condition_charging_result, "charging")
            conditions_instance.evaluate_conditions(condition_discharging_result, "discharging")

            self.control_charging(essunit, condition_charging_result)
            self.control_discharging(essunit, condition_discharging_result)

        self.items.log_items()
        self.no_data[0] = 0

    def control_charging(self, essunit, condition_charging_result):
        if condition_charging_result.execute and essunit is not None:
            self.logger.log_info(
                f"Condition {condition_charging_result.condition} result: {condition_charging_result.execute}, charging is turned on.")
            essunit.set_charge("on")
            self.statsmanager.set_status_data('energy', "initial_charge_state_wh", essunit.get_battery_current_wh())
        elif condition_charging_result.condition and essunit is not None:
            self.logger.log_info(f"{condition_charging_result.condition}, charging is turned off.")
            essunit.set_charge("off")
            self.statsmanager.set_status_data('energy', "initial_charge_state_wh", 0.0)
        elif essunit is not None:
            self.logger.log_info("Since none of the charging conditions are true, charging is turned off.")
            essunit.set_charge("off")
            self.statsmanager.set_status_data('energy', "initial_charge_state_wh", 0.0)

    def control_discharging(self, essunit, condition_discharging_result):
        if condition_discharging_result.execute and essunit is not None:
            self.logger.log_info(
                f"Condition {condition_discharging_result.condition} result: {condition_discharging_result.execute}, discharging is turned on.")
            essunit.set_discharge("on")
        elif condition_discharging_result.condition and essunit is not None:
            self.logger.log_info(f"{condition_discharging_result.condition}, discharging is turned off.")
            essunit.set_discharge("off")
        elif essunit is not None:
            self.logger.log_info("Since none of the discharging conditions are true, discharging is turned off.")
            essunit.set_discharge("off")

    def handle_no_data(self, essunit):
        self.logger.log_warning("No data available")
        self.no_data[0] += 1
        if essunit is not None:
            self.logger.log_info("There are currently no prices, so the charging mode is turned off.")
            essunit.set_discharge("off")
            self.logger.log_info("There are currently no prices, so the discharging mode is turned on.")
            essunit.set_discharge("on")

    def perform_test_run(self):
        test_run = os.environ.get('TESTRUN')
        if test_run is not None:
            self.graceful_exit(signal.SIGINT, None)

    def handle_no_data_sleep(self):
        if 0 < self.no_data[0] < 4:
            sleeptime = random.randint(10, 60)
            self.logger.log_info(
                f"There is no data available, attempt number {self.no_data[0]}/3 failed. wait {sleeptime} seconds for the next attempt.")
            time.sleep(sleeptime)
        else:
            self.no_data[0] = 0  # Aktualisiere die verpackte Variable

    def handle_time_to_next_hour(self, current_time):
        next_hour = (current_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        time_to_next_hour = int((next_hour - current_time).total_seconds())
        self.logger.log_info(f"Next price check at {next_hour.strftime('%H:%M')}")
        if self.items:
            self.logger.log_info(
                f"Current Spotmarket: {self.items.current_market_name}, failback: {self.items.failback_market_name}")
        time.sleep(max(0, time_to_next_hour + 2))

    def graceful_exit(self, signum, frame):
        print("\r   ")  # clear ^C
        print(f"Program will be terminated... signal: {signum}")
        self.logger.log_info("Program will be terminated...")

        self.power_consumption_manager.stop_instance()
        self.ws_server.stop()
        self.seuss_web.stop()
        self.svs_thread_stop_flag.set()

        sys.exit(0)

    def excepthook_handler(self, exc_type, exc_value, exc_traceback):
        self.logger.log_error(f"Unknown Exception exc_info=({exc_type}, {exc_value}, {exc_traceback})")

    def start(self):
        sys.excepthook = self.excepthook_handler

        # WebSocket-Server starten
        ws_server_thread = threading.Thread(target=self.ws_server.run, daemon=True)
        ws_server_thread.start()

        bottle_thread = threading.Thread(target=self.seuss_web.run, daemon=True)
        bottle_thread.start()

        self.svs_thread = threading.Thread(target=self.run_svs, daemon=True)
        self.svs_thread.start()

        signal.signal(signal.SIGINT, self.graceful_exit)
        signal.signal(signal.SIGTERM, self.graceful_exit)

        try:
            while not self.svs_thread_stop_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.graceful_exit(signal.SIGINT, None)
