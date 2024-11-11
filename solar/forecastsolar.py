# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2024 Christian Kvasny chris(at)ckvsoft.at
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# Project: [SEUSS -> Smart Ess Unit Spotmarket Switcher
#

import requests
from datetime import datetime, timedelta
import time
import pytz
from requests.exceptions import RequestException
from core.config import Config
from core.log import CustomLogger


class Forecastsolar:
    def __init__(self, **kwargs) -> None:
        self.config = Config()
        self.logger = CustomLogger()
        self.panels = self.config.get_pv_panels()

    def forecast(self, solardata):
        pv_info = {}
        total_forcast = 0.0
        max_retries = 3  # Adjust the number of retries as needed

        for panel in self.panels:
            damping_morning = panel['damping_morning'] if isinstance(panel['damping_morning'], float) and 0 <= panel[
                'damping_morning'] <= 1 else 0
            damping_evening = panel['damping_evening'] if isinstance(panel['damping_evening'], float) and 0 <= panel[
                'damping_evening'] <= 1 else 0
            url = f"https://api.forecast.solar/estimate/{panel['locLat']}/{panel['locLong']}/{panel['angle']}/{panel['direction']}/{panel['totPower']}?damping={damping_morning},{damping_evening}"

            solardata.update_power_peak(panel['totPower'] + solardata.power_peak)

            for retry in range(max_retries):
                try:
                    pv_info = requests.get(url)
                    pv_info.raise_for_status()  # Raise HTTPError for bad responses
                    break  # Break the loop if the request was successful
                except RequestException as e:
                    self.logger.log_error(f"Can't retrieve PV info. Error: {e}")
                    if retry < max_retries - 1:
                        self.logger.log_info(f"Retrying... Attempt {retry + 2}/{max_retries}")
                        time.sleep(20)
                    else:
                        self.logger.log_error(f"All retry attempts failed. Exiting.")
                        return None

            try:
                data = pv_info.json()
            except Exception as e:
                self.logger.log_error(f"Can't retrieve PV info. Error: {e}")
                return None

            timezone = pytz.timezone(self.config.time_zone)
            current_datetime = datetime.now(timezone)
            current_date = current_datetime.strftime('%Y-%m-%d')
            tomorrow_datetime = current_datetime + timedelta(days=1)
            tomorrow_date = tomorrow_datetime.strftime('%Y-%m-%d')

            watts_current_hour = data['result']['watts'].get(f"{current_date} {current_datetime.hour}:00:00", None)
            watt_hours_current_hour = data['result']['watt_hours'].get(f"{current_date} {current_datetime.hour}:00:00",
                                                                       None)
            watt_hours_current_day = data['result']['watt_hours_day'].get(current_date, None)
            watt_hours_tomorrow_day = data['result']['watt_hours_day'].get(tomorrow_date, None)

            # Fetching sunrise_current_day, sunset_current_day, and sun time for today
            watt_hours = data['result']['watt_hours']

            # Fetching sunrise_current_day, sunset_current_day, and sun time for today
            watt_hours_today = {key: value for key, value in watt_hours.items() if key.startswith(current_date)}

            # Sunrise and sunset_current_day for today
            sunrise_today = min(watt_hours_today.keys(), key=lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"))
            sunset_today = max(watt_hours_today.keys(), key=lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"))

            # Calculate sun time for today
            sunrise_today_datetime = datetime.strptime(sunrise_today, "%Y-%m-%d %H:%M:%S")
            sunset_today_datetime = datetime.strptime(sunset_today, "%Y-%m-%d %H:%M:%S")
            sun_time_today_minutes = int((sunset_today_datetime - sunrise_today_datetime).total_seconds() / 60)

            # Fetching sunrise_current_day, sunset_current_day, and sun time for tomorrow
            watt_hours_tomorrow = {key: value for key, value in watt_hours.items() if key.startswith(tomorrow_date)}

            # Sunrise and sunset_current_day for tomorrow
            sunrise_tomorrow = min(watt_hours_tomorrow.keys(), key=lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"))
            sunset_tomorrow = max(watt_hours_tomorrow.keys(), key=lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"))

            # Calculate sun time for tomorrow
            sunrise_tomorrow_datetime = datetime.strptime(sunrise_tomorrow, "%Y-%m-%d %H:%M:%S")
            sunset_tomorrow_datetime = datetime.strptime(sunset_tomorrow, "%Y-%m-%d %H:%M:%S")
            sun_time_tomorrow_minutes = int((sunset_tomorrow_datetime - sunrise_tomorrow_datetime).total_seconds() / 60)

            # Update Solardata values
            solardata.update_sunrise(sunrise_today)
            solardata.update_sunset(sunset_today)
            solardata.update_sun_time_today(sun_time_today_minutes)
            solardata.update_sun_time_tomorrow(sun_time_tomorrow_minutes)
            solardata.update_total_current_hour(watts_current_hour)
            solardata.update_total_current_day(watt_hours_current_day)
            solardata.update_total_tomorrow_day(watt_hours_tomorrow_day)

            self.logger.log_info(f"Place: {data['message']['info']['place']}")

            if watts_current_hour is not None:
                self.logger.log_info(f"Solar Watts for the current hour: {watts_current_hour}")

            if watt_hours_current_hour is not None:
                self.logger.log_info(f"Solar Watt Hours for the current hour: {watt_hours_current_hour}")
                total_forcast += float(watt_hours_current_hour)

            if watt_hours_current_day is not None:
                self.logger.log_info(f"Solar Watt Hours for the current day ({current_date}): {watt_hours_current_day}")

            if watt_hours_tomorrow_day is not None:
                self.logger.log_info(
                    f"Solar Watt Hours for the tomorrow day ({tomorrow_date}): {watt_hours_tomorrow_day}")

            # Log the results
            self.logger.log_info(f"Sunrise today: {sunrise_today}")
            self.logger.log_info(f"Sunset today: {sunset_today}")
            self.logger.log_info(f"Sun time today (in minutes): {sun_time_today_minutes}")

            self.logger.log_info(f"Sunrise tomorrow: {sunrise_tomorrow}")
            self.logger.log_info(f"Sunset tomorrow: {sunset_tomorrow}")
            self.logger.log_info(f"Sun time tomorrow (in minutes): {sun_time_tomorrow_minutes}")

        return total_forcast
