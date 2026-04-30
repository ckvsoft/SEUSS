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
    the day-so-far measured yield, used by:

      * solar/openmeteo.py        -- writes forecast / sun-time fields,
                                     reads pv_measured_today_wh for the
                                     adjustment-factor learning logic
      * core/conditions.py        -- reads sunrise_tomorrow_day,
                                     forecast_today_wh, forecast_tomorrow_wh
                                     for the solar abort condition
      * core/seusscore.py         -- writes pv_measured_today_wh from
                                     the authoritative PowerConsumption
                                     daily_pv_wh value (GX-bus integrated)

    Naming history: the field now called `pv_measured_today_wh` was
    previously `current_hour_solar_yield`, fed from the sum of inverter
    forward-counters. That sum drifted ~25% from the actual PV yield
    (e.g. 26500 Wh vs ~21000 Wh real), which both poisoned the stats
    page and biased the openmeteo learning loop. The authoritative
    source is now `PowerConsumption.daily_pv_wh`, which integrates
    live PV power on the GX bus and matches both the Victron VRM total
    and the home-page "PV today" tile.

    Similarly `forecast_today_wh` / `forecast_tomorrow_wh` were
    previously `total_current_day` / `total_tomorrow_day` -- the new
    names match the statsmanager keys that have always been correct.

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

        # PV yields (Wh).
        #
        # forecast_today_wh is a hybrid: pv_measured_today_wh (actual,
        # so far) plus the adjusted forecast for the rest of the day.
        # forecast_tomorrow_wh is a pure forecast.
        # pv_measured_today_wh is the authoritative measured yield
        # since 00:00, sourced from PowerConsumption.daily_pv_wh.
        self.forecast_today_wh = 0.0
        self.forecast_tomorrow_wh = 0.0
        self.pv_measured_today_wh = 0.0

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
    def update_forecast_today_wh(self, value):
        self.forecast_today_wh = value

    def update_forecast_tomorrow_wh(self, value):
        self.forecast_tomorrow_wh = value

    def update_pv_measured_today_wh(self, value):
        self.pv_measured_today_wh = value
