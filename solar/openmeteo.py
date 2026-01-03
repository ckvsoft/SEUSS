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
            # ISO Strings zu Objekten
            sr_dt = datetime.fromisoformat(sunrise_str)
            ss_dt = datetime.fromisoformat(sunset_str)

            # Umrechnen in Dezimalstunden (z.B. 07:30 -> 7.5)
            sr_h = sr_dt.hour + (sr_dt.minute / 60.0)
            ss_h = ss_dt.hour + (ss_dt.minute / 60.0)

            # Sicherheitscheck: Nachts immer 0
            if hour <= sr_h or hour >= ss_h:
                return 0.0

            m_loss = panel.get("damping_morning", 0.0)
            e_loss = panel.get("damping_evening", 0.0)

            # Wenn keine Dämpfung konfiguriert ist, direkt 1.0
            if m_loss == 0.0 and e_loss == 0.0:
                return 1.0

            # Gleitende Berechnung:
            if hour < self.noon_hour:
                # Vormittag: Faktor geht von 0.0 (Sonnenaufgang) bis 1.0 (Mittag)
                # Wir berechnen, wie weit wir im Vormittags-Fenster sind
                window = self.noon_hour - sr_h
                if window > 0:
                    # Lineare Annäherung an Mittag
                    position = (hour - sr_h) / window
                    # Dämpfung: 1.0 ist Maximum, m_loss ist der max. Abzug bei Sonnenaufgang
                    damping = 1.0 - (m_loss * (1.0 - position))
                else:
                    damping = 1.0
            else:
                # Nachmittag: Faktor geht von 1.0 (Mittag) bis 0.0 (Sonnenuntergang)
                window = ss_h - self.noon_hour
                if window > 0:
                    position = (ss_h - hour) / window
                    # Dämpfung: e_loss ist der max. Abzug bei Sonnenuntergang
                    damping = 1.0 - (e_loss * (1.0 - position))
                else:
                    damping = 1.0

            # Ergebnis auf Range [0.0, 1.0] begrenzen
            return max(0.0, min(1.0, damping))
        except Exception as e:
            # Im Fehlerfall lieber keine Dämpfung als 0 Forecast
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

            debug_api_today_raw = 0.0
            debug_api_tomorrow_raw = 0.0

            inverter_efficiency = 0.88
            solar_data.power_peak = sum(panel['totPower'] for panel in self.panels)

            for panel in self.panels:
                if not panel.get('enabled', True): continue

                url = (f"https://api.open-meteo.com/v1/forecast?latitude={panel['locLat']}&longitude={panel['locLong']}"
                       f"&hourly=global_tilted_irradiance&daily=sunrise,sunset,sunshine_duration"
                       f"&timezone={self.config.time_zone}&forecast_days=2&tilt={panel['angle']}&azimuth={panel['direction']}")

                data = None
                for attempt in range(3):
                    try:
                        r = requests.get(url, timeout=10)
                        r.raise_for_status()
                        data = r.json()
                        break
                    except RequestException as e:
                        if attempt < 2:
                            self.logger.log.warning(f"Network error (attempt {attempt + 1}): {e}. Retrying...")
                            time.sleep(1)
                            continue
                        else:
                            self.logger.log.error(f"API unreachable after 3 attempts: {e}")
                    except Exception as e:
                        self.logger.log.error(f"Unexpected error during API call: {e}")
                        break

                if not data: continue
                rad_list = data.get('hourly', {}).get('global_tilted_irradiance', [])
                daily = data.get('daily', {})
                dates = daily.get('time', [])

                t_idx = self.safe_date_index(dates, today_str, "today")
                tm_idx = self.safe_date_index(dates, tomorrow_str, "tomorrow")

                if t_idx is not None and tm_idx is not None:
                    sr_t, ss_t = daily['sunrise'][t_idx], daily['sunset'][t_idx]
                    sr_tm, ss_tm = daily['sunrise'][tm_idx], daily['sunset'][tm_idx]

                    # ALLE Updates für den BatteryCalculator
                    solar_data.update_sunrise_current_day(sr_t)
                    solar_data.update_sunset_current_day(ss_t)
                    solar_data.update_sunrise_tomorrow_day(sr_tm)
                    solar_data.update_sunset_tomorrow_day(ss_tm)
                    solar_data.update_sun_time_today(daily['sunshine_duration'][t_idx])
                    solar_data.update_sun_time_tomorrow(daily['sunshine_duration'][tm_idx])

                    area, eff, p_max = panel.get('total_area', 0), panel.get('efficiency', 20) / 100, panel.get(
                        'totPower', 0) * 1000
                    h_now = now.hour

                    for h in range(0, 48):
                        if h >= len(rad_list): break
                        is_today = (h < 24)
                        sr, ss = (sr_t, ss_t) if is_today else (sr_tm, ss_tm)

                        raw_wh = min((rad_list[h] or 0) * area * eff, p_max)
                        damp = self.calculate_exponential_damping(h % 24, panel, sr, ss)
                        damped_wh = raw_wh * damp

                        if raw_wh > 0:
                            self.logger.log.debug(
                                f"Hour {h % 24} ({'Today' if is_today else 'Tom.'}): Raw {raw_wh:.1f}Wh, Damp: {damp:.2f} -> {damped_wh:.1f}Wh")

                        if is_today:
                            debug_api_today_raw += raw_wh
                            if h < h_now:
                                sum_forecast_past_today_raw += damped_wh
                            elif h == h_now:
                                sum_current_hour_wh_raw += damped_wh
                            else:
                                sum_forecast_rest_today_raw += damped_wh
                        else:
                            debug_api_tomorrow_raw += raw_wh
                            sum_forecast_tomorrow_raw += damped_wh

            # --- Learning Logic ---
            measured_today = solar_data.current_hour_solar_yield or 0.0
            theoretical_past_net = sum_forecast_past_today_raw * inverter_efficiency

            adj_data = self.statsmanager.get_data('solar', 'efficiency')
            adj = (adj_data[0] / 100.0) if isinstance(adj_data, list) and len(adj_data) > 0 else (
                (adj_data / 100.0) if adj_data else 1.0)

            if theoretical_past_net > 200:
                adj = max(0.2, min(2.0, measured_today / theoretical_past_net))
                self.statsmanager.update_percent_status_data('solar', 'adjustment_factor', round(adj, 2))
                self.statsmanager.update_percent_status_data('solar', 'efficiency', round(adj * 100, 2))

            rest_today_final = sum_forecast_rest_today_raw * inverter_efficiency * adj
            total_today = measured_today + rest_today_final
            total_tomorrow = sum_forecast_tomorrow_raw * inverter_efficiency * adj

            solar_data.update_total_current_day(round(total_today, 2))
            solar_data.update_total_tomorrow_day(round(total_tomorrow, 2))
            solar_data.update_total_current_hour(round(sum_current_hour_wh_raw * inverter_efficiency * adj, 2))

            self.logger.log.debug(
                f"RAW API (Total): Today {debug_api_today_raw:.0f} Wh, Tomorrow {debug_api_tomorrow_raw:.0f} Wh")
            self.logger.log.info(
                f"Forecast: Today {total_today:.2f} Wh (Measured: {measured_today:.0f}, Rest: {rest_today_final:.0f}), "
                f"Tomorrow {total_tomorrow:.2f} Wh (Adj: {adj:.2f})"
            )
            return solar_data.total_current_hour

        except Exception as e:
            self.logger.log.exception(f"Forecast failed: {e}")
            return 0.0