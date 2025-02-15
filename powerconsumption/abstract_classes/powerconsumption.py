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

import json
import os
import threading
import time
import calendar

from core.log import CustomLogger
from core.statsmanager import StatsManager
from core.timeutilities import TimeUtilities


class PowerConsumptionBase:
    def __init__(self, interval_duration=5):
        self.interval_duration = interval_duration
        self.stop_event = threading.Event()
        self.ws_server = None
        self.logger = CustomLogger()
        self.statsmanager = StatsManager()
        self.running = False
        self.last_minute = None
        self.last_value = None  # Last power value in watts
        self.last_grid_value = None
        self.last_dc_value = 0
        self.last_time = None   # Last timestamp (seconds since epoch)
        self.current_price = 0

        self.hourly_wh = 0          # Consumption for the current hour in kWh
        self.hourly_grid_wh = 0
        self.energy_costs_by_hour = {}
        self.energy_costs_by_day = {}
        self.hourly_start_time = time.time()  # Start time of the current hour

        self.daily_wh = 0           # Daily consumption in kWh
        self.daily_grid_wh = 0
        self.current_hour = time.localtime(time.time()).tm_hour
        self.current_day = time.localtime(time.time()).tm_yday
        self.curent_year = time.localtime(time.time()).tm_year

        # Initialized variables
        self.P_DC_consumption_Battery = None
        self.P_AC_consumption_L1 = self.P_AC_consumption_L2 = self.P_AC_consumption_L3 = None
        self.G_AC_consumption_L1 = self.G_AC_consumption_L2 = self.G_AC_consumption_L3 = None
        self.number_of_phases = 3  # Default number of phases, adjust if needed
        self.number_of_grid_phases = 3  # Default number of phases, adjust if needed
        self.current_power = 0
        self.current_grid_power = 0
        self.consumption_diff = 0

        self.data_file = "consumption_data.json"
        self.load_data()

        self.thread = None
        self.average = (0,0)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
            self.logger.log.debug(f"{self.__class__.__name__} started with interval {self.interval_duration} minutes.")
        else:
            self.logger.log.debug(f"{self.__class__.__name__} is already running.")

    def stop(self):
        """Stop the running thread."""
        self.save_data(True)
        self.stop_event.set()  # Set the stop flag to end the run loop
        if self.thread:
            self.thread.join()  # Wait for the main thread to finish



    def run(self):
        """Main process - Implementation in derived classes."""
        raise NotImplementedError("This method must be implemented in the derived class.")

    def set_ws_server(self, ws):
        self.ws_server = ws

    def set_current_price(self, current_price):
        self.current_price = current_price

    def load_data(self):
        self.daily_wh = self.statsmanager.get_data("powerconsumption", "daily_wh") or 0.0

        hourly_wh_list = self.statsmanager.get_data("powerconsumption", "hourly_wh")
        self.hourly_wh, self.hourly_start_time = hourly_wh_list if isinstance(hourly_wh_list, tuple) and len(hourly_wh_list) == 2 else (0, time.time())

        average_list = self.statsmanager.get_data("powerconsumption", "average")
        self.average = average_list if isinstance(average_list, tuple) and len(average_list) == 2 else (0, 0)

        last_value_list = self.statsmanager.get_data("powerconsumption", "last_power_value")
        last_grid_value_list = self.statsmanager.get_data("powerconsumption", "last_grid_power_value")

        self.last_value, self.last_time = last_value_list if isinstance(last_value_list, tuple) and len(last_value_list) == 2 else (0, time.time())
        self.last_grid_value, _ = last_grid_value_list if isinstance(last_grid_value_list, tuple) and len(last_grid_value_list) == 2 else (0, time.time())

        energy_costs_by_hour = self.statsmanager.get_data("powerconsumption","energy_costs_by_hour")
        energy_costs_by_day = self.statsmanager.get_data("powerconsumption","energy_costs_by_day")

        self.logger.log.debug(f"Loaded energy costs by hour: {energy_costs_by_hour}")
        self.logger.log.debug(f"Loaded energy costs by day: {energy_costs_by_day}")

        self.energy_costs_by_hour = energy_costs_by_hour if energy_costs_by_hour else {}
        self.energy_costs_by_day = energy_costs_by_day if energy_costs_by_day else {}
        hourly_wh = self.statsmanager.get_data("powerconsumption","hourly_wh")
        if hourly_wh and hourly_wh[1] == self.current_hour:
            self.hourly_wh = hourly_wh[0]
        else:
            self.statsmanager.remove_data("powerconsumption", "hourly_wh")

    def save_data(self, logging=False):
        self.statsmanager.set_status_data("powerconsumption","energy_costs_by_hour", self.energy_costs_by_hour, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","energy_costs_by_day", self.energy_costs_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","hourly_wh", (self.hourly_wh, self.hourly_start_time), save_data=False)
        self.statsmanager.update_percent_status_data("powerconsumption","average", self.average, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","last_power_value", (self.last_value, self.last_time), save_data=False)
        self.statsmanager.set_status_data("powerconsumption","last_grid_power_value", (self.last_grid_value, self.last_time))
        self.statsmanager.set_status_data("powerconsumption","hourly_wh", (self.hourly_wh, self.current_hour))

        if logging:
            self.logger.log.debug("data saved.")

    def save_hour(self):
        """Speichert den Durchschnitt des aktuellen Stundenverbrauchs."""
        elapsed_time = (self.last_time - self.hourly_start_time) / 3600  # Zeit in Stunden
        value, count = self.average
        value *= count
        if elapsed_time > 0:
            avg_wh = self.hourly_wh / elapsed_time
            value += avg_wh
            count += 1
            value /= count
            self.average = (value, count)

        self.statsmanager.update_percent_status_data("powerconsumption", "average", self.average, save_data=False)
        self.logger.log.debug(f"save ... update average: {self.average}")
        self.statsmanager.update_percent_status_data("powerconsumption", "hourly_watt_average", value, save_data=False)
        self.statsmanager.update_percent_status_data("powerconsumption", "daily_watt_average", self.get_daily_average(), save_data=False)
        self.statsmanager.set_status_data("powerconsumption","daily_wh", self.daily_wh, save_data=False)

        # Speichert die Daten
        self.save_data()

    def save_day(self):
        print(f"Daily consumption: {self.daily_wh:.4f} Wh")
        self.statsmanager.update_percent_status_data("powerconsumption", "daily_watt_average", self.get_daily_average(), save_data=False)
        self.statsmanager.set_status_data("powerconsumption","energy_costs_by_day", self.energy_costs_by_day, save_data=False)
        total_cost = sum(self.energy_costs_by_hour.values())
        self.energy_costs_by_day[str(self.current_day)] = total_cost
        self.energy_costs_by_hour = {}

        # Speichert die Daten
        self.save_data()

    def update(self, power, grid_power, battery_power, timestamp):
        """Aktualisiert den Verbrauch basierend auf neuer Leistung und Zeit."""
        # Setze den Startwert, wenn es die erste Messung ist
        if self.last_time is None:
            self.last_value = power
            self.last_grid_value = grid_power
            self.last_time = timestamp
            self.current_hour = time.localtime(timestamp).tm_hour
            self.current_day = time.localtime(timestamp).tm_yday
            self.hourly_start_time = timestamp
            return

        # Berechne das Zeitintervall in Stunden
        time_diff = (timestamp - self.last_time) / 3600  # Zeitdifferenz in Stunden

        # Berechne den kWh-Verbrauch für diesen Zeitraum
        wh = (self.last_value * time_diff)
        self.hourly_wh += wh  # Addiere zum aktuellen Stundenverbrauch
        self.daily_wh += wh   # Update des täglichen Verbrauchs

        grid_wh = (self.last_grid_value * time_diff)
        if grid_wh > 0.0:
            self.hourly_grid_wh += grid_wh  # Addiere zum aktuellen Stundenverbrauch
            self.daily_grid_wh += grid_wh   # Update des täglichen Verbrauchs

        self.energy_costs_by_hour[str(self.current_hour)] = (self.hourly_grid_wh / 1000) * float(self.current_price)

        # Bestimme aktuelle Stunde und Tag
        current_hour = time.localtime(timestamp).tm_hour
        current_day = time.localtime(timestamp).tm_yday

        # Überprüfe, ob ein neuer Tag begonnen hat
        if current_day != self.current_day:
            self.save_day()  # Speichere den täglichen Verbrauch
            self.current_day = current_day
            self.daily_wh = 0  # Setze den täglichen Verbrauch zurück

        # Überprüfe, ob eine neue Stunde begonnen hat
        if current_hour != self.current_hour:
            self.save_hour()  # Speichere den Durchschnitt für die letzte Stunde
            self.current_hour = current_hour
            self.hourly_wh = 0  # Setze den stündlichen Verbrauch zurück
            self.hourly_start_time = timestamp
            self.hourly_grid_wh = 0

        # Speichern der Daten alle 5 Minuten
        current_minute = time.localtime(timestamp).tm_min
        if current_minute in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55] and current_minute != self.last_minute:
            self.save_data()
            self.last_minute = current_minute

        # Aktualisieren der letzten Werte
        self.last_value = power
        self.last_grid_value = grid_power
        self.last_dc_value = self.P_DC_consumption_Battery
        self.last_time = timestamp

    def check_for_data(self):
        missing_data = []

        if self.P_AC_consumption_L1 is None:
            missing_data.append("P_AC_consumption_L1")
        if self.number_of_phases is None:
            missing_data.append("number_of_phases")

        # Only for 2 or 3 phases:
        if self.number_of_phases >= 2 and self.P_AC_consumption_L2 is None:
            missing_data.append("P_AC_consumption_L2")
        if self.number_of_phases == 3 and self.P_AC_consumption_L3 is None:
            missing_data.append("P_AC_consumption_L3")

        #### grid
        if self.G_AC_consumption_L1 is None:
            missing_data.append("G_AC_consumption_L1")
        if self.number_of_grid_phases is None:
            missing_data.append("number_of_phases")

        # Only for 2 or 3 phases:
        if self.number_of_grid_phases >= 2 and self.G_AC_consumption_L2 is None:
            missing_data.append("G_AC_consumption_L2")
        if self.number_of_grid_phases == 3 and self.G_AC_consumption_L3 is None:
            missing_data.append("G_AC_consumption_L3")

        if missing_data:
            self.logger.log.debug(f"Missing data: {', '.join(missing_data)}")
            return False

        return True

    def get_hourly_average(self):
        """Calculates the projected hourly average."""
        elapsed_time_in_hours = (self.last_time - self.hourly_start_time) / 3600  # Elapsed time in hours
        if elapsed_time_in_hours > 0:
            # Project the hourly average based on the time already passed
            projected_wh = self.hourly_wh / elapsed_time_in_hours
            return projected_wh
        return 0

    def get_daily_average(self):
        total_duration_minutes, _ = self.get_minutes_since_until__midnight()
        if total_duration_minutes > 0:
            consumption_per_minute = self.daily_wh / total_duration_minutes
            projected_consumption_wh = consumption_per_minute * 1440
            return projected_consumption_wh / 24

        return 0

    def get_daily_wh(self):
        """Returns the current daily consumption in Wh."""
        return self.daily_wh

    def get_minutes_since_until__midnight(self):
        """Berechnet die vergangenen Minuten seit Mitternacht."""
        now = TimeUtilities.get_now()  # Lokale Zeit holen
        elapsed_minutes = now.hour * 60 + now.minute + now.second / 60  # Umrechnung in Minuten
        remaining_minutes = 1440 - elapsed_minutes  # Verbleibende Minuten bis Mitternacht
        return elapsed_minutes, remaining_minutes

    def reset_data(self):
        """Reset all tracked data to default values."""
        self.hourly_wh = 0
        self.daily_wh = 0
        self.hourly_start_time = time.time()
        self.last_value = 0
        self.last_grid_value = 0
        self.last_time = time.time()
        self.current_hour = time.localtime(time.time()).tm_hour
        self.current_day = time.localtime(time.time()).tm_yday
        self.curent_year = time.localtime(time.time()).tm_year

    def get_monthly_cost(self, year, month):
        """Berechnet die Gesamtkosten für einen bestimmten Monat anhand von yday."""
        start_day = sum(calendar.monthrange(year, m)[1] for m in range(1, month)) + 1
        end_day = start_day + calendar.monthrange(year, month)[1] - 1

        # Summe der Kosten für alle yday im Bereich
        return sum(self.energy_costs_by_day.get(day, 0) for day in range(start_day, end_day + 1))
