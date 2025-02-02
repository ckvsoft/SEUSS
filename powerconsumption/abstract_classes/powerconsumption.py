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
        self.last_time = None   # Last timestamp (seconds since epoch)

        self.hourly_wh = 0          # Consumption for the current hour in kWh
        self.hourly_start_time = time.time()  # Start time of the current hour

        self.daily_wh = 0           # Daily consumption in kWh
        self.current_hour = time.localtime(time.time()).tm_hour
        self.current_day = time.localtime(time.time()).tm_yday

        # Initialized variables
        self.P_AC_consumption_L1 = self.P_AC_consumption_L2 = self.P_AC_consumption_L3 = None
        self.number_of_phases = 3  # Default number of phases, adjust if needed
        self.current_power = 0

        self.data_file = "consumption_data.json"
        self.load_data()

        self.thread = None
        self.average = (0,0)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
            self.logger.log_debug(f"{self.__class__.__name__} started with interval {self.interval_duration} minutes.")
        else:
            self.logger.log_debug(f"{self.__class__.__name__} is already running.")

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

    def load_data(self):
        self.daily_wh = self.statsmanager.get_data("powerconsumption", "daily_wh") or 0.0

        hourly_wh_list = self.statsmanager.get_data("powerconsumption", "hourly_wh")
        self.hourly_wh, self.hourly_start_time = hourly_wh_list if isinstance(hourly_wh_list, tuple) and len(hourly_wh_list) == 2 else (0, time.time())

        average_list = self.statsmanager.get_data("powerconsumption", "average")
        self.average = average_list if isinstance(average_list, tuple) and len(average_list) == 2 else (0, 0)

        last_value_list = self.statsmanager.get_data("powerconsumption", "last_power_value")
        self.last_value, self.last_time = last_value_list if isinstance(last_value_list, tuple) and len(last_value_list) == 2 else (0, time.time())

        """Lädt gespeicherte Daten aus einer JSON-Datei."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r") as file:
                    data = json.load(file)
                    self.hourly_wh = data.get("hourly_wh", 0)
                    self.hourly_start_time = data.get("hourly_start_time", time.time())
                    self.last_value = data.get("last_value", 0)
                    self.last_time = data.get("last_time", time.time())
                    self.average = data.get("average", (0,0))
            except json.JSONDecodeError:
                self.logger.log_error("Corrupted JSON file detected. Resetting data.")
                self.reset_data()

    def save_data(self, logging=False):
        self.statsmanager.set_status_data("powerconsumption","hourly_wh", (self.hourly_wh, self.hourly_start_time))
        self.statsmanager.set_status_data("powerconsumption","average", self.average)
        self.logger.log_debug(f"save ... set average: {self.average}")
        self.statsmanager.set_status_data("powerconsumption","last_power_value", (self.last_value, self.last_time))
        if logging:
            self.logger.log_debug("data saved.")

        backup_file = f"{self.data_file}.backup"
        try:
            if os.path.exists(self.data_file):
                os.remove(self.data_file)
            if os.path.exists(backup_file):
                os.remove(backup_file)
        except Exception as e:
            self.logger.log_error(f"Error remove file: {e}")

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

        self.statsmanager.update_percent_status_data("powerconsumption", "average", self.average)
        self.logger.log_debug(f"save ... update average: {self.average}")
        self.statsmanager.update_percent_status_data("powerconsumption", "hourly_watt_average", value)
        self.statsmanager.update_percent_status_data("powerconsumption", "daily_watt_average", self.get_daily_average())
        self.statsmanager.set_status_data("powerconsumption","daily_wh", self.daily_wh)

        # Speichert die Daten
        self.save_data()

    def save_day(self):
        print(f"Daily consumption: {self.daily_wh:.4f} Wh")
        self.statsmanager.update_percent_status_data("powerconsumption", "daily_wh_average", self.get_daily_average())
        self.statsmanager.update_percent_status_data("powerconsumption", "daily_watt_average", self.get_daily_average())

        # Speichert die Daten
        self.save_data()

    def update(self, power, timestamp):
        """Aktualisiert den Verbrauch basierend auf neuer Leistung und Zeit."""
        # Setze den Startwert, wenn es die erste Messung ist
        if self.last_time is None:
            self.last_value = power
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

        # Speichern der Daten alle 5 Minuten
        current_minute = time.localtime(timestamp).tm_min
        if current_minute in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55] and current_minute != self.last_minute:
            self.save_data()
            self.last_minute = current_minute

        # Aktualisieren der letzten Werte
        self.last_value = power
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

        if missing_data:
            self.logger.log_debug(f"Missing data: {', '.join(missing_data)}")
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
        self.last_time = time.time()
        self.current_hour = time.localtime(time.time()).tm_hour
        self.current_day = time.localtime(time.time()).tm_yday
