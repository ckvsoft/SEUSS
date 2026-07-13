#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2026 Christian Kvasny chris(at)ckvsoft.at
#

"""
SolarForecastProvider -- abstract base class for solar yield forecast
providers (OpenMeteo, Solcast, etc.).

Implements the template-method pattern: the public `forecast()`
method runs the full pipeline (per-panel iteration, damping,
accumulation, adjustment-factor learning, persistence, history,
cloud-cover stats). Subclasses only implement `fetch_panel_raw()`
to deliver raw per-hour Wh values + sunrise/sunset/cloudcover for
one panel. Everything else is shared, so adding a new provider is
a single small file.

The subclass's `fetch_panel_raw(panel)` MUST return a dict with:
    {
        "ok":              bool,          # False on API failure
        "hourly_wh_raw":   list[48] float, # raw Wh per hour, 0..23=today, 24..47=tomorrow
        "cloudcover_pct":  list[48] float | None,  # %, same layout
        "sunrise_today":   str ISO,
        "sunset_today":    str ISO,
        "sunrise_tomorrow":str ISO,
        "sunset_tomorrow": str ISO,
        "error":           str | None,
    }

Returning `ok=False` lets SolarForecastManager fall back to the
next enabled provider. Provider implementations should make their
own HTTP error handling robust (retries / timeouts) -- the abstract
base does not retry on its behalf, it just believes the result.

NOTE on damping: subclasses return RAW Wh -- the base class applies
calculate_exponential_damping() uniformly. This means Solcast's
panel-aware power forecast still gets the user's morning/evening
damping factors applied, which is correct because those factors
encode LOCAL shading (a neighbour's tree, the user's chimney) that
no remote API can know about.
"""

import math
import time
from datetime import datetime, timedelta

import pytz

from core.config import Config
from core.log import CustomLogger
from core.statsmanager import StatsManager
from solar.solardata import Solardata


