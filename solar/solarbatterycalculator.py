#  -*- coding: utf-8 -*-

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

#
#  MIT License
#
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#
#
#  Project: [SEUSS -> Smart Ess Unit Spotmarket Switcher
#

from datetime import datetime
from core.statsmanager import StatsManager
from core.timeutilities import TimeUtilities
from core.log import CustomLogger

class SolarBatteryCalculator:
    def __init__(self, solardata):
        self.logger = CustomLogger()
        self.solardata = solardata
        self.solar_peak_power = solardata.power_peak * 1000
        self.average_consumption = 0.0
        self.efficiency = 0.0

        average_consumption_list = StatsManager.get_data('gridmeters', 'average')
        if average_consumption_list is not None:
            self.average_consumption = round(average_consumption_list[0], 2)

        efficiency_data = StatsManager.get_data('solar', 'efficiency')
        if efficiency_data is not None:
            self.efficiency = round(efficiency_data[0], 2)

    def calculate_full_capacity(self):
        if self.solardata.soc <= 0: return 0
        full_capacity = (self.solardata.battery_capacity / self.solardata.soc) * 100
        return full_capacity

    def calculate_battery_percentage(self):
        try:
            sunset_time = datetime.strptime(self.solardata.sunset_current_day, "%Y-%m-%dT%H:%M").time()

            current_time = TimeUtilities.get_now().time()
            current_date = TimeUtilities.get_now()

            if current_time > sunset_time:
                self.logger.log_debug("Use tomorrow_day forecast")
                forecast = self.solardata.total_tomorrow_day
                daylight_hours = self.solardata.sun_time_tomorrow_minutes / 60
                sunrise_tomorrow_date = datetime.strptime(self.solardata.sunrise_tomorrow_day, "%Y-%m-%dT%H:%M").astimezone(TimeUtilities.TZ)
                differenz = sunrise_tomorrow_date - current_date
            else:
                self.logger.log_debug("Use current_day forecast")
                forecast = self.solardata.total_current_day
                daylight_hours = self.solardata.sun_time_today_minutes / 60
                sunset_date = datetime.strptime(self.solardata.sunset_current_day, "%Y-%m-%dT%H:%M").astimezone(TimeUtilities.TZ)
                differenz = sunset_date - current_date

            max_solar_per_hour = (self.solar_peak_power * self.efficiency) / 100
            forecast_per_hour = 0.0
            if daylight_hours > 0.0:
                forecast_per_hour = ((forecast / daylight_hours) * self.efficiency) / 100
            if forecast is not None and forecast_per_hour < max_solar_per_hour:
                max_solar_per_hour = forecast_per_hour

            actual_solar_during_daylight = max_solar_per_hour * daylight_hours
            available_hours = differenz.total_seconds() / 3600

            # verbrauch bis sonnenuntergang oder verbrauch bis sonnenaufgang wenn nacht
            self.logger.log_debug(f"average_consumption {self.average_consumption} * available_hours: {available_hours}")
            average_consumption = self.average_consumption * available_hours
            # restliche battery capazität über minimum soc
            remaining_battery_soc = self.solardata.soc - self.solardata.battery_minimum_soc_limit

#            battery_power_needed = average_consumption - actual_solar_during_daylight

            actual_battery_capacity_wh = self.solardata.battery_capacity * self.solardata.battery_current_voltage
            full_voltage = 57.6 # self.solardata.battery_current_voltage / (self.solardata.soc/ 100)
            full_battery_capacity_wh = self.calculate_full_capacity() * full_voltage

            available_battery_capacity = ((full_battery_capacity_wh - actual_battery_capacity_wh) / 100) * remaining_battery_soc

            self.logger.log_info(f"Current Battery state: {self.solardata.battery_capacity} Ah, maximum: {round(self.calculate_full_capacity(),2)} Ah")

            # Überprüfen, ob die tatsächliche Solarproduktion den Verbrauch während der Sonnenstunden übersteigt
            if actual_solar_during_daylight >= average_consumption:
                self.logger.log_debug(f"return while {actual_solar_during_daylight} >= {average_consumption}")
                return self.solardata.battery_minimum_soc_limit  # Der Akku muss während der Sonnenstunden nicht geladen werden

            # Berechnen des verbleibenden Speicherplatzes in der Batterie
            remaining_battery_capacity = available_battery_capacity + actual_solar_during_daylight - average_consumption
            self.logger.log_debug(f"Remaining battery capacity: {remaining_battery_capacity}")
            battery_percentage = 0.0
            if remaining_battery_capacity < 0.0:
                battery_percentage = ((remaining_battery_capacity / full_battery_capacity_wh) * 100) * -1
                self.logger.log_debug(f"Battery percentage add: {battery_percentage}")

            battery_percentage = battery_percentage + self.solardata.battery_minimum_soc_limit
            self.logger.log_debug(f"Battery percentage: {battery_percentage}")

            # Berücksichtigung der verbleibenden Batteriekapazität
            battery_percentage = min(min(battery_percentage, 100), 100)

            return round(battery_percentage, 2)

        except TypeError:
            return 0
