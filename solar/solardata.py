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

class Solardata:
    def __init__(self):
        self.sunrise = None
        self.sunset = None
        self.sun_time_today_minutes = None
        self.sun_time_tomorrow_minutes = None
        self.total_current_hour = None
        self.total_current_day = None
        self.total_tomorrow_day = None
        self.power_peak = 0.0

    def update_sunrise(self, sunrise):
        self.sunrise = sunrise

    def update_sunset(self, sunset):
        self.sunset = sunset

    def update_sun_time_today(self, sun_time_today_minutes):
        self.sun_time_today_minutes = sun_time_today_minutes

    def update_sun_time_tomorrow(self, sun_time_tomorrow_minutes):
        self.sun_time_tomorrow_minutes = sun_time_tomorrow_minutes

    def update_total_current_hour(self, total_current_hour):
        self.total_current_hour = total_current_hour

    def update_total_current_day(self, total_current_day):
        self.total_current_day = total_current_day

    def update_total_tomorrow_day(self, total_tomorrow_day):
        self.total_tomorrow_day = total_tomorrow_day

    def update_power_peak(self, peak):
        self.power_peak = peak
