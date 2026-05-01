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

    def _estimate_sun_hours_so_far(self, now):
        """
        Cheap approximation of "how many hours of usable sun have we
        already had today". Used as a guard for the adjustment-factor
        learning logic: until we've seen enough sun, we don't trust the
        observed-vs-forecast ratio enough to update the multiplier.

        We define a "sun hour" as one full clock-hour past sunrise --
        below this we're in dawn / dusk regime where small absolute
        errors translate to huge relative ones. Sunrise comes from the
        already-fetched solar_data on the caller side; here we only need
        a rough hours-since-sunrise figure based on the local clock.

        Falls back to a simple heuristic (hours since 06:00 local) if
        no sunrise info is available yet, which is fine because the
        threshold check is paired with a Wh-threshold anyway.
        """
        try:
            # Crude: assume sunrise ~ 06:00 local. The Wh threshold catches
            # the dark-winter-morning case where sun rises later -- in that
            # case theoretical_past_net stays low and learning is skipped
            # for the right reason.
            hours = max(0.0, (now.hour + now.minute / 60.0) - 6.0)
            return hours
        except Exception:
            return 0.0

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

            # 24-slot accumulator for today's RAW (un-multiplied)
            # forecast, summed across all panels. Each panel contributes
            # its own per-hour damped Wh into the same hour bucket. We
            # multiply by inverter_efficiency * adj at persist time
            # below (after adj has been learned), so that a chart
            # rendering this matches the same scale as `daily_pv_wh`
            # measurements -- the y-axis "Wh" is comparable between
            # the forecast curve and the actual curve.
            today_hourly_raw = [0.0] * 24

            # Per-past-day accumulators for the backfill. Keys are
            # ISO date strings; values are dicts:
            #   {"day_total_raw": float, "hourly_raw": [24]float}
            # Filled by the per-panel loop below by walking the
            # past_days portion of the API response (rad_list indices
            # 0 .. t_idx*24-1, with one date per slot of 24 hours).
            # We multiply by inverter_efficiency * adj at persist
            # time, identical to today's data, so the historical
            # chart values are on the same scale as the actuals.
            past_day_acc = {}

            for panel in self.panels:
                if not panel.get('enabled', True): continue

                # past_days=30 lets us backfill the forecast history on
                # restart. Without this, forecast_pv_wh_by_day is empty
                # the first time SEUSS runs the new feature and stays
                # close to empty until weeks of completed days have
                # accumulated -- the chart shows "no history yet" or a
                # single useless dot. With past_days, every restart of
                # SEUSS (even just a config reload) ingests the API's
                # archived past forecasts for the last 30 days into the
                # history dict via write-once-per-day semantics, so the
                # first openmeteo run after deploying this version
                # immediately fills in 30 days of comparison data
                # against the actual pv_wh_by_day measurements that
                # already exist.
                url = (f"https://api.open-meteo.com/v1/forecast?latitude={panel['locLat']}&longitude={panel['locLong']}"
                       f"&hourly=global_tilted_irradiance&daily=sunrise,sunset"
                       f"&timezone={self.config.time_zone}&past_days=30&forecast_days=2&tilt={panel['angle']}&azimuth={panel['direction']}")

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

                    # Sunrise/sunset are kept on solar_data for downstream
                    # consumers (currently only sunrise_tomorrow_day is
                    # read, by the solar abort condition; the others stay
                    # for symmetry). The local sr/ss variables drive the
                    # damping curve below.
                    solar_data.update_sunrise_current_day(sr_t)
                    solar_data.update_sunset_current_day(ss_t)
                    solar_data.update_sunrise_tomorrow_day(sr_tm)
                    solar_data.update_sunset_tomorrow_day(ss_tm)

                    area, eff, p_max = panel.get('total_area', 0), panel.get('efficiency', 20) / 100, panel.get(
                        'totPower', 0) * 1000
                    h_now = now.hour

                    # PAST DAYS BACKFILL.
                    # With past_days=30 the API response is laid out as:
                    #   rad_list[0..23]            = oldest past day
                    #   rad_list[24..47]           = next past day
                    #   ...
                    #   rad_list[t_idx*24 ..]      = today
                    #   rad_list[(t_idx+1)*24 ..]  = tomorrow
                    # Walk every past day, group its 24 hours, and
                    # accumulate damped Wh into past_day_acc keyed by
                    # the day's ISO date (taken from `dates` so it
                    # matches what gets persisted).
                    #
                    # Wrapped in try/except because past-days data is
                    # sometimes incomplete (a sunrise/sunset of null
                    # for older days, missing rad_list entries, etc.)
                    # and we MUST NOT let backfill failures kill the
                    # live forecast for today/tomorrow which is what
                    # the rest of SEUSS depends on.
                    try:
                        past_days_processed = 0
                        for past_day_idx in range(t_idx):
                            if past_day_idx >= len(dates):
                                break
                            iso = dates[past_day_idx]
                            sr_p = daily.get('sunrise', [None] * (past_day_idx + 1))[past_day_idx]
                            ss_p = daily.get('sunset', [None] * (past_day_idx + 1))[past_day_idx]
                            # API sometimes returns null sunrise/sunset
                            # for past days. Skip those rather than
                            # crashing on datetime.fromisoformat(None).
                            if not sr_p or not ss_p:
                                continue
                            bucket = past_day_acc.setdefault(
                                iso,
                                {"day_total_raw": 0.0, "hourly_raw": [0.0] * 24},
                            )
                            for h in range(24):
                                ridx = past_day_idx * 24 + h
                                if ridx >= len(rad_list):
                                    break
                                raw_wh = min((rad_list[ridx] or 0) * area * eff, p_max)
                                damp = self.calculate_exponential_damping(h, panel, sr_p, ss_p)
                                damped_wh = raw_wh * damp
                                bucket["day_total_raw"] += damped_wh
                                bucket["hourly_raw"][h] += damped_wh
                            past_days_processed += 1
                        self.logger.log.debug(
                            f"Past-days backfill: processed {past_days_processed} "
                            f"of {t_idx} past day(s) for panel {panel.get('name', '?')}"
                        )
                    except Exception as e:
                        self.logger.log.warning(
                            f"Past-days backfill failed for panel "
                            f"{panel.get('name', '?')}: {e}. Live forecast continues."
                        )

                    # TODAY + TOMORROW (the original logic). The 48
                    # hours starting at rad_list[t_idx*24] are
                    # today's 24 followed by tomorrow's 24. h is the
                    # offset within that 48-hour window so the
                    # is_today / sunrise / damping logic below stays
                    # untouched.
                    today_start = t_idx * 24
                    for h in range(0, 48):
                        ridx = today_start + h
                        if ridx >= len(rad_list): break
                        is_today = (h < 24)
                        sr, ss = (sr_t, ss_t) if is_today else (sr_tm, ss_tm)

                        raw_wh = min((rad_list[ridx] or 0) * area * eff, p_max)
                        damp = self.calculate_exponential_damping(h % 24, panel, sr, ss)
                        damped_wh = raw_wh * damp

                        if raw_wh > 0:
                            self.logger.log.debug(
                                f"Hour {h % 24} ({'Today' if is_today else 'Tom.'}): Raw {raw_wh:.1f}Wh, Damp: {damp:.2f} -> {damped_wh:.1f}Wh")

                        if is_today:
                            debug_api_today_raw += raw_wh
                            today_hourly_raw[h] += damped_wh
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
            #
            # The previous version overwrote `adj` directly from the
            # observed-vs-forecast ratio of the last few hours. That made
            # one cloudy morning crash the multiplier for the whole day
            # AND tomorrow, with no smoothing. It also persisted across
            # restarts via statsmanager, so a bad day yesterday biased
            # today's first reading.
            #
            # New behaviour:
            #   * EWMA (exponential moving average) with configurable alpha
            #     -- the new ratio gets weight `alpha`, the persisted value
            #     gets `1-alpha`. alpha=1.0 reproduces the old behaviour.
            #   * A daily theoretical-yield threshold below which we don't
            #     learn at all -- avoids training on a single sliver of
            #     morning sun.
            #   * A minimum number of "sun hours so far" before we touch
            #     the factor -- avoids early-morning over-correction.
            #   * Per-day cap on how much `adj` can move (clamps drift if
            #     the model and reality disagree wildly on one day).
            #
            # All four parameters are read from Config so installations
            # with very different climates (alpine vs coastal vs arid)
            # can tune behaviour without code changes. Defaults match
            # "EWMA alpha=0.3, threshold 1000 Wh, min 4 sun hours, cap
            # 20%/day" -- a moderate setting.
            # The authoritative measured-today value comes from
            # PowerConsumption.daily_pv_wh (GX-bus integrated PV power),
            # pushed onto solar_data.pv_measured_today_wh by
            # seusscore.collect_meters_and_inverter_sum. This is
            # deliberately NOT the inverter forward-counter sum -- that
            # sum has been observed to drift ~25% from reality, which
            # would poison the EWMA learning loop below.
            pv_measured_today_wh = solar_data.pv_measured_today_wh or 0.0
            theoretical_past_net = sum_forecast_past_today_raw * inverter_efficiency

            adj_data = self.statsmanager.get_data('solar', 'efficiency')
            adj = (adj_data[0] / 100.0) if isinstance(adj_data, list) and len(adj_data) > 0 else (
                (adj_data / 100.0) if adj_data else 1.0)

            # Read tunables from config with safe fallbacks.
            alpha = getattr(self.config, "solar_adj_ewma_alpha", 0.3)
            min_theoretical = getattr(self.config, "solar_adj_min_theoretical_wh", 1000.0)
            min_sun_hours = getattr(self.config, "solar_adj_min_sun_hours", 4.0)
            max_daily_change = getattr(self.config, "solar_adj_max_daily_change", 0.20)

            # Sun hours observed so far today (rough clock-based estimate
            # of how far past sunrise we are). The Wh-threshold check below
            # catches cases where the clock says "10:00" but a heavy
            # overcast meant near-zero actual yield.
            sun_hours_so_far = self._estimate_sun_hours_so_far(now)

            should_learn = (
                theoretical_past_net > min_theoretical
                and sun_hours_so_far >= min_sun_hours
            )

            if should_learn:
                instantaneous = pv_measured_today_wh / theoretical_past_net
                # Clamp the same hard limits as before -- the model can't
                # be off by more than 5x in either direction, that would
                # be a configuration / data problem we shouldn't paper over.
                instantaneous = max(0.2, min(2.0, instantaneous))

                # EWMA smoothing
                new_adj = alpha * instantaneous + (1.0 - alpha) * adj

                # Per-day change cap
                if max_daily_change > 0:
                    delta = new_adj - adj
                    capped = max(-max_daily_change, min(max_daily_change, delta))
                    new_adj = adj + capped

                adj = max(0.2, min(2.0, new_adj))
                self.statsmanager.update_percent_status_data('solar', 'adjustment_factor', round(adj, 2))
                self.statsmanager.update_percent_status_data('solar', 'efficiency', round(adj * 100, 2))
                self.logger.log.debug(
                    f"adj learn: instant={instantaneous:.2f}, smoothed={adj:.2f} "
                    f"(alpha={alpha}, sun_h={sun_hours_so_far:.1f}, "
                    f"theoretical={theoretical_past_net:.0f}Wh)"
                )
            else:
                self.logger.log.debug(
                    f"adj learn skipped: theoretical={theoretical_past_net:.0f}Wh "
                    f"(need {min_theoretical}), sun_h={sun_hours_so_far:.1f} "
                    f"(need {min_sun_hours}). Keeping adj={adj:.2f}"
                )

            rest_today_final = sum_forecast_rest_today_raw * inverter_efficiency * adj
            total_today = pv_measured_today_wh + rest_today_final
            total_tomorrow = sum_forecast_tomorrow_raw * inverter_efficiency * adj

            # Pure model forecast for the entire day (past + current
            # hour + rest), in contrast to `total_today` which is
            # hybrid (measured-so-far + adjusted rest). Used for the
            # forecast-vs-actual history chart on the stats page,
            # where we want the morning forecast frozen in time so
            # the chart shows "what we expected" vs. "what actually
            # happened".
            full_day_forecast = (
                (sum_forecast_past_today_raw
                 + sum_current_hour_wh_raw
                 + sum_forecast_rest_today_raw)
                * inverter_efficiency * adj
            )

            solar_data.update_forecast_today_wh(round(total_today, 2))
            solar_data.update_forecast_tomorrow_wh(round(total_tomorrow, 2))

            # Persist the forecast totals so the stats page can display
            # them. We must use save_data=True (not False), because the
            # StatsManager singleton's __init__ calls load_data() which
            # overwrites the class-level dict from disk -- any RAM-only
            # values would be lost the moment the stats handler creates
            # a fresh StatsManager() instance. The forecast runs at
            # most once per evaluation cycle, so the disk write is
            # cheap.
            self.statsmanager.set_status_data('solar', 'forecast_today_wh', round(total_today, 2))
            self.statsmanager.set_status_data('solar', 'forecast_tomorrow_wh', round(total_tomorrow, 2))
            self.statsmanager.set_status_data('solar', 'forecast_measured_today_wh', round(pv_measured_today_wh, 2))
            self.statsmanager.set_status_data('solar', 'forecast_rest_today_wh', round(rest_today_final, 2))

            # Per-day forecast history. Keyed by today's local ISO date.
            # Write-once-per-day semantics: the FIRST forecast run of
            # the day captures the morning prediction, later runs in
            # the same day don't overwrite it. This lets the stats
            # page show "what we expected this morning" vs. "what
            # actually came in", which is the meaningful comparison.
            # Without write-once, the value would slowly converge to
            # whatever total_today is at the end of the day, making
            # the chart trivially correct and useless.
            today_iso = now.strftime('%Y-%m-%d')
            forecast_by_day = (
                self.statsmanager.get_data('solar', 'forecast_pv_wh_by_day') or {}
            )
            if not isinstance(forecast_by_day, dict):
                forecast_by_day = {}
            if today_iso not in forecast_by_day:
                forecast_by_day[today_iso] = round(full_day_forecast, 2)
                self.statsmanager.set_status_data(
                    'solar', 'forecast_pv_wh_by_day', forecast_by_day
                )
                # Hourly breakdown for today's solar chart, also
                # written once per day. Apply inverter_efficiency *
                # adj here -- todayHourlyRaw was accumulated as RAW
                # damped Wh per hour summed over panels, so we need
                # the same scaling as the daily total above. The
                # per-hour values then sit on the same scale as the
                # measured-PV per-hour values from
                # PowerConsumption.pv_wh_by_hour_today.
                today_hourly_adj = [
                    round(v * inverter_efficiency * adj, 2)
                    for v in today_hourly_raw
                ]
                hourly_by_day = (
                    self.statsmanager.get_data(
                        'solar', 'forecast_hourly_wh_by_day'
                    ) or {}
                )
                if not isinstance(hourly_by_day, dict):
                    hourly_by_day = {}
                hourly_by_day[today_iso] = today_hourly_adj
                self.statsmanager.set_status_data(
                    'solar', 'forecast_hourly_wh_by_day', hourly_by_day
                )
                self.logger.log.info(
                    f"Captured morning forecast for {today_iso}: "
                    f"{full_day_forecast:.0f} Wh "
                    f"(hourly peak {max(today_hourly_adj):.0f} Wh)"
                )

            # Past-days backfill. Same write-once-per-day semantics:
            # only fill in days that aren't already in the dict, so a
            # genuine morning forecast captured in real time is never
            # overwritten by the API's archived forecast for that day.
            # We re-read the dicts here in case "today" was just
            # written above -- the local references would be stale.
            try:
                forecast_by_day = (
                    self.statsmanager.get_data('solar', 'forecast_pv_wh_by_day') or {}
                )
                if not isinstance(forecast_by_day, dict):
                    forecast_by_day = {}
                hourly_by_day = (
                    self.statsmanager.get_data('solar', 'forecast_hourly_wh_by_day') or {}
                )
                if not isinstance(hourly_by_day, dict):
                    hourly_by_day = {}
                backfilled = 0
                skipped_existing = 0
                for iso, bucket in past_day_acc.items():
                    if iso == today_iso:
                        continue
                    day_total_adj = round(
                        bucket["day_total_raw"] * inverter_efficiency * adj, 2
                    )
                    day_hourly_adj = [
                        round(v * inverter_efficiency * adj, 2)
                        for v in bucket["hourly_raw"]
                    ]
                    if iso not in forecast_by_day:
                        forecast_by_day[iso] = day_total_adj
                        backfilled += 1
                    else:
                        skipped_existing += 1
                    if iso not in hourly_by_day:
                        hourly_by_day[iso] = day_hourly_adj
                if backfilled:
                    self.statsmanager.set_status_data(
                        'solar', 'forecast_pv_wh_by_day', forecast_by_day
                    )
                    self.statsmanager.set_status_data(
                        'solar', 'forecast_hourly_wh_by_day', hourly_by_day
                    )
                    self.logger.log.info(
                        f"Backfilled forecast history for {backfilled} past day(s); "
                        f"{skipped_existing} day(s) already had a forecast and were "
                        f"left alone; total in past_day_acc: {len(past_day_acc)}"
                    )
                else:
                    self.logger.log.debug(
                        f"No past days to backfill (acc has {len(past_day_acc)} day(s); "
                        f"already-stored: {skipped_existing})"
                    )
            except Exception as e:
                self.logger.log.warning(
                    f"Past-days persist failed: {e}. "
                    f"forecast_pv_wh_by_day not updated; "
                    f"acc had {len(past_day_acc)} day(s)."
                )

            self.logger.log.debug(
                f"RAW API (Total): Today {debug_api_today_raw:.0f} Wh, Tomorrow {debug_api_tomorrow_raw:.0f} Wh")
            self.logger.log.info(
                f"Forecast: Today {total_today:.2f} Wh (Measured: {pv_measured_today_wh:.0f}, Rest: {rest_today_final:.0f}), "
                f"Tomorrow {total_tomorrow:.2f} Wh (Adj: {adj:.2f})"
            )
            return {
                "current_hour": sum_current_hour_wh_raw,
                "past_today": sum_forecast_past_today_raw,
                "rest_today": sum_forecast_rest_today_raw
            }

        except Exception as e:
            self.logger.log.exception(f"Forecast failed: {e}")
            # Return the same structure with zeros so the caller doesn't crash
            return {
                "current_hour": 0.0,
                "past_today": 0.0,
                "rest_today": 0.0
            }