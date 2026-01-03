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

            # Wir sammeln die Forecast-Werte separat
            total_today_forecast = 0.0
            total_tomorrow_forecast = 0.0
            current_hour_wh = 0.0
            inverter_efficiency = 0.88

            # Peak Power setzen
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
                except Exception:
                    continue

                hourly = data.get('hourly', {})
                daily = data.get('daily', {})
                dates = daily.get('time', [])
                t_idx = self.safe_date_index(dates, today_str, "today")
                tm_idx = self.safe_date_index(dates, tomorrow_str, "tomorrow")

                if t_idx is not None:
                    # Diese Updates MÜSSEN sein für den SOC Rechner
                    solar_data.update_sunrise_current_day(daily['sunrise'][t_idx])
                    solar_data.update_sunset_current_day(daily['sunset'][t_idx])
                    solar_data.update_sunrise_tomorrow_day(daily['sunrise'][tm_idx])
                    solar_data.update_sunset_tomorrow_day(daily['sunset'][tm_idx])
                    solar_data.update_sun_time_today(daily['sunshine_duration'][t_idx])
                    solar_data.update_sun_time_tomorrow(daily['sunshine_duration'][tm_idx])

                    area = panel.get('total_area', 0)
                    eff = panel.get('efficiency', 20) / 100
                    p_max_watt = panel.get('totPower', 0) * 1000
                    rad_list = hourly.get('global_tilted_irradiance', [])

                    # Berechnung Heute (kompletter Tag aus API Sicht)
                    for h in range(0, 24):
                        if h < len(rad_list):
                            rad = rad_list[h] or 0
                            damp = self.calculate_exponential_damping(h, panel)
                            val = min(rad * area * eff * damp, p_max_watt)
                            total_today_forecast += val
                            if h == now.hour:
                                current_hour_wh += val

                    # Berechnung Morgen
                    for h in range(24, 48):
                        if h < len(rad_list):
                            rad = rad_list[h] or 0
                            damp = self.calculate_exponential_damping(h % 24, panel)
                            total_tomorrow_forecast += min(rad * area * eff * damp, p_max_watt)

            # Lernfaktor
            adj = self.statsmanager.get_data("solar", "adjustment_factor") or 1.0
            if adj > 1.5 or adj < 0.5: adj = 1.0

            # Finale Werte berechnen
            final_today = total_today_forecast * inverter_efficiency * adj
            final_tomorrow = total_tomorrow_forecast * inverter_efficiency * adj

            # WICHTIG: Wir vergleichen mit dem, was schon in solar_data steht
            # Wenn die Inverter schon MEHR gemeldet haben (z.B. 3031 Wh),
            # dann nehmen wir diesen Ist-Wert als Minimum.
            measured_now = solar_data.total_current_day or 0.0
            if final_today < measured_now:
                final_today = measured_now

            # Zurückschreiben in das Objekt
            solar_data.update_total_current_day(round(final_today, 2))
            solar_data.update_total_tomorrow_day(round(final_tomorrow, 2))
            solar_data.update_total_current_hour(round(current_hour_wh * inverter_efficiency, 2))

            self.logger.log.info(
                f"Forecast: Today {solar_data.total_current_day} Wh, Tomorrow {solar_data.total_tomorrow_day} Wh")

            return solar_data.total_current_hour

        except Exception as e:
            self.logger.log.exception(f"Forecast failed: {e}")
            return 0.0

    def calculate_exponential_damping(self, hour, panel):
        m_loss = panel.get("damping_morning", 0.0)
        e_loss = panel.get("damping_evening", 0.0)
        loss = m_loss if hour < self.noon_hour else e_loss
        return max(0.0, min(1.0, 1.0 - loss))