class SolarForecastProvider:
    # Subclasses MUST set this -- the human-readable identifier that
    # matches `name` in the config's solar_forecast_providers list.
    name = None

    # Per-provider inverter efficiency multiplier. Applied AFTER raw
    # damped Wh have been accumulated, BEFORE the adjustment-factor
    # learning loop. Same value for all providers historically (0.88);
    # subclasses can override if their numbers already include the
    # inverter.
    inverter_efficiency = 0.88

    # If True, the provider's fetch_panel_raw() returns Wh for the
    # WHOLE PV system in one call (e.g. Solcast: rooftop site already
    # represents the full array). The base class then iterates panels
    # only to apply per-panel damping, but accumulates only ONCE.
    # If False (e.g. OpenMeteo: GTI per location/tilt), each panel
    # contributes independently and gets summed.
    aggregates_all_panels = False

    def __init__(self):
        self.config = Config()
        self.logger = CustomLogger()
        self.statsmanager = StatsManager()
        self.panels = self.config.get_pv_panels()
        self.noon_hour = 12.0
        # Looked up lazily so subclasses can call _provider_config()
        # without ordering issues.
        self._provider_config_cache = None

    # --------------------------------------------------------------
    # Hooks for subclasses to implement
    # --------------------------------------------------------------

    def fetch_panel_raw(self, panel):
        """
        Subclass implementation: fetch a single panel's 48-hour
        raw Wh forecast plus sunrise/sunset/cloudcover.

        Return shape: see module docstring.
        """
        raise NotImplementedError

    # --------------------------------------------------------------
    # Provider-config helpers
    # --------------------------------------------------------------

    def _provider_config(self):
        """
        Returns this provider's entry from
        Config.solar_forecast_providers, keyed by `self.name` (case-
        insensitive). Empty dict if not configured -- caller should
        treat that as "enabled, no api_key, default throttle".
        """
        if self._provider_config_cache is not None:
            return self._provider_config_cache
        result = {}
        try:
            providers = getattr(self.config, "solar_forecast_providers", None)
            if providers is None and hasattr(self.config, "get_solar_forecast_providers"):
                providers = self.config.get_solar_forecast_providers()
            if providers:
                target = (self.name or "").lower()
                for p in providers:
                    if str(p.get("name", "")).lower() == target:
                        result = p
                        break
        except Exception as e:
            self.logger.log.debug(
                f"Provider config lookup failed for {self.name}: {e}"
            )
        self._provider_config_cache = result
        return result

    @property
    def enabled(self):
        cfg = self._provider_config()
        if not cfg:
            # No config block -> default-on, for backward compat with
            # the old single-provider setup that just used OpenMeteo.
            return self.name and self.name.lower() == "openmeteo"
        return bool(cfg.get("enabled", True))

    @property
    def primary(self):
        return bool(self._provider_config().get("primary", False))

    @property
    def api_key(self):
        return self._provider_config().get("api_key", "") or ""

    # --------------------------------------------------------------
    # Shared helpers
    # --------------------------------------------------------------

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
        learning logic.
        """
        try:
            hours = max(0.0, (now.hour + now.minute / 60.0) - 6.0)
            return hours
        except Exception:
            return 0.0

    @staticmethod
    def _iso_hour(iso_str):
        """Extract hour-of-day from an ISO timestamp like '2026-06-04T05:35'."""
        try:
            if iso_str and len(iso_str) >= 13:
                return int(iso_str[11:13])
        except (ValueError, TypeError):
            pass
        return None

    def calculate_exponential_damping(self, hour, panel, sunrise, sunset):
        """
        Symmetric exponential damping around solar noon. damp_morning
        and damp_evening control how strongly the curve compresses on
        each side -- 0 = no damping (flat 1.0 across the day), 1 =
        full damping (exp falloff from sr->noon and noon->ss).
        """
        try:
            sr_h = self._iso_hour(sunrise)
            ss_h = self._iso_hour(sunset)
            if sr_h is None or ss_h is None:
                return 1.0
            if hour < sr_h or hour > ss_h:
                return 0.0
            damp_morning = float(panel.get('damping_morning', 0) or 0)
            damp_evening = float(panel.get('damping_evening', 0) or 0)
            noon_h = (sr_h + ss_h) / 2.0
            if hour < noon_h:
                if damp_morning <= 0:
                    return 1.0
                half_width = max(noon_h - sr_h, 0.1)
                x = (hour - sr_h) / half_width
                damping = 1.0 - damp_morning * (1.0 - math.exp(-3.0 * (1.0 - x)))
            else:
                if damp_evening <= 0:
                    return 1.0
                half_width = max(ss_h - noon_h, 0.1)
                x = (ss_h - hour) / half_width
                damping = 1.0 - damp_evening * (1.0 - math.exp(-3.0 * (1.0 - x)))
            return max(0.0, min(1.0, damping))
        except Exception:
            return 1.0

    # --------------------------------------------------------------
    # The public template-method
    # --------------------------------------------------------------

    def forecast(self, solar_data):
        """
        Run the full forecast pipeline using the subclass's
        fetch_panel_raw() to get raw Wh data. Returns the same
        legacy dict shape as the old direct OpenMeteo.forecast()
        so existing callers keep working.

        On API failure for the first panel, bails out early WITHOUT
        writing zeros to statsmanager / solar_data, so the last
        good forecast remains visible to the user. The
        SolarForecastManager picks this up and tries the next
        enabled provider.
        """
        try:
            timezone = pytz.timezone(self.config.time_zone)
            now = datetime.now(timezone)

            sum_forecast_past_today_raw = 0.0
            sum_forecast_rest_today_raw = 0.0
            sum_forecast_tomorrow_raw = 0.0
            sum_current_hour_wh_raw = 0.0

            today_hourly_raw = [0.0] * 24
            tomorrow_hourly_raw = [0.0] * 24

            cloudcover_today = None
            cloudcover_tomorrow = None
            sr_t = ss_t = sr_tm = ss_tm = None

            any_panel_succeeded = False
            for panel in self.panels:
                if not panel.get('enabled', True):
                    continue

                raw = self.fetch_panel_raw(panel)
                if not raw or not raw.get("ok"):
                    self.logger.log.warning(
                        f"{self.name} fetch failed for panel "
                        f"'{panel.get('name', '?')}': {raw.get('error') if raw else 'no result'}. "
                        f"Aborting forecast cycle, keeping previous values."
                    )
                    # Signal manager that this provider failed -- the
                    # special return shape lets it try the next one.
                    return None

                any_panel_succeeded = True
                hourly_wh = raw.get("hourly_wh_raw") or []
                if len(hourly_wh) < 48:
                    hourly_wh = list(hourly_wh) + [0.0] * (48 - len(hourly_wh))

                cc_list = raw.get("cloudcover_pct") or []
                if cloudcover_today is None and len(cc_list) >= 24:
                    cloudcover_today = [float(v or 0) for v in cc_list[:24]]
                if cloudcover_tomorrow is None and len(cc_list) >= 48:
                    cloudcover_tomorrow = [float(v or 0) for v in cc_list[24:48]]

                # Sunrise/sunset (first successful panel wins -- it's
                # a location attribute, identical across panels at
                # the same lat/lon).
                if sr_t is None:
                    sr_t = raw.get("sunrise_today")
                    ss_t = raw.get("sunset_today")
                    sr_tm = raw.get("sunrise_tomorrow")
                    ss_tm = raw.get("sunset_tomorrow")
                    if sr_t:
                        solar_data.update_sunrise_current_day(sr_t)
                    if ss_t:
                        solar_data.update_sunset_current_day(ss_t)
                    if sr_tm:
                        solar_data.update_sunrise_tomorrow_day(sr_tm)
                    if ss_tm:
                        solar_data.update_sunset_tomorrow_day(ss_tm)

                p_max = float(panel.get('totPower', 0) or 0) * 1000  # kW -> W cap
                h_now = now.hour

                for h in range(48):
                    is_today = (h < 24)
                    sr = sr_t if is_today else sr_tm
                    ss = ss_t if is_today else ss_tm

                    raw_wh = hourly_wh[h] or 0.0
                    # Cap to panel's instantaneous nameplate power to
                    # prevent absurd over-estimates from a bad GTI value.
                    if p_max > 0:
                        raw_wh = min(raw_wh, p_max)

                    damp = self.calculate_exponential_damping(h % 24, panel, sr, ss)
                    damped_wh = raw_wh * damp

                    if is_today:
                        today_hourly_raw[h] += damped_wh
                        if h < h_now:
                            sum_forecast_past_today_raw += damped_wh
                        elif h == h_now:
                            sum_current_hour_wh_raw += damped_wh
                        else:
                            sum_forecast_rest_today_raw += damped_wh
                    else:
                        sum_forecast_tomorrow_raw += damped_wh
                        tomorrow_hourly_raw[h - 24] += damped_wh

                # If the provider already aggregated the full PV
                # system into one fetch (e.g. Solcast Rooftop Site
                # represents the whole array), we should only consume
                # the result ONCE. Use the first enabled panel for
                # damping (the per-panel local-shading correction)
                # and skip the rest -- otherwise we'd add the same
                # forecast multiple times.
                if self.aggregates_all_panels:
                    break

            if not any_panel_succeeded:
                self.logger.log.warning(
                    f"{self.name}: no enabled panels produced data. Keeping previous values."
                )
                return None

            # --- Adjustment-factor learning (clear/cloudy two-point) ---
            #
            # One global factor cannot fit this system: with a steep
            # (70 deg) panel the real yield beats the raw GTI model far
            # more under DIRECT sun than under diffuse (overcast) light.
            # Observed: on a 26%-cloud day the true factor was ~1.8, on
            # a 69%-cloud day ~1.2 -- the single EWMA settled at ~1.6
            # and was wrong on BOTH kinds of day (overshooting cloudy
            # days, undershooting clear ones).
            #
            # Instead we keep exactly TWO factors -- adj_clear and
            # adj_cloudy -- and interpolate between them by the cloud
            # cover of the hour being predicted. Learning weights the
            # day's observed ratio into both bins proportionally to the
            # day's cloudiness, so a clear day mostly trains adj_clear
            # and an overcast day mostly trains adj_cloudy. All existing
            # guardrails (min data, min sun hours, EWMA alpha, daily
            # change cap, clip to [0.2, 2.0]) stay in place per factor.
            #
            # The legacy 'solar/efficiency' key keeps being written with
            # the day's effective blended factor: it remains the display
            # value and the fallback for providers without cloud data
            # (Solcast).
            pv_measured_today_wh = solar_data.pv_measured_today_wh or 0.0
            theoretical_past_net = sum_forecast_past_today_raw * self.inverter_efficiency

            adj_data = self.statsmanager.get_data('solar', 'efficiency')
            adj_legacy = (adj_data[0] / 100.0) if isinstance(adj_data, list) and len(adj_data) > 0 else (
                (adj_data / 100.0) if adj_data else 1.0)

            def _read_pct(key, default):
                v = self.statsmanager.get_data('solar', key)
                if isinstance(v, list) and v:
                    return v[0] / 100.0
                if isinstance(v, (int, float)) and v:
                    return v / 100.0
                return default

            # Seed both bins from the legacy global factor on first run.
            adj_clear = _read_pct('adj_clear', adj_legacy)
            adj_cloudy = _read_pct('adj_cloudy', adj_legacy)

            alpha = getattr(self.config, "solar_adj_ewma_alpha", 0.3)
            min_theoretical = getattr(self.config, "solar_adj_min_theoretical_wh", 1000.0)
            min_sun_hours = getattr(self.config, "solar_adj_min_sun_hours", 4.0)
            max_daily_change = getattr(self.config, "solar_adj_max_daily_change", 0.20)

            # Daytime-average cloud fraction of the PAST hours today --
            # that's the weather the measured yield was produced under,
            # so it decides how the observation is split between bins.
            cc_past_frac = 0.5  # neutral when no cloud data (Solcast)
            if cloudcover_today is not None:
                try:
                    sr_h = self._iso_hour(sr_t) or 0
                    h_hi = min(now.hour, 23)
                    past_slice = cloudcover_today[sr_h:h_hi + 1]
                    if past_slice:
                        cc_past_frac = max(0.0, min(1.0, (sum(past_slice) / len(past_slice)) / 100.0))
                except Exception:
                    pass

            sun_hours_so_far = self._estimate_sun_hours_so_far(now)
            should_learn = (
                theoretical_past_net > min_theoretical
                and sun_hours_so_far >= min_sun_hours
            )
            if should_learn:
                instantaneous = pv_measured_today_wh / theoretical_past_net
                instantaneous = max(0.2, min(2.0, instantaneous))

                # The factor is a CONTINUOUS line over cloud cover:
                #   adj(cc) = adj_clear*(1-cc) + adj_cloudy*cc
                # (adj_clear / adj_cloudy are just the line's endpoints
                # at 0% and 100% cloud -- not categories.)
                #
                # Today's observation is one point on that line: at
                # cc_past_frac the true factor was `instantaneous`.
                # Correct ONLY the line's error AT THAT POINT (standard
                # LMS update on the two basis weights). A 45%-cloud day
                # thus adjusts the line where 45% lives and preserves
                # its slope -- unlike naively EWMA-ing both endpoints
                # toward the observation, which would slowly flatten
                # the line into a useless average again.
                predicted = adj_clear * (1.0 - cc_past_frac) + adj_cloudy * cc_past_frac
                error = instantaneous - predicted
                step_clear = alpha * (1.0 - cc_past_frac) * error
                step_cloudy = alpha * cc_past_frac * error
                if max_daily_change > 0:
                    step_clear = max(-max_daily_change, min(max_daily_change, step_clear))
                    step_cloudy = max(-max_daily_change, min(max_daily_change, step_cloudy))
                adj_clear = max(0.2, min(2.0, adj_clear + step_clear))
                adj_cloudy = max(0.2, min(2.0, adj_cloudy + step_cloudy))
                self.statsmanager.update_percent_status_data('solar', 'adj_clear', round(adj_clear * 100, 2))
                self.statsmanager.update_percent_status_data('solar', 'adj_cloudy', round(adj_cloudy * 100, 2))

            def _adj_for_cc(cc_pct):
                """Interpolated factor for one hour's cloud cover."""
                cc = max(0.0, min(1.0, (cc_pct or 0) / 100.0))
                return adj_clear * (1.0 - cc) + adj_cloudy * cc

            have_cc_today = cloudcover_today is not None
            have_cc_tomorrow = cloudcover_tomorrow is not None

            # Per-hour application: every raw hour is scaled by the
            # factor matching ITS forecast cloud cover. Falls back to
            # the blended legacy behaviour when the provider delivers
            # no cloud data.
            h_now = now.hour
            if have_cc_today:
                rest_today_final = sum(
                    today_hourly_raw[h] * self.inverter_efficiency * _adj_for_cc(cloudcover_today[h])
                    for h in range(h_now + 1, 24)
                )
                full_day_forecast = sum(
                    today_hourly_raw[h] * self.inverter_efficiency * _adj_for_cc(cloudcover_today[h])
                    for h in range(24)
                )
                # Effective blended factor of today (for display and as
                # the Solcast fallback): full-day weighted mean.
                raw_day = sum(today_hourly_raw) or 1.0
                adj_effective = sum(
                    today_hourly_raw[h] * _adj_for_cc(cloudcover_today[h])
                    for h in range(24)
                ) / raw_day
            else:
                adj_effective = adj_legacy
                rest_today_final = sum_forecast_rest_today_raw * self.inverter_efficiency * adj_effective
                full_day_forecast = (
                    (sum_forecast_past_today_raw
                     + sum_current_hour_wh_raw
                     + sum_forecast_rest_today_raw)
                    * self.inverter_efficiency * adj_effective
                )

            if have_cc_tomorrow:
                total_tomorrow = sum(
                    tomorrow_hourly_raw[h] * self.inverter_efficiency * _adj_for_cc(cloudcover_tomorrow[h])
                    for h in range(24)
                )
            else:
                total_tomorrow = sum_forecast_tomorrow_raw * self.inverter_efficiency * adj_effective

            total_today = pv_measured_today_wh + rest_today_final

            # Keep the legacy keys alive: 'efficiency' is the effective
            # blended factor (display + Solcast fallback).
            if should_learn:
                self.statsmanager.update_percent_status_data('solar', 'adjustment_factor', round(adj_effective, 2))
                self.statsmanager.update_percent_status_data('solar', 'efficiency', round(adj_effective * 100, 2))

            solar_data.update_forecast_today_wh(round(total_today, 2))
            solar_data.update_forecast_tomorrow_wh(round(total_tomorrow, 2))

            self.statsmanager.set_status_data('solar', 'forecast_today_wh', round(total_today, 2))
            self.statsmanager.set_status_data('solar', 'forecast_tomorrow_wh', round(total_tomorrow, 2))
            self.statsmanager.set_status_data('solar', 'forecast_measured_today_wh', round(pv_measured_today_wh, 2))
            self.statsmanager.set_status_data('solar', 'forecast_rest_today_wh', round(rest_today_final, 2))

            # Tag the active provider so the UI can show "Forecast by
            # Solcast / by OpenMeteo".
            self.statsmanager.set_status_data(
                'solar', 'active_provider',
                {"name": str(self.name or "?"), "ts": int(time.time())}
            )

            # Cloud-cover (daytime average + hourly)
            if cloudcover_today is not None:
                try:
                    sr_h_today = self._iso_hour(sr_t) or 0
                    ss_h_today = self._iso_hour(ss_t) or 23
                    day_slice = cloudcover_today[sr_h_today:ss_h_today + 1]
                    avg_today = sum(day_slice) / len(day_slice) if day_slice else 0.0
                    self.statsmanager.set_status_data(
                        'solar', 'cloudcover_today_avg_pct', round(avg_today, 1)
                    )
                    self.statsmanager.set_status_data(
                        'solar', 'cloudcover_today_hourly',
                        {str(i): v for i, v in enumerate(cloudcover_today)}
                    )
                except Exception as e:
                    self.logger.log.debug(f"cloudcover today stats hiccup: {e}")
            if cloudcover_tomorrow is not None:
                try:
                    sr_h_tm = self._iso_hour(sr_tm) or 0
                    ss_h_tm = self._iso_hour(ss_tm) or 23
                    day_slice = cloudcover_tomorrow[sr_h_tm:ss_h_tm + 1]
                    avg_tm = sum(day_slice) / len(day_slice) if day_slice else 0.0
                    self.statsmanager.set_status_data(
                        'solar', 'cloudcover_tomorrow_avg_pct', round(avg_tm, 1)
                    )
                    self.statsmanager.set_status_data(
                        'solar', 'cloudcover_tomorrow_hourly',
                        {str(i): v for i, v in enumerate(cloudcover_tomorrow)}
                    )
                except Exception as e:
                    self.logger.log.debug(f"cloudcover tomorrow stats hiccup: {e}")

            # Per-day history. We capture the day's forecast once -- ideally
            # the morning value -- and freeze it. But "once per day" is too
            # strict: if the morning's primary provider failed (e.g. open-
            # meteo 502) we'd be locked into a 0 for that day even after a
            # fallback provider succeeds an hour later. So we also rewrite
            # when the stored value is 0/missing. Once a real value lands,
            # subsequent fetches won't overwrite it (that's still the
            # frozen-forecast semantics we want).
            today_iso = now.strftime('%Y-%m-%d')
            forecast_by_day = self.statsmanager.get_data('solar', 'forecast_pv_wh_by_day') or {}
            if not isinstance(forecast_by_day, dict):
                forecast_by_day = {}

            # Sanity: prune any pre-existing 0/None entries from the
            # history. A daily PV forecast of 0 is physically impossible
            # outside polar night, so any 0 sitting in the dict is a
            # failed write from a previous cycle and shouldn't pollute
            # the history chart. We rewrite the cleaned dict only if
            # we actually removed something, so this is a no-op on
            # healthy data.
            cleaned = {
                k: v for k, v in forecast_by_day.items()
                if isinstance(v, (int, float)) and v > 0
            }
            if len(cleaned) != len(forecast_by_day):
                forecast_by_day = cleaned
                self.statsmanager.set_status_data(
                    'solar', 'forecast_pv_wh_by_day', forecast_by_day
                )
                self.logger.log.debug(
                    f"[{self.name}] Pruned implausible zero entries from "
                    f"forecast_pv_wh_by_day."
                )

            existing = forecast_by_day.get(today_iso)
            needs_write = (
                today_iso not in forecast_by_day
                or existing is None
                or (isinstance(existing, (int, float)) and existing <= 0)
            )
            if needs_write and full_day_forecast > 0:
                forecast_by_day[today_iso] = round(full_day_forecast, 2)
                self.statsmanager.set_status_data(
                    'solar', 'forecast_pv_wh_by_day', forecast_by_day
                )
                today_hourly_adj = [
                    round(
                        today_hourly_raw[h] * self.inverter_efficiency
                        * (_adj_for_cc(cloudcover_today[h]) if have_cc_today else adj_effective),
                        2,
                    )
                    for h in range(24)
                ]
                hourly_by_day = self.statsmanager.get_data('solar', 'forecast_hourly_wh_by_day') or {}
                if not isinstance(hourly_by_day, dict):
                    hourly_by_day = {}
                hourly_by_day[today_iso] = today_hourly_adj
                self.statsmanager.set_status_data(
                    'solar', 'forecast_hourly_wh_by_day', hourly_by_day
                )
                self.logger.log.info(
                    f"[{self.name}] Captured forecast for {today_iso}: "
                    f"{full_day_forecast:.0f} Wh "
                    f"(hourly peak {max(today_hourly_adj):.0f} Wh)"
                )

            self.logger.log.info(
                f"[{self.name}] Forecast: Today {total_today:.2f} Wh "
                f"(Measured: {pv_measured_today_wh:.0f}, Rest: {rest_today_final:.0f}), "
                f"Tomorrow {total_tomorrow:.2f} Wh (Adj: {adj_effective:.2f})"
            )

            return {
                "current_hour": sum_current_hour_wh_raw,
                "past_today": sum_forecast_past_today_raw,
                "rest_today": sum_forecast_rest_today_raw,
            }

        except Exception as e:
            self.logger.log.exception(f"[{self.name}] Forecast failed: {e}")
            return None
