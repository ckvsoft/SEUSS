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

from datetime import datetime

class Solardata:
    """
    Solar data container.
    Stores PV forecast, current yield, sunrise/sunset info, battery state, etc.
    All methods are in English and compatible with OpenMeteo class.
    """

    def __init__(self):
        # Sunrise / Sunset
        self.sunrise_current_day = None
        self.sunset_current_day = None
        self.sunrise_tomorrow_day = None
        self.sunset_tomorrow_day = None
        self.sun_time_today_minutes = None
        self.sun_time_tomorrow_minutes = None

        # PV yields
        self.total_current_hour = 0.0
        self.total_current_day = 0.0
        self.total_tomorrow_day = 0.0
        self.current_hour_forecast = 0.0
        self.current_hour_solar_yield = 0.0

        # Panel / system info
        self.power_peak = 0.0

        # Battery / SOC info
        self.need_soc = 0
        self.soc = 0
        self.battery_capacity = 0
        self.battery_minimum_soc_limit = 5
        self.battery_current_voltage = 0.0

    # --------------------------------------------------
    # Time-related updates
    # --------------------------------------------------
    def outside_sun_hours(self):
        current_datetime = datetime.now()
        current_time = current_datetime.time()
        try:
            sunrise_time = datetime.strptime(self.sunrise_current_day, "%Y-%m-%dT%H:%M").time()
            sunset_time = datetime.strptime(self.sunset_tomorrow_day, "%Y-%m-%dT%H:%M").time()
        except Exception:
            return True  # assume outside if no data

        if sunrise_time < sunset_time:
            return current_time < sunrise_time or current_time > sunset_time
        else:
            return not (sunrise_time < current_time < sunset_time)

    def update_sunrise_current_day(self, sunrise):
        self.sunrise_current_day = sunrise

    def update_sunset_current_day(self, sunset):
        self.sunset_current_day = sunset

    def update_sunrise_tomorrow_day(self, sunrise):
        self.sunrise_tomorrow_day = sunrise

    def update_sunset_tomorrow_day(self, sunset):
        self.sunset_tomorrow_day = sunset

    def update_sun_time_today(self, minutes):
        self.sun_time_today_minutes = minutes

    def update_sun_time_tomorrow(self, minutes):
        self.sun_time_tomorrow_minutes = minutes

    # --------------------------------------------------
    # PV yield updates
    # --------------------------------------------------
    def update_total_current_hour(self, value):
        self.total_current_hour = value

    def update_total_current_day(self, value):
        self.total_current_day = value

    def update_total_tomorrow_day(self, value):
        self.total_tomorrow_day = value

    def update_current_hour_forecast(self, value):
        self.current_hour_forecast = value

    def update_current_hour_solar_yield(self, value):
        self.current_hour_solar_yield = value

    def update_power_peak(self, value):
        self.power_peak = value

    # --------------------------------------------------
    # Battery / SOC updates
    # --------------------------------------------------
    def update_need_soc(self, percentage):
        self.need_soc = round(percentage / 5) * 5

    def update_soc(self, percentage):
        self.soc = percentage

    def update_battery_capacity(self, capacity):
        self.battery_capacity = capacity

    def update_battery_minimum_soc_limit(self, limit):
        self.battery_minimum_soc_limit = limit

    def update_battery_current_voltage(self, voltage):
        self.battery_current_voltage = voltage
