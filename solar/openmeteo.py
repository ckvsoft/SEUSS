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
from core.statsmanager import StatsManager

class OpenMeteo:
    def __init__(self, **kwargs) -> None:
        self.config = Config()
        self.logger = CustomLogger()
        self.panels = self.config.get_pv_panels()
        self.noon_hour = 12
        self.damping = (0.0, 0.0)
        self.start_hour = 6
        self.end_hour = 18

    def forecast(self, solardata):
        try:
            pv_info = {}
            total_forcast = 0.0
            max_retries = 3  # Adjust the number of retries as needed

            total_watts_current_hour = 0
            total_watts_current_hour_real = 0
            total_watt_hours_current_day = 0
            total_watt_hours_tomorrow_day = 0
            total_area = 0.0
            sunrise_current_day = None
            sunset_current_day = None
            sunrise_tomorrow_day = None
            sunset_tomorrow_day = None
            sunshine_duration_current_day = None
            sunshine_duration_tomorrow_day = None

            timezone = pytz.timezone(self.config.time_zone)
            current_datetime = datetime.now(timezone)
            current_date = current_datetime.strftime('%Y-%m-%d')
            tomorrow_datetime = current_datetime + timedelta(days=1)
            tomorrow_date = tomorrow_datetime.strftime('%Y-%m-%d')

            for panel in self.panels:
                url = f"https://api.open-meteo.com/v1/forecast?latitude={panel['locLat']}&longitude={panel['locLong']}&minutely_15=sunshine_duration,global_tilted_irradiance&hourly=shortwave_radiation,cloud_cover,temperature_2m,snow_depth&daily=sunrise,sunset,daylight_duration,sunshine_duration,snowfall_sum,shortwave_radiation_sum,showers_sum&timezone={self.config.time_zone}&forecast_days=2&forecast_minutely_15=96&tilt={panel['angle']}&azimuth={panel['direction']}"
                self.damping = (panel.get('damping_morning', 0.0), panel.get('damping_evening', 0.0))

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

                index_today = data['daily'].get('time', []).index(current_date)
                index_tomorrow = data['daily'].get('time', []).index(tomorrow_date)

                sunset_current_day = data['daily'].get('sunset', [])[index_today]
                sunrise_current_day = data['daily'].get('sunrise', [])[index_today]

                sunset_tomorrow_day = data['daily'].get('sunset', [])[index_tomorrow]
                sunrise_tomorrow_day = data['daily'].get('sunrise', [])[index_tomorrow]

                sunshine_duration_current_day = data['daily'].get('sunshine_duration', [])[index_today]
                sunshine_duration_tomorrow_day = data['daily'].get('sunshine_duration', [])[index_tomorrow]

                # shortwave_radiation_today = data['daily'].get('shortwave_radiation_sum', [])[index_today]
                self.start_hour = datetime.strptime(sunrise_tomorrow_day, "%Y-%m-%dT%H:%M").hour
                self.end_hour = datetime.strptime(sunset_tomorrow_day, "%Y-%m-%dT%H:%M").hour + 1
                shortwave_radiation_tomorrow = self.calculate_shortwave_radiation(hourly_data, 24, 47)
                # shortwave_radiation_tomorrow = data['daily'].get('shortwave_radiation_sum', [])[index_tomorrow]
                self.start_hour = datetime.strptime(sunrise_current_day, "%Y-%m-%dT%H:%M").hour
                self.end_hour = datetime.strptime(sunset_current_day, "%Y-%m-%dT%H:%M").hour + 1
                shortwave_radiation_today = self.calculate_shortwave_radiation(hourly_data, 0, 23)

                # total_watt_hours_today = (shortwave_radiation_today / 3.6) * 1000
                # total_watt_hours_tomorrow = (shortwave_radiation_tomorrow / 3.6) * 1000

                efficiency = panel.get('efficiency', 20) / 100

                total_watt_hours_current_day += round((shortwave_radiation_today * total_area) * efficiency, 2)
                total_watt_hours_tomorrow_day += round((shortwave_radiation_tomorrow * total_area) * efficiency, 2)

                total_current_hour = round((self.calculate_shortwave_radiation(hourly_data, 0, index) * total_area) * efficiency, 2)
                total_current_hour_real = round(self.calculate_shortwave_radiation(hourly_data, 0, index - 1), 2)

                # watts_current_hour = hourly_data.get('shortwave_radiation', [])[index]
                # total_watt_current_hour = round((watts_current_hour * total_area) * efficiency, 2)

                # Akkumulierung der Gesamtwerte
                total_watts_current_hour += total_current_hour if total_current_hour is not None else 0
                total_watts_current_hour_real += total_current_hour_real if total_current_hour_real is not None else 0

            # Update der Gesamtwerte für Solardaten
            efficiency_inverter = 95 / 100 # Durchschnitt der am Markt erhältlichen PV Inverter
            solardata.update_total_current_hour(round(total_watts_current_hour * efficiency_inverter, 2))
            solardata.update_total_current_hour_real(total_watts_current_hour_real)
            total_current_day = round(total_watt_hours_current_day * efficiency_inverter, 2)
            total_tomorrow_day = round(total_watt_hours_tomorrow_day * efficiency_inverter, 2)

            efficiency_seuss_list = StatsManager.get_data('solar', 'efficiency')
            if efficiency_seuss_list is not None:
                total_seuss_current_day = round(((total_watt_hours_current_day * efficiency_inverter) / 100) * efficiency_seuss_list[0], 2)
                total_seuss_tomorrow_day = round(((total_watt_hours_tomorrow_day * efficiency_inverter) / 100) * efficiency_seuss_list[0], 2)
                solardata.update_total_seuss_current_day(total_seuss_current_day)
                solardata.update_total_seuss_tomorrow_day(total_seuss_tomorrow_day)

            solardata.update_total_current_day(total_current_day)
            solardata.update_total_tomorrow_day(total_tomorrow_day)
            solardata.update_sunset_current_day (sunset_current_day)
            solardata.update_sunrise_current_day(sunrise_current_day)
            solardata.update_sunset_tomorrow_day(sunset_tomorrow_day)
            solardata.update_sunrise_tomorrow_day(sunrise_tomorrow_day)
            solardata.update_sun_time_today(sunshine_duration_current_day / 60)
            solardata.update_sun_time_tomorrow(sunshine_duration_tomorrow_day / 60)

            # Log der Gesamtwerte
            self.logger.log_info(f"Total Solar for the current hour: {solardata.total_current_hour} Wh")
            self.logger.log_debug(f"Total Solar for the current hour real: {solardata.total_current_hour_real} Wh")
            self.logger.log_info(
                f"Total Solar for the current day ({current_date}): {solardata.total_current_day} Wh, seuss estimated: {solardata.total_seuss_current_day} Wh")
            self.logger.log_info(
                f"Total Solar for the tomorrow day ({tomorrow_date}): {solardata.total_tomorrow_day} Wh, seuss estimated: {solardata.total_seuss_tomorrow_day} Wh")

            return solardata.total_current_hour

        except TypeError:
            return None

    def calculate_exponential_damping(self, hour):
        damping = self.damping[0]
        if hour >= self.noon_hour:
            damping = self.damping[1]

        damping = 1.0 - damping

        if damping == 0.0:
            self.logger.log_debug(f"exponential_damping: hour {hour}, damping {1 + damping}, exponential damping 0.0")
            return 0.0  # Volle Dämpfung, daher ist der Dämpfungsfaktor immer 0
        elif damping == 1.0:
            self.logger.log_debug(f"exponential_damping: hour {hour}, damping {1 - damping}, exponential damping 1.0")
            return 1.0  # Keine Dämpfung, daher ist der Dämpfungsfaktor immer 1
        else:
            # Berechnung des Dämpfungsfaktors basierend auf dem gewünschten Verhalten
            if hour >= self.noon_hour:
                # exponential_damping = 1 - (1 - damping) * ((hour - self.noon_hour) / (24 - self.noon_hour))
                if hour > self.end_hour: return 0
                exponential_damping = 1 - (1 - damping) * ((hour - self.noon_hour) / (self.end_hour - self.noon_hour))

            else:
                # exponential_damping = damping + (1 - damping) * (hour / self.noon_hour)
                if hour < self.start_hour: return 0
                exponential_damping = damping + (1 - damping) * ((hour - self.start_hour) / (self.noon_hour - self.start_hour))

            self.logger.log_debug(f"exponential_damping: hour {hour}, damping {damping}, exponential damping {exponential_damping}")
            return exponential_damping

    def calculate_shortwave_radiation(self, hourly_data, from_hour, to_hour):
        total = 0
        current_hour = 0
        for i in range(from_hour, to_hour + 1):
            cloud_cover = hourly_data.get('cloud_cover', [])[i]
            watts_current_hour = self.calculate_cloud_cover(hourly_data.get('shortwave_radiation', [])[i], cloud_cover)

            if watts_current_hour is not None:
                total += watts_current_hour * self.calculate_exponential_damping(current_hour)

            current_hour += 1

        return total


def calculate_solar_energy(shortwave_radiation, cloud_cover):
    # Modellieren Sie den Einfluss der Wolkenbedeckung auf die Sonnenenergie
    # Angenommen, 100% Wolkenbedeckung bedeutet nicht vollständige Dunkelheit
    # Definieren Sie einen Faktor für den Einfluss der Wolkenbedeckung auf die Sonnenenergie
    cloud_factor = 0.8  # Zum Beispiel: Wolken reduzieren die Sonnenenergie um 20%

    # Berechnen Sie die angepasste Sonnenenergie
    calculated_energy = shortwave_radiation * (1 - cloud_cover / 100) * cloud_factor

    return calculated_energy
