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
import time
import pytz
from requests.exceptions import RequestException
from core.config import Config
from core.log import CustomLogger
from core.statsmanager import StatsManager

class OpenMeteo:
    """
    Modernized OpenMeteo PV forecast class.
    - Forecasts current hour, today, and tomorrow PV yield.
    - Applies morning/evening damping.
    - Dynamically scales today forecast based on already measured energy.
    - Logs important steps.
    """

    def __init__(self):
        self.config = Config()
        self.logger = CustomLogger()
        self.statsmanager = StatsManager()
        self.panels = self.config.get_pv_panels()
        self.noon_hour = 12
        self.damping = (0.0, 0.0)
        self.start_hour = 6
        self.end_hour = 18

    # -----------------------------------------------------------
    # Safe method: prevents ValueError when API date list shifts
    # -----------------------------------------------------------
    def safe_date_index(self, dates, target_date, label):
        try:
            return dates.index(target_date)
        except ValueError:
            self.logger.log.error(
                f"[OpenMeteo] Missing date '{target_date}' in daily.time for {label}. "
                f"Available dates: {dates}"
            )
            return None

    # ------------------------------------------------------------------
    # Main forecast function
    # ------------------------------------------------------------------
    def forecast(self, solar_data):
        try:
            timezone = pytz.timezone(self.config.time_zone)
            now = datetime.now(timezone)
            today_str = now.strftime('%Y-%m-%d')
            tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')

            total_area = 0.0
            total_current_day_wh = 0.0
            total_tomorrow_wh = 0.0
            total_current_hour_wh = 0.0

            for panel in self.panels:
                latitude = panel['locLat']
                longitude = panel['locLong']
                tilt = panel['angle']
                azimuth = panel['direction']
                efficiency = panel.get('efficiency', 20) / 100
                panel_power_watt = panel['totPower'] * 1000
                morning_loss = panel.get("tree_loss_morning", 0.0)
                evening_loss = panel.get("tree_loss_evening", 0.0)
                total_area += panel['total_area']

                # --- Construct Open-Meteo API URL ---
                url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={latitude}&longitude={longitude}"
                    f"&minutely_15=sunshine_duration,global_tilted_irradiance"
                    f"&hourly=global_tilted_irradiance,shortwave_radiation,temperature_2m,snow_depth"
                    f"&daily=sunrise,sunset,daylight_duration,sunshine_duration,snowfall_sum,"
                    f"shortwave_radiation_sum,showers_sum"
                    f"&timezone={self.config.time_zone}"
                    f"&forecast_days=2&forecast_minutely_15=96"
                    f"&tilt={tilt}&azimuth={azimuth}"
                )

                # --- Request with retries ---
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = requests.get(url)
                        response.raise_for_status()
                        data = response.json()
                        break
                    except RequestException as e:
                        self.logger.log.error(f"Can't retrieve PV info. Error: {e}")
                        if attempt < max_retries - 1:
                            self.logger.log.info(f"Retrying... Attempt {attempt+2}/{max_retries}")
                            time.sleep(20)
                        else:
                            self.logger.log.error("All retry attempts failed.")
                            return None

                hourly_data = data.get('hourly', {})
                daily_data = data.get('daily', {})

                # --- Safe date extraction ---
                dates = daily_data.get('time', [])
                today_index = self.safe_date_index(dates, today_str, "today") or 0
                tomorrow_index = self.safe_date_index(dates, tomorrow_str, "tomorrow") or min(1, len(dates)-1)

                sunrise_today = daily_data.get('sunrise', [None])[today_index]
                sunset_today = daily_data.get('sunset', [None])[today_index]
                sunrise_tomorrow = daily_data.get('sunrise', [None])[tomorrow_index]
                sunset_tomorrow = daily_data.get('sunset', [None])[tomorrow_index]

                # --- Determine day start/end hours ---
                start_hour_today = datetime.strptime(sunrise_today, "%Y-%m-%dT%H:%M").hour if sunrise_today else 6
                end_hour_today = datetime.strptime(sunset_today, "%Y-%m-%dT%H:%M").hour + 1 if sunset_today else 18
                start_hour_tomorrow = datetime.strptime(sunrise_tomorrow, "%Y-%m-%dT%H:%M").hour if sunrise_tomorrow else 6
                end_hour_tomorrow = datetime.strptime(sunset_tomorrow, "%Y-%m-%dT%H:%M").hour + 1 if sunset_tomorrow else 18

                # --- Calculate model energy so far today ---
                hours_passed = now.hour - start_hour_today
                if hours_passed > 0:
                    model_energy_so_far = self.calculate_shortwave_radiation(
                        hourly_data, start_hour_today, now.hour-1,
                        panel['total_area'], efficiency, panel_power_watt, morning_loss, evening_loss
                    )
                else:
                    model_energy_so_far = 0.0

                measured_energy_so_far = solar_data.current_hour_solar_yield

                # --- Dynamic scaling factor ---
                if model_energy_so_far > 0:
                    scaling_factor = measured_energy_so_far / model_energy_so_far
                    scaling_factor = max(0.5, min(1.5, scaling_factor))
                else:
                    scaling_factor = 1.0

                # --- Forecast remaining hours today ---
                remaining_energy = self.calculate_shortwave_radiation(
                    hourly_data, now.hour, end_hour_today,
                    panel['total_area'], efficiency, panel_power_watt, morning_loss, evening_loss
                )
                remaining_energy_adjusted = remaining_energy * scaling_factor

                total_today = measured_energy_so_far + remaining_energy_adjusted
                total_current_day_wh += total_today

                # --- Forecast tomorrow ---
                tomorrow_energy = self.calculate_shortwave_radiation(
                    hourly_data, start_hour_tomorrow, end_hour_tomorrow,
                    panel['total_area'], efficiency, panel_power_watt, morning_loss, evening_loss
                )
                total_tomorrow_wh += tomorrow_energy

                # --- Current hour power ---
                try:
                    current_hour_radiation = hourly_data.get('global_tilted_irradiance', [0])[now.hour]
                except IndexError:
                    self.logger.log.warning(f"Current hour radiation missing for panel {panel}")
                    current_hour_radiation = 0

                total_current_hour_wh += min(current_hour_radiation * panel['total_area'] * efficiency, panel_power_watt)

            # --- Apply inverter efficiency ---
            inverter_efficiency = 0.88
            solar_data.update_total_current_day(round(total_current_day_wh * inverter_efficiency, 2))
            solar_data.update_total_tomorrow_day(round(total_tomorrow_wh * inverter_efficiency, 2))
            solar_data.update_total_current_hour(round(total_current_hour_wh * inverter_efficiency, 2))

            # --- Update sunrise/sunset info ---
            solar_data.update_sunrise_current_day(sunrise_today)
            solar_data.update_sunset_current_day(sunset_today)
            solar_data.update_sunrise_tomorrow_day(sunrise_tomorrow)
            solar_data.update_sunset_tomorrow_day(sunset_tomorrow)

            self.logger.log.info(f"Forecast today: {total_current_day_wh:.2f} Wh, tomorrow: {total_tomorrow_wh:.2f} Wh")
            self.logger.log.info(f"Current hour: {total_current_hour_wh:.2f} Wh")

            return solar_data.total_current_hour

        except Exception as e:
            self.logger.log.error(f"Forecast calculation failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Shortwave radiation calculation with damping
    # ------------------------------------------------------------------
    def calculate_shortwave_radiation(self, hourly_data, from_hour, to_hour, total_area, efficiency, panel_power_watt, morning_loss, evening_loss):
        """
        Calculate energy (Wh) between from_hour and to_hour.
        Applies exponential morning/evening damping to simulate morning/afternoon loss.
        """
        total = 0.0
        for i, hour in enumerate(range(from_hour, to_hour+1)):
            try:
                radiation = hourly_data.get('global_tilted_irradiance', [0])[hour] or 0
            except IndexError:
                radiation = 0
            damping_factor = self.calculate_exponential_damping(i, morning_loss, evening_loss)
            power = min(radiation * total_area * efficiency * damping_factor, panel_power_watt)
            total += power
        return total

    # ------------------------------------------------------------------
    # Exponential damping
    # ------------------------------------------------------------------
    def calculate_exponential_damping(self, hour_index, morning_loss, evening_loss):
        """
        Apply morning/evening damping.
        Morning: low->high, Evening: high->low.
        Returns 0..1 multiplier.
        """
        damping = morning_loss if hour_index < self.noon_hour else evening_loss
        damping = 1.0 - damping

        if damping <= 0.0:
            return 0.0
        elif damping >= 1.0:
            return 1.0
        else:
            if hour_index < self.noon_hour:
                return damping + (1 - damping) * (hour_index / self.noon_hour)
            else:
                hours_after_noon = hour_index - self.noon_hour
                return 1 - (1 - damping) * (hours_after_noon / (self.end_hour - self.noon_hour + 1))
