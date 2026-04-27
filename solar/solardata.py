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


class Solardata:
    """
    Solar data container -- holds the OpenMeteo forecast outputs and
    the day-so-far yield, used by:

      * solar/openmeteo.py        -- writes forecast / sun-time fields
      * core/conditions.py        -- reads sunrise_tomorrow_day,
                                     total_current_day, total_tomorrow_day
                                     for the solar abort condition
      * core/seusscore.py         -- writes current_hour_solar_yield
                                     after summing inverter Wh

    Earlier revisions of this class had a `Battery / SOC` block plus a
    `need_soc` value pushed through SolarBatteryCalculator. Both were
    removed when the calculator was deleted -- the abort logic in
    conditions.py now does the SOC math itself against the live
    essunit, which avoids the calculator's brittle "required SOC"
    formula.
    """

    def __init__(self):
        # Sunrise / sunset (ISO strings "YYYY-MM-DDTHH:MM" in local tz,
        # as returned by OpenMeteo when called with timezone=...).
        # Only sunrise_tomorrow_day is currently consumed (by the solar
        # abort condition in conditions.py); the other three are kept
        # as a symmetric pair so future code can grab "today's
        # sunset" etc. without re-plumbing the OpenMeteo loop.
        self.sunrise_current_day = None
        self.sunset_current_day = None
        self.sunrise_tomorrow_day = None
        self.sunset_tomorrow_day = None

        # PV yields (Wh)
        self.total_current_day = 0.0    # measured-so-far + forecast-rest
        self.total_tomorrow_day = 0.0   # forecast tomorrow
        self.current_hour_solar_yield = 0.0  # measured Wh today, summed across inverters

    # --------------------------------------------------
    # Time-related updates
    # --------------------------------------------------
    def update_sunrise_current_day(self, sunrise):
        self.sunrise_current_day = sunrise

    def update_sunset_current_day(self, sunset):
        self.sunset_current_day = sunset

    def update_sunrise_tomorrow_day(self, sunrise):
        self.sunrise_tomorrow_day = sunrise

    def update_sunset_tomorrow_day(self, sunset):
        self.sunset_tomorrow_day = sunset

    # --------------------------------------------------
    # PV yield updates
    # --------------------------------------------------
    def update_total_current_day(self, value):
        self.total_current_day = value

    def update_total_tomorrow_day(self, value):
        self.total_tomorrow_day = value

    def update_current_hour_solar_yield(self, value):
        self.current_hour_solar_yield = value
