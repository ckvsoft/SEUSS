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

"""
GridTariff: the time-of-day grid Arbeitspreis (Netznutzungsentgelt
Arbeitspreis) with the Austrian SNAP/WiNAP discount windows.

  SNAP  -- 1 Apr .. 30 Sep, 10:00-16:00
  WiNAP -- 1 Oct .. 31 Mar, 22:00-04:00 (spans midnight)

Both are a percentage discount (default 20 %) on the base grid
Arbeitspreis for Netzebene 7 (opt-in via a smart meter with 15-min
readout). Only the grid Arbeitspreis is discounted -- energy price,
taxes, base/metering fees are untouched. Storage (Mittel-/
Langfristspeicher) is excluded from SNAP/WiNAP in the regulation;
this implementation assumes a normal household connection (no
storage special-casing).

The fee flows into SEUSS' price math through the {grid_fee} token in
a market's `fee` expression: every item substitutes the token with
the zone-aware ct/kWh for its start time before the fee expression is
parsed, so charging can shift into the discounted windows. The
economic rule stays price-driven: the discount is just an additional
term -- whether shifting actually pays depends on the spot prices.
"""

from core.log import CustomLogger


class GridTariff:
    # SNAP / WiNAP months (1-based). Winter = Oct..Mar, summer = Apr..Sep.
    WINTER_MONTHS = (10, 11, 12, 1, 2, 3)
    SUMMER_MONTHS = (4, 5, 6, 7, 8, 9)
    SNAP_FROM, SNAP_TO = 10, 16     # 10:00 <= h < 16:00
    WINAP_FROM = 22                  # 22:00 <= h < 04:00 (next day)

    @staticmethod
    def zone_active(dt_local, snap_enabled=True, winap_enabled=True):
        """
        True when `dt_local` (a datetime, aware or naive) falls inside
        a discount window. Unknown/missing -> False (no discount).
        """
        if dt_local is None:
            return False
        try:
            month = dt_local.month
            hour = dt_local.hour
        except AttributeError:
            return False
        if winap_enabled and month in GridTariff.WINTER_MONTHS:
            if hour >= GridTariff.WINAP_FROM or hour < 4:
                return True
        if snap_enabled and month in GridTariff.SUMMER_MONTHS:
            if GridTariff.SNAP_FROM <= hour < GridTariff.SNAP_TO:
                return True
        return False

    @classmethod
    def work_price_ct(cls, dt_local, config=None):
        """
        Effective grid Arbeitspreis (ct/kWh) for the given local
        datetime: the configured base value, zone-discounted inside
        SNAP/WiNAP. 0.0 when the base price is not configured.
        """
        try:
            from core.config import Config
            cfg = config if config is not None else Config()
            # One master switch for the whole grid-tariff group.
            if not bool(getattr(cfg, "grid_tariff_enabled", False)):
                return 0.0
            base = float(getattr(cfg, "grid_work_price_ct", 0.0) or 0.0)
            if base <= 0.0:
                return 0.0
            discount = float(getattr(
                cfg, "grid_zone_discount_percent", 0.0) or 0.0)
            discount = max(0.0, min(100.0, discount))
            if discount > 0.0 and cls.zone_active(
                    dt_local,
                    bool(getattr(cfg, "grid_zone_snap_enabled", True)),
                    bool(getattr(cfg, "grid_zone_winap_enabled", True))):
                base *= (1.0 - discount / 100.0)
        except Exception as e:
            CustomLogger().log.debug(
                f"grid tariff lookup failed, using 0: {e}")
            return 0.0
        return round(base, 4)

    @staticmethod
    def substitute_grid_fee(fee_str, starttime_utc, config=None):
        """
        Replace every {grid_fee} token in a market fee expression with
        the zone-aware grid Arbeitspreis (ct/kWh) for the item's start
        time. Unknown / no token -> the string is returned unchanged.
        """
        if not isinstance(fee_str, str) or "{grid_fee}" not in fee_str:
            return fee_str
        try:
            from core.timeutilities import TimeUtilities
            local = TimeUtilities.convert_utc_to_local(starttime_utc, False)
            gf = GridTariff.work_price_ct(local, config)
        except Exception as e:
            CustomLogger().log.debug(
                f"grid fee token substitution failed, using 0: {e}")
            gf = 0.0
        return fee_str.replace("{grid_fee}", f"{gf:.4f}")