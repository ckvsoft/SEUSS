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

#  -*- coding: utf-8 -*-

import requests
import time
from datetime import datetime, timedelta
import pytz
from requests.exceptions import RequestException
from core.config import Config
from core.log import CustomLogger
from core.statsmanager import StatsManager
from solar.solardata import Solardata


class OpenMeteo:
    def __init__(self):
        self.config = Config()
        self.logger = CustomLogger()
        self.statsmanager = StatsManager()
        self.panels = self.config.get_pv_panels()
        self.noon_hour = 12

    def safe_date_index(self, dates, target_date, label):
        try:
            return dates.index(target_date)
        except ValueError:
            return None

    def forecast(self, solar_data: Solardata):
        try:
            timezone = pytz.timezone(self.config.time_zone)
            now = datetime.now(timezone)
            today_str = now.strftime('%Y-%m-%d')
            tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')

            sum_forecast_rest_today = 0.0
            sum_forecast_tomorrow = 0.0
            sum_current_hour_wh = 0.0
            inverter_efficiency = 0.88

            solar_data.power_peak = sum(panel['totPower'] for panel in self.panels)

            for panel in self.panels:
                if not panel.get('enabled', True): continue

                url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={panel['locLat']}&longitude={panel['locLong']}"
                    f"&hourly=global_tilted_irradiance"
                    f"&daily=sunrise,sunset,sunshine_duration"
                    f"&timezone={self.config.time_zone}&forecast_days=2"
                    f"&tilt={panel['angle']}&azimuth={panel['direction']}"
                )

                try:
                    r = requests.get(url, timeout=10)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    self.logger.log.error(f"API Error: {e}")
                    continue

                hourly = data.get('hourly', {})
                daily = data.get('daily', {})
                rad_list = hourly.get('global_tilted_irradiance', [])
                dates = daily.get('time', [])

                t_idx = self.safe_date_index(dates, today_str, "today")
                tm_idx = self.safe_date_index(dates, tomorrow_str, "tomorrow")
                if t_idx is None: continue

                area = panel.get('total_area', 0)
                eff = panel.get('efficiency', 20) / 100
                p_max_watt = panel.get('totPower', 0) * 1000
                h_now = now.hour

                # Roh-Berechnung für dieses Panel
                p_rest_today = 0.0
                p_tomorrow = 0.0

                for h in range(h_now + 1, 24):
                    if h < len(rad_list):
                        damp = self.calculate_exponential_damping(h, panel)
                        p_rest_today += min(rad_list[h] * area * eff * damp, p_max_watt)

                for h in range(24, 48):
                    if h < len(rad_list):
                        damp = self.calculate_exponential_damping(h % 24, panel)
                        p_tomorrow += min(rad_list[h] * area * eff * damp, p_max_watt)

                self.logger.log.debug(
                    f"Panel {panel.get('name')}: Rest Today {p_rest_today:.0f}Wh, Tomorrow {p_tomorrow:.0f}Wh (Raw)")

                sum_forecast_rest_today += p_rest_today
                sum_forecast_tomorrow += p_tomorrow

            # --- DEN LERNFAKTOR RESETTEN ---
            # Wenn der Faktor völlig gaga ist (über 2.0 oder unter 0.2), setzen wir ihn hart zurück
            adj = self.statsmanager.get_data("solar", "adjustment_factor") or 1.0
            if adj > 2.0 or adj < 0.2:
                self.logger.log.info(f"Resetting crazy adjustment factor: {adj}")
                adj = 1.0
                self.statsmanager.set_status_data("solar", "adjustment_factor", 1.0)

            measured_today_total = solar_data.current_hour_solar_yield or 0.0

            final_today = measured_today_total + (sum_forecast_rest_today * inverter_efficiency * adj)
            final_tomorrow = sum_forecast_tomorrow * inverter_efficiency * adj

            solar_data.update_total_current_day(round(final_today, 2))
            solar_data.update_total_tomorrow_day(round(final_tomorrow, 2))

            self.logger.log.info(f"FINAL: Today {final_today:.2f} Wh, Tomorrow {final_tomorrow:.2f} Wh (Adj: {adj})")

            return sum_current_hour_wh

        except Exception as e:
            self.logger.log.exception(f"Forecast failed: {e}")
            return 0.0

    def calculate_exponential_damping(self, hour, panel):
        m_loss = panel.get("damping_morning", 0.0)
        e_loss = panel.get("damping_evening", 0.0)
        return 1.0 - (m_loss if hour < self.noon_hour else e_loss)