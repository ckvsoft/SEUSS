#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2025 Christian Kvasny
#  Project: SEUSS -> Smart Ess Unit Spotmarket Switcher

import requests
from datetime import datetime, timedelta
import time
import pytz
from requests.exceptions import RequestException
from core.config import Config
from core.log import CustomLogger
from core.statsmanager import StatsManager


class OpenMeteo:
    def __init__(self, **kwargs) -> None:
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

    def forecast(self, solardata):
        try:
            pv_info = {}
            total_forcast = 0.0
            max_retries = 3

            total_watts_current_hour = 0
            total_watt_hours_current_day = 0
            total_watt_hours_tomorrow_day = 0
            total_area = 0.0

            sunrise_current_day = None
            sunset_current_day = None
            sunrise_tomorrow_day = None
            sunset_tomorrow_day = None
            sunshine_duration_current_day = 0
            sunshine_duration_tomorrow_day = 0

            timezone = pytz.timezone(self.config.time_zone)
            current_datetime = datetime.now(timezone)
            current_date = current_datetime.strftime('%Y-%m-%d')

            tomorrow_datetime = current_datetime + timedelta(days=1)
            tomorrow_date = tomorrow_datetime.strftime('%Y-%m-%d')

            solardata.update_current_hour_forcast(0)

            for panel in self.panels:
                url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={panel['locLat']}&longitude={panel['locLong']}"
                    f"&minutely_15=sunshine_duration,global_tilted_irradiance"
                    f"&hourly=global_tilted_irradiance,shortwave_radiation,temperature_2m,snow_depth"
                    f"&daily=sunrise,sunset,daylight_duration,sunshine_duration,snowfall_sum,"
                    f"shortwave_radiation_sum,showers_sum"
                    f"&timezone={self.config.time_zone}"
                    f"&forecast_days=2&forecast_minutely_15=96"
                    f"&tilt={panel['angle']}&azimuth={panel['direction']}"
                )

                self.damping = (
                    panel.get('damping_morning', 0.0),
                    panel.get('damping_evening', 0.0)
                )

                solardata.update_power_peak(panel['totPower'] + solardata.power_peak)
                total_area += panel['total_area']

                # Retry for API
                for retry in range(max_retries):
                    try:
                        pv_info = requests.get(url)
                        pv_info.raise_for_status()
                        break
                    except RequestException as e:
                        self.logger.log.error(f"Can't retrieve PV info. Error: {e}")
                        if retry < max_retries - 1:
                            self.logger.log.info(f"Retrying... Attempt {retry + 2}/{max_retries}")
                            time.sleep(20)
                        else:
                            self.logger.log.error("All retry attempts failed.")
                            return None

                try:
                    data = pv_info.json()
                except Exception as e:
                    self.logger.log.error(f"Can't parse PV info JSON. Error: {e}")
                    return None

                hourly_data = data.get('hourly', {})
                index_current_hour = current_datetime.hour

                # --- Safe date extraction ---
                dates = data.get('daily', {}).get('time', [])

                index_today = self.safe_date_index(dates, current_date, "today")
                index_tomorrow = self.safe_date_index(dates, tomorrow_date, "tomorrow")

                # Fallback if missing
                if index_today is None:
                    index_today = 0
                if index_tomorrow is None:
                    index_tomorrow = min(1, len(dates) - 1)

                # Safe extraction of daily values
                daily = data.get('daily', {})

                sunset_current_day = daily.get('sunset', [None])[index_today]
                sunrise_current_day = daily.get('sunrise', [None])[index_today]
                sunshine_duration_current_day = daily.get('sunshine_duration', [0])[index_today]

                sunset_tomorrow_day = daily.get('sunset', [None])[index_tomorrow]
                sunrise_tomorrow_day = daily.get('sunrise', [None])[index_tomorrow]
                sunshine_duration_tomorrow_day = daily.get('sunshine_duration', [0])[index_tomorrow]

                # --- Radiation calculations ---
                efficiency = panel.get('efficiency', 20) / 100
                twp = round(panel['totPower'] * 1000.0, 2)

                # Tomorrow
                self.start_hour = datetime.strptime(sunrise_tomorrow_day, "%Y-%m-%dT%H:%M").hour if sunrise_tomorrow_day else 6
                self.end_hour = datetime.strptime(sunset_tomorrow_day, "%Y-%m-%dT%H:%M").hour + 1 if sunset_tomorrow_day else 18

                shortwave_radiation_tomorrow = self.calculate_shortwave_radiation(
                    hourly_data, 24, 47, panel['total_area'], efficiency, twp
                )

                # Today
                self.start_hour = datetime.strptime(sunrise_current_day, "%Y-%m-%dT%H:%M").hour if sunrise_current_day else 6
                self.end_hour = datetime.strptime(sunset_current_day, "%Y-%m-%dT%H:%M").hour + 1 if sunset_current_day else 18

                shortwave_radiation_today = self.calculate_shortwave_radiation(
                    hourly_data, 0, 23, panel['total_area'], efficiency, twp
                )

                total_watt_hours_current_day += round(shortwave_radiation_today, 2)
                total_watt_hours_tomorrow_day += round(shortwave_radiation_tomorrow, 2)

                # Current hour
                new_datetime = current_datetime - timedelta(hours=1)
                current_forecast_wh = hourly_data.get('global_tilted_irradiance', [0])[new_datetime.hour]

                solardata.update_current_hour_forcast(
                    solardata.current_hour_forcast + current_forecast_wh
                )

                total_current_hour = round(
                    self.calculate_shortwave_radiation(
                        hourly_data, 0, index_current_hour, panel['total_area'], efficiency, twp
                    ), 2
                )

                total_watts_current_hour += total_current_hour

            # --- Final aggregation ---
            efficiency_inverter = 0.88
            forcast_total_watts_current_hour = round(total_watts_current_hour * efficiency_inverter, 2)

            # Adjustment factor
            if forcast_total_watts_current_hour == 0:
                adjustment_factor = 1
            else:
                adjustment_factor = solardata.current_hour_solar_yield / forcast_total_watts_current_hour

            previous_adjustment = self.statsmanager.get_data("solar", "adjustment_factor") or 1
            self.statsmanager.set_status_data("solar", "adjustment_factor", adjustment_factor)

            adj = min(1.5, (previous_adjustment * 0.5) + (adjustment_factor * 0.5))

            total_current_day = round(total_watt_hours_current_day * efficiency_inverter * adj, 2)
            total_tomorrow_day = round(total_watt_hours_tomorrow_day * efficiency_inverter * adj, 2)
            total_watts_current_hour = round(total_watts_current_hour * efficiency_inverter * adj, 2)

            # Update solardata
            solardata.update_total_current_hour(total_watts_current_hour)
            solardata.update_total_current_day(total_current_day)
            solardata.update_total_tomorrow_day(total_tomorrow_day)

            solardata.update_sunrise_current_day(sunrise_current_day)
            solardata.update_sunset_current_day(sunset_current_day)
            solardata.update_sunrise_tomorrow_day(sunrise_tomorrow_day)
            solardata.update_sunset_tomorrow_day(sunset_tomorrow_day)

            solardata.update_sun_time_today(sunshine_duration_current_day / 60)
            solardata.update_sun_time_tomorrow(sunshine_duration_tomorrow_day / 60)

            # Logging
            self.logger.log.info(
                f"Total Solar current hour: {solardata.total_current_hour} Wh"
            )
            self.logger.log.info(
                f"Total Solar today ({current_date}): {solardata.total_current_day} Wh"
            )
            self.logger.log.info(
                f"Total Solar tomorrow ({tomorrow_date}): {solardata.total_tomorrow_day} Wh"
            )

            return solardata.total_current_hour

        except TypeError:
            return None

    # ------------------------------------------------------------------
    # Radiation & damping logic (unchanged from your original version)
    # ------------------------------------------------------------------
    def calculate_shortwave_radiation(self, hourly_data, from_hour, to_hour, total_area, efficiency, twp):
        total = 0
        current_hour = 0
        for i in range(from_hour, to_hour + 1):
            watts_current_hour = hourly_data.get('global_tilted_irradiance', [0])[i]
            if watts_current_hour is not None:
                effective_power = watts_current_hour * self.calculate_exponential_damping(current_hour)
                power = min((effective_power * total_area) * efficiency, twp)
                total += power
            current_hour += 1
        return total

    def calculate_exponential_damping(self, hour):
        damping = self.damping[0]
        if hour >= self.noon_hour:
            damping = self.damping[1]

        damping = 1.0 - damping

        if damping == 0.0:
            return 0.0
        elif damping == 1.0:
            return 1.0
        else:
            if hour >= self.noon_hour:
                if hour > self.end_hour:
                    return 0
                return 1 - (1 - damping) * ((hour - self.noon_hour) / (self.end_hour - self.noon_hour))
            else:
                if hour < self.start_hour:
                    return 0
                return damping + (1 - damping) * ((hour - self.start_hour) / (self.noon_hour - self.start_hour))
