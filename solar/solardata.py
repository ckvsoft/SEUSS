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

from datetime import datetime, time

class Solardata:
    def __init__(self):
        self.sunrise_current_day = None
        self.sunset_current_day = None
        self.sunrise_tomorrow_day = None
        self.sunset_tomorrow_day = None
        self.sun_time_today_minutes = None
        self.sun_time_tomorrow_minutes = None
        self.total_current_hour = None
        self.total_current_hour_real = None
        self.total_current_day = None
        self.total_tomorrow_day = None
        self.total_seuss_current_day = None
        self.total_seuss_tomorrow_day = None
        self.power_peak = 0.0
        self.need_soc = 0
        self.soc = 0
        self.scheduler_soc = 0
        self.battery_capacity = 0
        self.battery_minimum_soc_limit = 5
        self.battery_current_voltage = None
        self.current_cloudcover = 0
        self.current_hour_forcast = 0
        self.abort_solar = True

    def outside_sun_hours(self):
        current_datetime = datetime.now()
        current_time = current_datetime.time()

        # Konvertieren Sie die Zeitzeichenfolge in ein datetime-Objekt
        sunrise_datetime = datetime.strptime(self.sunrise_current_day, "%Y-%m-%dT%H:%M")
        sunset_datetime = datetime.strptime(self.sunset_tomorrow_day, "%Y-%m-%dT%H:%M")

        # Extrahieren Sie die Zeit aus den datetime-Objekten
        sunrise_time = sunrise_datetime.time()
        sunset_time = sunset_datetime.time()

        # Wenn Sonnenuntergang nach Sonnenaufgang liegt, sind wir außerhalb der Sonnenstunden,
        # wenn die aktuelle Zeit vor Sonnenaufgang oder nach Sonnenuntergang liegt.
        # Andernfalls sind wir innerhalb der Sonnenstunden.
        if sunrise_time < sunset_time:
            return current_time < sunrise_time or current_time > sunset_time
        else:
            # Wenn Sonnenuntergang vor Sonnenaufgang liegt, sind wir innerhalb der Sonnenstunden,
            # wenn die aktuelle Zeit nicht zwischen Sonnenuntergang und Sonnenaufgang liegt.
            # Andernfalls sind wir außerhalb der Sonnenstunden.
            return not (sunrise_time < current_time < sunset_time)

    def update_sunrise_current_day(self, sunrise):
        self.sunrise_current_day = sunrise

    def update_sunset_current_day(self, sunset):
        self.sunset_current_day = sunset

    def update_sunrise_tomorrow_day(self, sunrise):
        self.sunrise_tomorrow_day = sunrise

    def update_sunset_tomorrow_day(self, sunset):
        self.sunset_tomorrow_day = sunset

    def update_sun_time_today(self, sun_time_today_minutes):
        self.sun_time_today_minutes = sun_time_today_minutes

    def update_sun_time_tomorrow(self, sun_time_tomorrow_minutes):
        self.sun_time_tomorrow_minutes = sun_time_tomorrow_minutes

    def update_total_current_hour(self, total_current_hour):
        self.total_current_hour = total_current_hour

    def update_total_current_hour_real(self, total_current_hour):
        self.total_current_hour_real = total_current_hour

    def update_total_current_day(self, total_current_day):
        self.total_current_day = total_current_day

    def update_total_tomorrow_day(self, total_tomorrow_day):
        self.total_tomorrow_day = total_tomorrow_day

    def update_total_seuss_current_day(self, total_current_day):
        self.total_seuss_current_day = total_current_day

    def update_total_seuss_tomorrow_day(self, total_tomorrow_day):
        self.total_seuss_tomorrow_day = total_tomorrow_day

    def update_power_peak(self, peak):
        self.power_peak = peak

    def update_need_soc(self, percentage):
        self.need_soc = round(percentage / 5) * 5

    def update_soc(self, percentage):
        self.soc = percentage

    def update_scheduler_soc(self, percentage):
        self.scheduler_soc = percentage

    def update_battery_capacity(self, capacity):
        self.battery_capacity = capacity

    def update_battery_minimum_soc_limit(self, limit):
        self.battery_minimum_soc_limit = limit

    def update_battery_current_voltage(self, voltage):
        self.battery_current_voltage = voltage

    def update_abort_solar(self, abort):
        self.abort_solar = abort

    def update_current_cloudcover(self, clouds):
        self.current_cloudcover = clouds

    def update_current_hour_forcast(self, value):
        self.current_hour_forcast = value
