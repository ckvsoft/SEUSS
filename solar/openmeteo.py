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
        self.noon_hour = 12.0

    def safe_date_index(self, dates, target_date, label):
        try:
            return dates.index(target_date)
        except ValueError:
            self.logger.log.error(f"Date {target_date} ({label}) not found in API response.")
            return None

    def calculate_exponential_damping(self, hour, panel, sunrise_str, sunset_str):
        try:
            # Convert ISO strings to decimal hours
            sr_dt = datetime.fromisoformat(sunrise_str)
            ss_dt = datetime.fromisoformat(sunset_str)

            sr_h = sr_dt.hour + (sr_dt.minute / 60.0)
            ss_h = ss_dt.hour + (ss_dt.minute / 60.0)

            if hour <= sr_h or hour >= ss_h:
                return 0.0

            m_loss = panel.get("damping_morning", 0.0)
            e_loss = panel.get("damping_evening", 0.0)

            if hour < self.noon_hour:
                divisor = (self.noon_hour - sr_h)
                factor = (self.noon_hour - hour) / divisor if divisor > 0 else 0
                damping = 1.0 - (m_loss * max(0.0, min(1.0, factor)))
            else:
                divisor = (ss_h - self.noon_hour)
                factor = (hour - self.noon_hour) / divisor if divisor > 0 else 0
                damping = 1.0 - (e_loss * max(0.0, min(1.0, factor)))

            return max(0.0, min(1.0, damping))
        except Exception:
            return 1.0

    def forecast(self, solar_data: Solardata):
        try:
            timezone = pytz.timezone(self.config.time_zone)
            now = datetime.now(timezone)
            today_str = now.strftime('%Y-%m-%d')
            tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')

            sum_forecast_past_today_raw = 0.0
            sum_forecast_rest_today_raw = 0.0
            sum_forecast_tomorrow_raw = 0.0
            sum_current_hour_wh_raw = 0.0
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

                data = None
                for attempt in range(3):
                    try:
                        r = requests.get(url, timeout=10)
                        r.raise_for_status()
                        data = r.json()
                        break
                    except (RequestException, Exception) as e:
                        if attempt < 2:
                            time.sleep(1);
                            continue
                        else:
                            self.logger.log.error(f"API Error after 3 attempts: {e}")

                if not data: continue

                hourly = data.get('hourly', {})
                daily = data.get('daily', {})
                rad_list = hourly.get('global_tilted_irradiance', [])
                dates = daily.get('time', [])

                t_idx = self.safe_date_index(dates, today_str, "today")
                tm_idx = self.safe_date_index(dates, tomorrow_str, "tomorrow")

                if t_idx is not None and tm_idx is not None:
                    sr_t = daily['sunrise'][t_idx]
                    ss_t = daily['sunset'][t_idx]
                    sr_tm = daily['sunrise'][tm_idx]
                    ss_tm = daily['sunset'][tm_idx]

                    # SOC related updates
                    solar_data.update_sunrise_current_day(sr_t)
                    solar_data.update_sunset_current_day(ss_t)
                    solar_data.update_sunrise_tomorrow_day(sr_tm)
                    solar_data.update_sunset_tomorrow_day(ss_tm)
                    solar_data.update_sun_time_today(daily['sunshine_duration'][t_idx])
                    solar_data.update_sun_time_tomorrow(daily['sunshine_duration'][tm_idx])

                    area = panel.get('total_area', 0)
                    eff = panel.get('efficiency', 20) / 100
                    p_max = panel.get('totPower', 0) * 1000
                    h_now = now.hour

                    # 1. Past hours raw forecast
                    for h in range(0, h_now):
                        if h < len(rad_list):
                            damp = self.calculate_exponential_damping(h, panel, sr_t, ss_t)
                            sum_forecast_past_today_raw += min((rad_list[h] or 0) * area * eff * damp, p_max)

                    # 2. Current hour raw
                    if h_now < len(rad_list):
                        damp = self.calculate_exponential_damping(h_now, panel, sr_t, ss_t)
                        sum_current_hour_wh_raw += min((rad_list[h_now] or 0) * area * eff * damp, p_max)

                    # 3. Future hours raw
                    for h in range(h_now + 1, 24):
                        if h < len(rad_list):
                            damp = self.calculate_exponential_damping(h, panel, sr_t, ss_t)
                            sum_forecast_rest_today_raw += min((rad_list[h] or 0) * area * eff * damp, p_max)

                    # 4. Tomorrow raw
                    for h in range(24, 48):
                        if h < len(rad_list):
                            damp = self.calculate_exponential_damping(h % 24, panel, sr_tm, ss_tm)
                            sum_forecast_tomorrow_raw += min((rad_list[h] or 0) * area * eff * damp, p_max)

            # --- Learning Logic ---
            measured_today = solar_data.current_hour_solar_yield or 0.0
            theoretical_past_net = sum_forecast_past_today_raw * inverter_efficiency

            # Load existing adj
            adj = self.statsmanager.get_data("solar", "adjustment_factor") or 1.0

            if theoretical_past_net > 200:
                adj = max(0.2, min(2.0, measured_today / theoretical_past_net))
                # Set the data (assuming statsmanager handles persistence)
                # self.statsmanager.set_data(...) if needed, otherwise we just use the local adj for calculations

            # --- Apply Factor ---
            rest_today_final = sum_forecast_rest_today_raw * inverter_efficiency * adj
            total_today = measured_today + rest_today_final
            total_tomorrow = sum_forecast_tomorrow_raw * inverter_efficiency * adj

            solar_data.update_total_current_day(round(total_today, 2))
            solar_data.update_total_tomorrow_day(round(total_tomorrow, 2))
            solar_data.update_total_current_hour(round(sum_current_hour_wh_raw * inverter_efficiency, 2))

            self.logger.log.info(
                f"Forecast: Today {total_today:.2f} Wh (Measured: {measured_today:.0f}, Rest: {rest_today_final:.0f}), "
                f"Tomorrow {total_tomorrow:.2f} Wh (Adj: {adj:.2f})"
            )

            return solar_data.total_current_hour

        except Exception as e:
            self.logger.log.exception(f"Forecast failed: {e}")
            return 0.0