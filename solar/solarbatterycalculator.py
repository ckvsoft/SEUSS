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

class SolarBatteryCalculator:
    def __init__(self, solardata):
        self.solardata = solardata
        self.solar_peak_power = solardata.power_peak
        self.average_consumption = 0.0
        self.efficiency = 0.0

        average_consumption_list = StatsManager.get_data('gridmeters', 'average')
        if average_consumption_list is not None:
            self.average_consumption = round(average_consumption_list[0], 2)

        efficiency_data = StatsManager.get_data('solar', 'efficiency')
        if efficiency_data is not None:
            self.efficiency = round(efficiency_data[0], 2)

    def calculate_battery_percentage(self):
        try:

            sunset_time = datetime.strptime(self.solardata.sunset_current_day, "%Y-%m-%dT%H:%M").time()

            current_time = TimeUtilities.get_now().time()
            if current_time > sunset_time:
                forecast = self.solardata.total_tomorrow_day
                daylight_hours = self.solardata.sun_time_tomorrow_minutes
            else:
                forecast = self.solardata.total_current_day
                daylight_hours = self.solardata.sun_time_today_minutes

            max_solar_per_hour = (self.solar_peak_power * self.efficiency) / 100
            if forecast is not None and forecast < self.solar_peak_power:
                max_solar_per_hour = (forecast * self.efficiency) / 100


            actual_solar_during_daylight = min(max_solar_per_hour * daylight_hours / 60, forecast)

            # Überprüfen, ob die tatsächliche Solarproduktion den Verbrauch während der Sonnenstunden übersteigt
            if actual_solar_during_daylight >= self.average_consumption:
                return 0  # Der Akku muss während der Sonnenstunden nicht geladen werden

            # Berechnen, wie viel Strom aus Akkus benötigt wird, um den Rest des Verbrauchs zu decken
            battery_power_needed = self.average_consumption - actual_solar_during_daylight

            # Berechnen des Prozentsatzes aus Akkus
            battery_percentage = (battery_power_needed / self.average_consumption) * 100

            # Sicherstellen, dass der Prozentsatz zwischen 0 und 100 liegt
            battery_percentage = max(min(battery_percentage, 100), 0)

            return round(battery_percentage, 2)

        except TypeError:
            return 0
