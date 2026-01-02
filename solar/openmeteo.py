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

import requests
from datetime import datetime, timedelta
import pytz
from requests.exceptions import RequestException
from core.config import Config
from core.log import CustomLogger
from core.statsmanager import StatsManager
from solar.solardata import Solardata


class OpenMeteo:
    """
    PV forecast engine with configurable morning/evening damping.
    Today forecast = measured_today + remaining hours forecast (dynamic adjustment),
    Tomorrow forecast = realistic sum of hourly forecast, clamped to max panel capacity
    and adjusted based on actual today yield.
    """

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
            self.logger.log.error(f"[OpenMeteo] Missing date '{target_date}' for {label}. Available: {dates}")
            return None

    def forecast(self, solar_data: Solardata):
        try:
            timezone = pytz.timezone(self.config.time_zone)
            now = datetime.now(timezone)
            today_str = now.strftime('%Y-%m-%d')
            tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')

            total_today_wh = 0.0
            total_tomorrow_wh = 0.0
            total_current_hour_wh = 0.0
            inverter_efficiency = 0.88

            for panel in self.panels:
                lat, lon = panel['locLat'], panel['locLong']
                tilt, azimuth = panel['angle'], panel['direction']
                efficiency = panel.get('efficiency', 20) / 100
                panel_power_watt = panel['totPower'] * 1000
                morning_loss = panel.get("tree_loss_morning", 0.0)
                evening_loss = panel.get("tree_loss_evening", 0.0)

                url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={lat}&longitude={lon}"
                    f"&hourly=global_tilted_irradiance,shortwave_radiation"
                    f"&daily=sunrise,sunset,sunshine_duration"
                    f"&timezone={self.config.time_zone}&forecast_days=2"
                    f"&tilt={tilt}&azimuth={azimuth}"
                )

                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = requests.get(url)
                        response.raise_for_status()
                        data = response.json()
                        break
                    except RequestException as e:
                        self.logger.log.error(f"Can't retrieve PV info: {e}")
                        if attempt < max_retries - 1:
                            time.sleep(10)
                        else:
                            self.logger.log.error("All retries failed.")
                            return 0.0

                hourly_data = data.get('hourly', {})
                daily_data = data.get('daily', {})
                dates = daily_data.get('time', [])
                today_index = self.safe_date_index(dates, today_str, "today") or 0
                tomorrow_index = self.safe_date_index(dates, tomorrow_str, "tomorrow") or min(1, len(dates)-1)

                sunrise_today = daily_data.get('sunrise', [None])[today_index]
                sunset_today = daily_data.get('sunset', [None])[today_index]
                sunrise_tomorrow = daily_data.get('sunrise', [None])[tomorrow_index]
                sunset_tomorrow = daily_data.get('sunset', [None])[tomorrow_index]

                sun_today_minutes = daily_data.get('sunshine_duration', [0])[today_index] or 0
                sun_tomorrow_minutes = daily_data.get('sunshine_duration', [0])[tomorrow_index] or 0

                # Update solar_data
                solar_data.update_sunrise_current_day(sunrise_today)
                solar_data.update_sunset_current_day(sunset_today)
                solar_data.update_sunrise_tomorrow_day(sunrise_tomorrow)
                solar_data.update_sunset_tomorrow_day(sunset_tomorrow)
                solar_data.update_sun_time_today(sun_today_minutes)
                solar_data.update_sun_time_tomorrow(sun_tomorrow_minutes)
                solar_data.update_power_peak(panel['totPower'] + solar_data.power_peak)

                # Stunden definieren
                start_hour_today = datetime.strptime(sunrise_today, "%Y-%m-%dT%H:%M").hour if sunrise_today else 6
                end_hour_today = datetime.strptime(sunset_today, "%Y-%m-%dT%H:%M").hour + 1 if sunset_today else 18
                hour_now = now.hour

                # Radiation array safety
                radiation_list = hourly_data.get('global_tilted_irradiance', [])
                if len(radiation_list) < 24:
                    radiation_list += [0]*(24 - len(radiation_list))
                hourly_data['global_tilted_irradiance'] = radiation_list

                # Current hour
                current_hour_wh = radiation_list[hour_now] * panel['total_area'] * efficiency
                total_current_hour_wh += current_hour_wh

                # Remaining today forecast
                forecast_remaining_wh = 0.0
                if hour_now < end_hour_today:
                    forecast_remaining_wh = self.calculate_shortwave_radiation(
                        hourly_data, hour_now+1, end_hour_today,
                        panel['total_area'], efficiency, panel_power_watt,
                        morning_loss, evening_loss
                    )

                measured_today_wh = solar_data.total_current_day or 0
                max_possible_today_wh = panel_power_watt * (sun_today_minutes/60) * efficiency * inverter_efficiency
                panel_forecast_today = min(measured_today_wh + forecast_remaining_wh, max_possible_today_wh)
                total_today_wh += panel_forecast_today

                # Tomorrow forecast
                start_hour_tomorrow = datetime.strptime(sunrise_tomorrow, "%Y-%m-%dT%H:%M").hour if sunrise_tomorrow else 6
                end_hour_tomorrow = datetime.strptime(sunset_tomorrow, "%Y-%m-%dT%H:%M").hour + 1 if sunset_tomorrow else 18

                forecast_tomorrow_wh = self.calculate_shortwave_radiation(
                    hourly_data, start_hour_tomorrow, end_hour_tomorrow,
                    panel['total_area'], efficiency, panel_power_watt,
                    morning_loss, evening_loss
                )

                max_possible_tomorrow_wh = panel_power_watt * (sun_tomorrow_minutes/60) * efficiency * inverter_efficiency
                panel_forecast_tomorrow = min(forecast_tomorrow_wh, max_possible_tomorrow_wh)
                total_tomorrow_wh += panel_forecast_tomorrow

            # ---------------- Dynamic Adjustment Factor ----------------
            previous_adj = self.statsmanager.get_data("solar", "adjustment_factor") or 1.0
            if total_today_wh > 0:
                adj_factor = (solar_data.total_current_day or 0) / total_today_wh
            else:
                adj_factor = 1.0

            # Smooth update to prevent extremes
            adj_factor = max(0.5, min(1.5, 0.5 * previous_adj + 0.5 * adj_factor))
            self.statsmanager.set_status_data("solar", "adjustment_factor", adj_factor)

            # Apply adjustment
            total_today_wh *= adj_factor
            total_tomorrow_wh *= adj_factor

            # Update Solardata
            solar_data.update_total_current_day(round(total_today_wh,2))
            solar_data.update_total_tomorrow_day(round(total_tomorrow_wh,2))
            solar_data.update_total_current_hour(round(total_current_hour_wh*inverter_efficiency,2))

            self.logger.log.info(f"Forecast today: {solar_data.total_current_day:.2f} Wh, tomorrow: {solar_data.total_tomorrow_day:.2f} Wh")
            self.logger.log.info(f"Current hour: {solar_data.total_current_hour:.2f} Wh")
            return solar_data.total_current_hour

        except Exception as e:
            self.logger.log.exception(f"Forecast calculation failed: {e}")
            return 0.0

    # ------------------------------------------------------------------
    def calculate_shortwave_radiation(self, hourly_data, from_hour, to_hour, total_area, efficiency, panel_power_watt, morning_loss, evening_loss):
        total = 0.0
        for hour in range(from_hour, to_hour+1):
            try:
                radiation = hourly_data.get('global_tilted_irradiance', [0])[hour] or 0
            except IndexError:
                radiation = 0
            damping_factor = self.calculate_exponential_damping(hour, morning_loss, evening_loss)
            total += min(radiation * total_area * efficiency * damping_factor, panel_power_watt)
        return total

    def calculate_exponential_damping(self, hour, morning_loss, evening_loss):
        if hour < self.noon_hour:
            damping = morning_loss
        else:
            damping = evening_loss
        return max(0.0, min(1.0, 1.0 - damping))
