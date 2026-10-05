#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2026 Christian Kvasny chris(at)ckvsoft.at
#

"""
Solcast solar forecast provider (Hobbyist tier).

Solcast Hobbyist API:
  - Endpoint:   https://api.solcast.com.au/rooftop_sites/{RESOURCE_ID}/forecasts?format=json
  - Auth:       Bearer token via Authorization header
  - Quota:      10 API calls / day per account (Hobbyist)
  - Granularity: 30-minute slots, in kW
  - Forecast horizon: ~7 days

To stay within the 10-call/day budget while being polled every ~5min
from seusscore, we cache the result in StatsManager and only re-fetch
when `min_interval_minutes` has elapsed since the last successful
call. The cache survives restarts.

Resource IDs are configured per provider (comma-separated string),
NOT per panel -- Solcast already knows your panel specs via the
rooftop site you registered. The cap is 2 rooftops for hobbyists.

This subclass behaves like OpenMeteo from the base class's point of
view: returns the same 48-hour Wh layout plus sunrise/sunset (which
Solcast does NOT provide directly -- we compute sunrise as "first
slot with non-zero forecast" and sunset symmetrically; the dampers
work with whatever we give them).
"""

import json
import time
from datetime import datetime, timedelta

import pytz
import requests
from requests.exceptions import RequestException

from solar.abstract_classes.solarforecast import SolarForecastProvider


