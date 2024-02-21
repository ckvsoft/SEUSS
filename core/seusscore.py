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
from solar.openmeteo import OpenMeteo
from solar.solardata import Solardata
from solar.solarbatterycalculator import SolarBatteryCalculator
from core.conditions import Conditions, ConditionResult
from core.config import Config
from core.log import CustomLogger
from design_patterns.factory.generic_loader_factory import GenericLoaderFactory
from spotmarket.abstract_classes.itemlist import Itemlist
from core.seussweb import SEUSSWeb

class SEUSS:
    def __init__(self):
        self.config = Config()
        self.logger = CustomLogger()
        self.svs_thread = None
        self.seuss_web = SEUSSWeb()
        self.no_data = [0]
        self.svs_thread_stop_flag = threading.Event()
        self.solardata = Solardata()

    def run_svs(self):
        self.load_configuration()
        self.initialize_logging()

        items = self.initialize_items()
        no_data = self.no_data

        try:
            while True:
                current_time = datetime.now()

                items = self.update_items(items)
                self.seuss_web.set_item_list(items)

                essunit = self.initialize_essunit()
                total_solar = self.process_solar_data(essunit)

                self.process_solar_forecast(total_solar)

                if items.get_item_count() > 0:
                    self.evaluate_conditions_and_control_charging_discharging(essunit, items, no_data)
                else:
                    self.handle_no_data(essunit, no_data)

                self.perform_test_run()

                self.handle_no_data_sleep(no_data)

                no_data, time_to_next_hour = self.handle_time_to_next_hour(current_time, items, no_data)

        except KeyboardInterrupt:
            self.graceful_exit(signal.SIGINT, None)

    def load_configuration(self):
        self.config.load_config()

    def initialize_logging(self):
        self.logger.log_info(f"SEUSS v{version.__version__} started...")
        self.logger.log_info(f"{self.config.config_data}")

    def initialize_items(self):
        return Itemlist.create_item_list([])

    def update_items(self, items):
        return items.perform_update(items)

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
        gridmeters = essunit.get_grid_meters()
        inverters = essunit.get_solar_energy()
        total_solar = 0.0

        for key_outer, value_outer in gridmeters.gridmeters.items():
            customname = gridmeters.get_value(key_outer, 'CustomName')
            productname = gridmeters.get_value(key_outer, 'ProductName')
            forward = gridmeters.get_forward_kwh(key_outer)
            forward_hourly = gridmeters.get_hourly_kwh(key_outer)
            self.logger.log_debug(f"Found Gridmeter:  {productname} {customname}.")
            self.logger.log_info(f"{productname} {customname} today:  {round(forward, 2)} Wh, average hour: {round(forward_hourly, 2)} Wh")

            for key_inner, value_inner in value_outer.items():
                self.logger.log_debug(f"  {key_inner}: {json.loads(value_inner)['value']}")

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
        return total_solar

    def process_solar_forecast(self, total_solar):
        forecast = OpenMeteo() # Forecastsolar()
        # self.solardata = Solardata()
        total_forecast = forecast.forecast(self.solardata)
        calculator = SolarBatteryCalculator(self.solardata)
        self.solardata.update_need_soc(calculator.calculate_battery_percentage())
        self.logger.log_info(f"Needed Charging SOC: {self.solardata.need_soc}%.")

        if total_forecast is not None and total_forecast > 0.0:
            percentage = (total_solar / total_forecast) * 100
            efficiency = None
            if total_solar > 0.0:
                efficiency = StatsManager.update_percent_status_data('solar', 'efficiency', percentage)
            rounded_percentage = round(percentage, 2)
            self.logger.log_info(f"Solar current percent: {rounded_percentage}%. (average: {efficiency})%")
        else:
            self.logger.log_info("Solar forecast is zero or not available.")

    def evaluate_conditions_and_control_charging_discharging(self, essunit, items, no_data):
        condition_charging_result = ConditionResult()
        condition_discharging_result = ConditionResult()
        conditions_instance = Conditions(items, self.solardata)
        conditions_instance.info()
        conditions_instance.evaluate_conditions(condition_charging_result, "charging")
        conditions_instance.evaluate_conditions(condition_discharging_result, "discharging")

        self.control_charging(essunit, condition_charging_result)
        self.control_discharging(essunit, condition_discharging_result)

        items.log_items()
        no_data[0] = 0

    def control_charging(self, essunit, condition_charging_result):
        if condition_charging_result.execute and essunit is not None:
            self.logger.log_info(f"Condition {condition_charging_result.condition} result: {condition_charging_result.execute}, charging is turned on.")
            essunit.set_charge("on")
        elif essunit is not None:
            self.logger.log_info("Since none of the charging conditions are true, charging is turned off.")
            essunit.set_charge("off")

    def control_discharging(self, essunit, condition_discharging_result):
        if condition_discharging_result.execute and essunit is not None:
            self.logger.log_info(
                f"Condition {condition_discharging_result.condition} result: {condition_discharging_result.execute}, discharging is turned on.")
            essunit.set_discharge("on")
        elif essunit is not None:
            self.logger.log_info("Since none of the discharging conditions are true, discharging is turned off.")
            essunit.set_discharge("off")

    def handle_no_data(self, essunit, no_data):
        self.logger.log_warning("No data available")
        no_data[0] += 1
        if essunit is not None:
            self.logger.log_info("There are currently no prices, so the charging mode is turned off.")
            essunit.set_discharge("off")
            self.logger.log_info("There are currently no prices, so the discharging mode is turned on.")
            essunit.set_discharge("on")

    def perform_test_run(self):
        test_run = os.environ.get('TESTRUN')
        if test_run is not None:
            self.graceful_exit(signal.SIGINT, None)

    def handle_no_data_sleep(self, no_data):
        if 0 < no_data[0] < 4:
            sleeptime = random.randint(10, 60)
            self.logger.log_info(f"There is no data available, attempt number {no_data[0]}/3 failed. wait {sleeptime} seconds for the next attempt.")
            time.sleep(sleeptime)
        else:
            no_data[0] = 0  # Aktualisiere die verpackte Variable

    def handle_time_to_next_hour(self, current_time, items, no_data):
        next_hour = (current_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        time_to_next_hour = int((next_hour - current_time).total_seconds())
        self.logger.log_info(f"Next price check at {next_hour.strftime('%H:%M')}")
        if items:
            self.logger.log_info(f"Current Spotmarket: {items.current_market_name}, failback: {items.failback_market_name}")
        time.sleep(max(0, time_to_next_hour + 2))

        return no_data, time_to_next_hour

    def graceful_exit(self, signum, frame):
        print("\r   ") # clear ^C
        self.logger.log_info("Program will be terminated...")
        self.seuss_web.stop()
        self.svs_thread_stop_flag.set()

        sys.exit(0)

    def excepthook_handler(self, exc_type, exc_value, exc_traceback):
        self.logger.log_error(f"Unknown Exception exc_info=({exc_type}, {exc_value}, {exc_traceback})")

    def start(self):
        sys.excepthook = self.excepthook_handler
        bottle_thread = threading.Thread(target=self.seuss_web.run)
        bottle_thread.daemon = True
        bottle_thread.start()

        self.svs_thread = threading.Thread(target=self.run_svs)
        self.svs_thread.daemon = True
        self.svs_thread.start()

        signal.signal(signal.SIGINT, self.graceful_exit)

        try:
            while not self.svs_thread_stop_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.graceful_exit(signal.SIGINT, None)
