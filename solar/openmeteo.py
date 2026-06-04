#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2026 Christian Kvasny chris(at)ckvsoft.at
#

"""
OpenMeteo solar forecast provider.

Subclass of SolarForecastProvider. Only implements fetch_panel_raw:
the heavy lifting (panel iteration, damping, accumulation, learning,
persistence) lives in the abstract base, so this file just translates
the open-meteo API response into the canonical 48-hour Wh layout.
"""

from datetime import datetime, timedelta
import time

import pytz
import requests
from requests.exceptions import RequestException

from solar.abstract_classes.solarforecast import SolarForecastProvider


class OpenMeteo(SolarForecastProvider):
    name = "OpenMeteo"

    def fetch_panel_raw(self, panel):
        timezone = pytz.timezone(self.config.time_zone)
        now = datetime.now(timezone)
        today_str = now.strftime('%Y-%m-%d')
        tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={panel['locLat']}&longitude={panel['locLong']}"
            f"&hourly=global_tilted_irradiance,cloudcover"
            f"&daily=sunrise,sunset"
            f"&timezone={self.config.time_zone}"
            f"&forecast_days=2"
            f"&tilt={panel['angle']}&azimuth={panel['direction']}"
        )

        data = None
        last_error = None
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                data = r.json()
                break
            except RequestException as e:
                last_error = str(e)
                if attempt < 2:
                    self.logger.log.warning(
                        f"Network error (attempt {attempt + 1}): {e}. Retrying..."
                    )
                    time.sleep(1)
                    continue
                else:
                    self.logger.log.error(
                        f"OpenMeteo unreachable after 3 attempts: {e}"
                    )
            except Exception as e:
                last_error = str(e)
                self.logger.log.error(f"Unexpected error during OpenMeteo call: {e}")
                break

        if not data:
            return {"ok": False, "error": last_error or "no data"}

        # Parse hourly arrays
        hourly = data.get('hourly', {}) or {}
        rad_list = hourly.get('global_tilted_irradiance', []) or []
        cc_list = hourly.get('cloudcover', []) or []

        daily = data.get('daily', {}) or {}
        dates = daily.get('time', []) or []
        sunrises = daily.get('sunrise', []) or []
        sunsets = daily.get('sunset', []) or []

        t_idx = self.safe_date_index(dates, today_str, "today")
        tm_idx = self.safe_date_index(dates, tomorrow_str, "tomorrow")
        if t_idx is None or tm_idx is None:
            return {"ok": False, "error": "date index missing in API response"}

        # Build a 48-slot raw Wh array. open-meteo returns GTI (W/m^2)
        # at hourly granularity; we convert via area * efficiency. The
        # base-class applies damping + capping afterwards.
        area = float(panel.get('total_area', 0) or 0)
        eff = float(panel.get('efficiency', 20) or 20) / 100.0

        hourly_wh = [0.0] * 48
        for h in range(min(48, len(rad_list))):
            gti = rad_list[h] or 0.0
            hourly_wh[h] = float(gti) * area * eff

        cc_pct = [None] * 48
        for h in range(min(48, len(cc_list))):
            cc_pct[h] = float(cc_list[h] or 0)

        return {
            "ok": True,
            "hourly_wh_raw": hourly_wh,
            "cloudcover_pct": cc_pct,
            "sunrise_today": sunrises[t_idx] if t_idx < len(sunrises) else None,
            "sunset_today": sunsets[t_idx] if t_idx < len(sunsets) else None,
            "sunrise_tomorrow": sunrises[tm_idx] if tm_idx < len(sunrises) else None,
            "sunset_tomorrow": sunsets[tm_idx] if tm_idx < len(sunsets) else None,
            "error": None,
        }