class Solcast(SolarForecastProvider):
    name = "Solcast"
    # Solcast Rooftop Site already represents the user's entire PV
    # system (1-2 rooftops covering all panels). One Solcast call
    # returns the WHOLE forecast, so the base class must consume it
    # only once, not once per SEUSS-side panel.
    aggregates_all_panels = True
    BASE_URL = "https://api.solcast.com.au/rooftop_sites/{}/forecasts"

    # Default throttle if the config doesn't specify. 90 min => 16
    # calls/day, just above Hobbyist's hard 10/day limit for two
    # sites. Users should override to 180 (8 calls/day) for safety
    # if they have two rooftops.
    DEFAULT_MIN_INTERVAL_MIN = 90

    def __init__(self):
        super().__init__()
        # The same Solcast response is good for all panels (it's per-
        # rooftop, and the rooftop covers the panel's specs). Cache
        # the per-resource_id response across panel iterations in one
        # forecast() call to avoid making the same request twice.
        self._call_cache = {}

    # --------------------------------------------------------------
    # Config accessors
    # --------------------------------------------------------------

    @property
    def resource_ids(self):
        """
        Comma- or pipe-separated list of rooftop resource IDs from
        the provider config. Parsed lazily, returns [] if empty.
        """
        raw = self._provider_config().get("resource_ids", "") or ""
        if not raw:
            return []
        # Accept comma OR pipe separators -- pipes match the smart-
        # switches convention elsewhere in the config.
        parts = [p.strip() for p in raw.replace("|", ",").split(",")]
        return [p for p in parts if p]

    @property
    def min_interval_minutes(self):
        try:
            return float(self._provider_config().get(
                "min_interval_minutes", self.DEFAULT_MIN_INTERVAL_MIN
            ))
        except (TypeError, ValueError):
            return self.DEFAULT_MIN_INTERVAL_MIN

    # --------------------------------------------------------------
    # Cache helpers
    # --------------------------------------------------------------

    def _cache_key(self, resource_id):
        return f"solcast_cache_{resource_id}"

    def _read_cache(self, resource_id):
        """
        Returns (last_fetch_epoch, payload_dict) or (0, None) when no
        cache or unreadable. Payload is the parsed JSON from Solcast.
        """
        try:
            entry = self.statsmanager.get_data("solar", self._cache_key(resource_id))
            if isinstance(entry, dict) and "ts" in entry and "payload_json" in entry:
                payload = json.loads(entry["payload_json"])
                return float(entry["ts"]), payload
        except Exception as e:
            self.logger.log.debug(f"Solcast cache read failed for {resource_id}: {e}")
        return 0.0, None

    def _write_cache(self, resource_id, payload):
        try:
            entry = {
                "ts": time.time(),
                "payload_json": json.dumps(payload, separators=(",", ":")),
            }
            self.statsmanager.set_status_data(
                "solar", self._cache_key(resource_id), entry
            )
        except Exception as e:
            self.logger.log.debug(f"Solcast cache write failed for {resource_id}: {e}")

    # --------------------------------------------------------------
    # API call
    # --------------------------------------------------------------

    def _http_get(self, resource_id):
        """
        Fetch fresh data from Solcast. Returns the parsed JSON dict
        or None on any error.
        """
        url = self.BASE_URL.format(resource_id) + "?format=json"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 429:
                self.logger.log.warning(
                    "Solcast quota exceeded (429). "
                    "Hobbyist tier is 10 calls/day. "
                    "Increase min_interval_minutes in config."
                )
                return None
            r.raise_for_status()
            return r.json()
        except RequestException as e:
            self.logger.log.error(f"Solcast API error for {resource_id}: {e}")
            return None
        except Exception as e:
            self.logger.log.error(f"Unexpected Solcast error for {resource_id}: {e}")
            return None

    def _get_or_fetch(self, resource_id):
        """
        Return Solcast data for this resource, using cache when it's
        still within the throttle window. Falls back to stale cache
        if a fresh fetch fails -- a stale forecast is better than no
        forecast at all.
        """
        # Per-call dedup so multiple panels with the same resource_id
        # share one HTTP request inside a single forecast() pass.
        if resource_id in self._call_cache:
            return self._call_cache[resource_id]

        last_ts, cached = self._read_cache(resource_id)
        age_min = (time.time() - last_ts) / 60.0 if last_ts else float("inf")

        if cached is not None and age_min < self.min_interval_minutes:
            self.logger.log.debug(
                f"Solcast: using cached forecast for {resource_id} "
                f"(age {age_min:.0f} min, throttle {self.min_interval_minutes:.0f} min)"
            )
            self._call_cache[resource_id] = cached
            return cached

        self.logger.log.info(
            f"Solcast: fetching fresh forecast for {resource_id}"
        )
        fresh = self._http_get(resource_id)
        if fresh is not None:
            self._write_cache(resource_id, fresh)
            self._call_cache[resource_id] = fresh
            return fresh

        # Fetch failed -- fall back to cached even if stale.
        if cached is not None:
            self.logger.log.warning(
                f"Solcast fetch failed, using stale cache "
                f"({age_min:.0f} min old) for {resource_id}"
            )
            self._call_cache[resource_id] = cached
            return cached

        return None

    # --------------------------------------------------------------
    # Hook implementation
    # --------------------------------------------------------------

    def fetch_panel_raw(self, panel):
        """
        Map Solcast's 30-minute kW forecast to the canonical 48-hour
        Wh layout. Solcast only returns FUTURE values (from now onward),
        so the past-today hours are filled from the user's actual
        measured PV yield (pv_wh_by_hour_today from PowerConsumption).
        We back-scale the measured values by the current adjustment
        factor and inverter efficiency so the base class's forward-
        scaling restores them to the true measured Wh.

        Solcast cap and tilt/azimuth are stored at Solcast per rooftop,
        so we don't pass panel specs in the HTTP call (they would be
        ignored). The base class still applies the local damping
        factors from `panel` afterwards.
        """
        if not self.api_key:
            return {"ok": False, "error": "No Solcast api_key configured"}
        if not self.resource_ids:
            return {"ok": False, "error": "No Solcast resource_ids configured"}

        # Hobbyist accounts have up to 2 rooftops. We sum power across
        # all of them so the user can model multi-orientation roofs.
        agg_30min = {}  # iso period_end -> kW summed across resources
        any_resource_ok = False
        last_error = None

        for resource_id in self.resource_ids:
            payload = self._get_or_fetch(resource_id)
            if not payload:
                last_error = f"no data for {resource_id}"
                continue
            forecasts = payload.get("forecasts", [])
            if not forecasts:
                last_error = f"empty forecasts for {resource_id}"
                continue
            any_resource_ok = True
            for f in forecasts:
                pe = f.get("period_end")
                if not pe:
                    continue
                kw = float(f.get("pv_estimate", 0) or 0)
                agg_30min[pe] = agg_30min.get(pe, 0.0) + kw

        if not any_resource_ok or not agg_30min:
            return {
                "ok": False,
                "error": last_error or "Solcast returned no data for any resource",
            }

        # Convert the dict-of-30min-slots to a 48-hour Wh array
        # aligned to local midnight today.
        timezone = pytz.timezone(self.config.time_zone)
        now = datetime.now(timezone)
        midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cur_hour = now.hour

        hourly_wh = [0.0] * 48
        for pe_iso, kw_sum in agg_30min.items():
            try:
                pe_dt = datetime.fromisoformat(pe_iso.replace("Z", "+00:00"))
                pe_local = pe_dt.astimezone(timezone)
            except Exception:
                continue

            # period_end marks the END of the 30-min slot, so the slot
            # covers [pe_local - 30min, pe_local). Bucket by the slot
            # midpoint to avoid edge ambiguities on the hour boundary.
            mid = pe_local - timedelta(minutes=15)
            hours_from_midnight = (mid - midnight_today).total_seconds() / 3600.0
            slot_hour = int(hours_from_midnight)
            if 0 <= slot_hour < 48:
                # kw_sum * 0.5h = kWh in this 30-min slot, *1000 = Wh
                hourly_wh[slot_hour] += kw_sum * 0.5 * 1000.0

        # Solcast only sends FUTURE values, so past-today hours in the
        # array are 0. Fill them from the measured PV history so the
        # base class's "past_today" sum reflects reality and the
        # adjustment-factor learning loop sees something to learn from.
        # Back-scale by inverter_efficiency * adj so that the base
        # class's forward-scaling reproduces the measured value.
        try:
            measured_by_hour = self.statsmanager.get_data(
                "powerconsumption", "pv_wh_by_hour_today"
            ) or {}
            if not isinstance(measured_by_hour, dict):
                measured_by_hour = {}

            # The base class multiplies hourly_wh_raw by
            # inverter_efficiency * adj at persist time, so we have
            # to divide here. adj is the EWMA-smoothed factor stored
            # under solar.efficiency (as percent).
            adj_data = self.statsmanager.get_data('solar', 'efficiency')
            if isinstance(adj_data, list) and len(adj_data) > 0:
                adj = adj_data[0] / 100.0
            elif adj_data:
                adj = adj_data / 100.0
            else:
                adj = 1.0
            scale = self.inverter_efficiency * adj
            if scale <= 0:
                scale = 1.0  # safety: never divide by 0

            for h in range(cur_hour):
                measured_wh = measured_by_hour.get(str(h), 0) or 0
                try:
                    measured_wh = float(measured_wh)
                except (TypeError, ValueError):
                    measured_wh = 0.0
                if measured_wh > 0:
                    # No division across panels here: aggregates_all_panels
                    # is True, so the base class consumes our output only
                    # once. Back-scale by inverter_efficiency * adj so
                    # the base's forward-scaling reproduces the measured
                    # value.
                    hourly_wh[h] = measured_wh / scale
        except Exception as e:
            self.logger.log.debug(f"Solcast past-fill from measured failed: {e}")

        # Solcast doesn't return sunrise/sunset directly -- derive them
        # from the first/last non-zero slot. We look at both past
        # (measured) and future (forecast) to get the full envelope.
        sr_today = self._first_nonzero_hour_iso(hourly_wh[:24], midnight_today)
        ss_today = self._last_nonzero_hour_iso(hourly_wh[:24], midnight_today)
        sr_tomorrow = self._first_nonzero_hour_iso(
            hourly_wh[24:], midnight_today + timedelta(days=1)
        )
        ss_tomorrow = self._last_nonzero_hour_iso(
            hourly_wh[24:], midnight_today + timedelta(days=1)
        )

        return {
            "ok": True,
            "hourly_wh_raw": hourly_wh,
            "cloudcover_pct": None,  # Solcast doesn't expose cloud cover
            "sunrise_today": sr_today,
            "sunset_today": ss_today,
            "sunrise_tomorrow": sr_tomorrow,
            "sunset_tomorrow": ss_tomorrow,
            "error": None,
        }

    @staticmethod
    def _first_nonzero_hour_iso(hourly, day_midnight):
        for h, v in enumerate(hourly):
            if v > 1:  # >1 Wh = "real" sun, not numeric noise
                t = day_midnight + timedelta(hours=h)
                return t.strftime("%Y-%m-%dT%H:%M")
        return None

    @staticmethod
    def _last_nonzero_hour_iso(hourly, day_midnight):
        for h in range(len(hourly) - 1, -1, -1):
            if hourly[h] > 1:
                t = day_midnight + timedelta(hours=h)
                return t.strftime("%Y-%m-%dT%H:%M")
        return None
