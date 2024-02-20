# -*- coding: utf-8 -*-

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

#
# MIT License
#
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#
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

class OpenMeteo:
    def __init__(self, **kwargs) -> None:
        self.config = Config()
        self.logger = CustomLogger()
        self.panels = self.config.get_pv_panels()

    def forecast(self, solardata):
        pv_info = {}
        total_forcast = 0.0
        max_retries = 3  # Adjust the number of retries as needed

        total_watts_current_hour = 0
        total_watt_hours_current_day = 0
        total_watt_hours_tomorrow_day = 0
        total_area = 0.0

        timezone = pytz.timezone(self.config.time_zone)
        current_datetime = datetime.now(timezone)
        current_date = current_datetime.strftime('%Y-%m-%d')
        tomorrow_datetime = current_datetime + timedelta(days=1)
        tomorrow_date = tomorrow_datetime.strftime('%Y-%m-%d')

        for panel in self.panels:
            damping_morning = panel['damping_morning'] if isinstance(panel['damping_morning'], float) and 0 <= panel[
                'damping_morning'] <= 1 else 0
            damping_evening = panel['damping_evening'] if isinstance(panel['damping_evening'], float) and 0 <= panel[
                'damping_evening'] <= 1 else 0
            url = f"https://api.open-meteo.com/v1/forecast?latitude={panel['locLat']}&longitude={panel['locLong']}&minutely_15=sunshine_duration,global_tilted_irradiance&hourly=temperature_2m,snow_depth,global_tilted_irradiance&daily=sunrise,sunset,daylight_duration,sunshine_duration,snowfall_sum,shortwave_radiation_sum&timezone={self.config.time_zone}&forecast_days=2&forecast_minutely_15=96&tilt={panel['angle']}&azimuth={panel['direction']}"

            solardata.update_power_peak(panel['totPower'] + solardata.power_peak)
            total_area += panel['total_area']

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


            hourly_data = data.get('hourly', {})
            index = current_datetime.hour

            index_today = data['daily']['time'].index(current_date)
            index_tomorrow = data['daily']['time'].index(tomorrow_date)

            shortwave_radiation_today = data['daily']['shortwave_radiation_sum'][index_today]
            shortwave_radiation_tomorrow = data['daily']['shortwave_radiation_sum'][index_tomorrow]

            total_watt_hours_current_day += (shortwave_radiation_today / 3.6) * 1000
            total_watt_hours_tomorrow_day += (shortwave_radiation_tomorrow / 3.6) * 1000

            watts_current_hour = hourly_data.get('global_tilted_irradiance', [])[index]

            # Akkumulierung der Gesamtwerte
            total_watts_current_hour += watts_current_hour if watts_current_hour is not None else 0

        # Update der Gesamtwerte für Solardaten
        solardata.update_total_current_hour(total_watts_current_hour)
        solardata.update_total_current_day(round((total_watt_hours_current_day * total_area) * 0.25, 4))
        solardata.update_total_tomorrow_day(round((total_watt_hours_tomorrow_day * total_area) * 0.25, 4))

        # Log der Gesamtwerte
        self.logger.log_info(f"Total Solar Watts for the current hour: {total_watts_current_hour}")
        self.logger.log_info(
            f"Total Solar Watt Hours for the current day ({current_date}): {solardata.total_current_day}")
        self.logger.log_info(
            f"Total Solar Watt Hours for the tomorrow day ({tomorrow_date}): {solardata.total_tomorrow_day}")

        return solardata.total_current_day
