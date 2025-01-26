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

class PowerConsumptionBase:
    def __init__(self, interval_duration=5):
        self.interval_duration = interval_duration
        self.logger = CustomLogger()
        self.statsmanager = StatsManager()
        self.running = False
        self.last_minute = None
        self.last_value = None  # Last power value in watts
        self.last_time = None   # Last timestamp (seconds since epoch)

        self.hourly_kwh = 0          # Consumption for the current hour in kWh
        self.hourly_count = 0        # Number of measurements in the current hour
        self.hourly_start_time = None  # Start time of the current hour

        self.daily_kwh = 0           # Daily consumption in kWh
        self.current_hour = None     # Current hour
        self.current_day = None      # Current day

        # Initialized variables
        self.P_AC_consumption_L1 = self.P_AC_consumption_L2 = self.P_AC_consumption_L3 = None
        self.number_of_phases = 3  # Default number of phases, adjust if needed
        self.current_power = 0

        self.data_file = "consumption_data.json"
        self.load_data()

        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
            self.logger.log_debug(f"{self.__class__.__name__} started with interval {self.interval_duration} minutes.")
        else:
            self.logger.log_debug(f"{self.__class__.__name__} is already running.")

    def stop(self):
        if self.thread is not None:
            self.logger.log_debug(f"{self.__class__.__name__} is stopping...")
            self.thread.join()  # Wait until the thread finishes
            self.thread = None
        else:
            self.logger.log_debug(f"{self.__class__.__name__} is not running.")

    def run(self):
        """Main process - Implementation in derived classes."""
        raise NotImplementedError("This method must be implemented in the derived class.")

    def load_data(self):
        """Loads saved data from a JSON file."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r") as file:
                    data = json.load(file)
                    self.hourly_kwh = data.get("hourly_kwh", 0)
                    self.daily_kwh = data.get("daily_kwh", 0)
                    self.hourly_start_time = data.get("hourly_start_time", time.time())
                    self.last_value = data.get("last_value", 0)
                    self.last_time = data.get("last_time", time.time())
                    self.current_hour = data.get("current_hour", time.localtime(time.time()).tm_hour)
                    self.current_day = data.get("current_day", time.localtime(time.time()).tm_yday)
            except json.JSONDecodeError:
                self.logger.log_error("Corrupted JSON file detected. Resetting data.")
                self.reset_data()

    def save_data(self):
        """Saves the current status to a JSON file."""
        data = {
            "hourly_kwh": self.hourly_kwh,
            "daily_kwh": self.daily_kwh,
            "hourly_start_time": self.hourly_start_time,
            "last_value": self.last_value,
            "last_time": self.last_time,
            "current_hour": self.current_hour,
            "current_day": self.current_day
        }
        backup_file = f"{self.data_file}.backup"
        try:
            if os.path.exists(self.data_file):
                os.replace(self.data_file, backup_file)  # Backup der aktuellen Datei
            with open(self.data_file, "w") as file:
                json.dump(data, file, indent=4)
        except Exception as e:
            self.logger.log_error(f"Error saving data: {e}")
            if os.path.exists(backup_file):
                os.replace(backup_file, self.data_file)  # Wiederherstellung aus Backup

    def save_hour(self):
        """Saves the average of the current hour and calls save_data."""
        elapsed_time = (self.last_time - self.hourly_start_time) / 3600  # Elapsed time in hours
        if elapsed_time > 0:
            avg_kwh = self.hourly_kwh / elapsed_time
        else:
            avg_kwh = 0
        print(f"Hourly average for hour {self.current_hour}: {avg_kwh:.4f} kWh")
        self.statsmanager.update_percent_status_data("powerconsumption", "hourly_watt_average", avg_kwh * 1000)

        # Save the data
        self.save_data()

    def save_day(self):
        """Saves the daily consumption and calls save_data."""
        print(f"Daily consumption: {self.daily_kwh:.4f} kWh")
        elapsed_time_in_hours = (time.time() - self.hourly_start_time) / 3600
        if elapsed_time_in_hours > 0:
            daily_forecast = (self.daily_kwh / elapsed_time_in_hours) * 24
            self.statsmanager.update_percent_status_data("powerconsumption", "daily_kwh_average", daily_forecast)
            print(f"Projected daily consumption: {daily_forecast:.4f} kWh")
        else:
            print("No projected data available.")

        # Save the data
        self.save_data()

    def get_hourly_average(self):
        """Calculates the projected hourly average."""
        elapsed_time_in_hours = (self.last_time - self.hourly_start_time) / 3600  # Elapsed time in hours
        if elapsed_time_in_hours > 0:
            # Project the hourly average based on the time already passed
            projected_kwh = self.hourly_kwh / elapsed_time_in_hours
            return projected_kwh
        return 0

    def get_daily_kwh(self):
        """Returns the current daily consumption."""
        return self.daily_kwh

    def update(self, power, timestamp):
        """Updates the consumption based on new power and time."""
        # Set the start point if it's the first measurement
        if self.last_time is None:
            self.last_value = power
            self.last_time = timestamp
            self.current_hour = time.localtime(timestamp).tm_hour
            self.current_day = time.localtime(timestamp).tm_yday
            self.hourly_start_time = timestamp
            return

        # Calculate the time interval in hours
        time_diff = (timestamp - self.last_time) / 3600  # Time difference in hours

        # Calculate the kWh consumption in this period
        kwh = (self.last_value * time_diff) / 1000  # Consumption in kWh
        self.hourly_kwh += kwh  # Add to the current hourly consumption
        self.daily_kwh += kwh   # Update daily consumption
        self.hourly_count += 1  # Count the measurement

        # Determine current hour and day
        current_minute = time.localtime(timestamp).tm_min
        current_hour = time.localtime(timestamp).tm_hour
        current_day = time.localtime(timestamp).tm_yday

        # Check if a new day has started
        if current_day != self.current_day:
            self.save_day()  # Save daily consumption
            self.current_day = current_day
            self.daily_kwh = 0  # Reset consumption for the new day

        # Check if a new hour has started
        if current_hour != self.current_hour:
            self.save_hour()  # Save average for the last hour
            self.current_hour = current_hour
            self.hourly_kwh = 0  # Reset consumption for the new hour
            self.hourly_count = 0
            self.hourly_start_time = timestamp

        if current_minute != self.last_minute and current_minute in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]:
            self.last_minute = current_minute
            self.save_data()

        # Update the last values
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

    def reset_data(self):
        """Reset all tracked data to default values."""
        self.hourly_kwh = 0
        self.daily_kwh = 0
        self.hourly_start_time = time.time()
        self.last_value = 0
        self.last_time = time.time()
        self.current_hour = time.localtime(time.time()).tm_hour
        self.current_day = time.localtime(time.time()).tm_yday
