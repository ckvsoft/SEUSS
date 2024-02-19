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

from core.statsmanager import StatsManager

class SolarBatteryCalculator:
    def __init__(self, solardata):
        self.solar_production = solardata.total_current_day
        self.solar_peak_power = solardata.power_peak
        self.daylight_hours = solardata.sun_time_today_minutes
        self.average_consumption = 0.0
        self.efficiency = 0.0

        average_consumption = StatsManager.get_data('gridmeters', 'forward_start')
        if average_consumption is not None:
            self.average_consumption = round(average_consumption, 2)

        efficiency_data = StatsManager.get_data('solar', 'efficiency')
        if efficiency_data is not None:
            self.efficiency = round(efficiency_data[0], 2)

    def calculate_battery_percentage(self):
        try:
            max_solar_per_hour = (self.solar_peak_power * self.efficiency) / 100

            # Tatsächliche Solarproduktion während der Sonnenstunden berechnen
            actual_solar_during_daylight = min(max_solar_per_hour * self.daylight_hours / 60, self.solar_production)

            # Überprüfen, ob die tatsächliche Solarproduktion den Verbrauch während der Sonnenstunden übersteigt
            if actual_solar_during_daylight >= self.average_consumption:
                return 0  # Der Akku muss während der Sonnenstunden nicht geladen werden

            # Berechnen, wie viel Strom aus Akkus benötigt wird, um den Rest des Verbrauchs zu decken
            battery_power_needed = self.average_consumption - actual_solar_during_daylight

            # Berechnen des Prozentsatzes aus Akkus
            battery_percentage = (battery_power_needed / self.average_consumption) * 100

            # Sicherstellen, dass der Prozentsatz zwischen 0 und 100 liegt
            battery_percentage = max(min(battery_percentage, 100), 0)

            return battery_percentage

        except TypeError:
            return 0
