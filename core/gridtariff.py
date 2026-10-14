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
GridTariff: the time-of-day grid work price (the per-kWh energy
component of the Austrian network fee) with the SNAP/WiNAP discount
windows.

  SNAP  -- 1 Apr .. 30 Sep, 10:00-16:00
  WiNAP -- 1 Oct .. 31 Mar, 23:00-05:00 (spans midnight)

WiNAP is NOT in force yet: per the final E-Control SNE-G-V it first
takes effect with the winter half-year 2027/28 (1 Oct 2027). The
winter months Jan-Mar 2027 still belong to the season that started in
Oct 2026 and carry no WiNAP. zone_active() therefore gates WiNAP on
the season's start year (WINAP_FIRST_SEASON_YEAR). SNAP has been in
force since 1 Apr 2026 and needs no gate.

Both are a percentage discount (default 20 %) on the base grid work
price for NE7 (the Austrian low-voltage level), opt-in via a smart
meter with 15-min readout. Only the grid work price is discounted --
energy price, taxes, base/metering fees are untouched. Storage
(medium-/long-term) is excluded from SNAP/WiNAP in the regulation;
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
    WINAP_FROM, WINAP_TO = 23, 5    # 23:00 <= h < 05:00 (next day)
    # WiNAP first takes effect with the winter half-year 2027/28, i.e.
    # 1 Oct 2027 (SNE-G-V as decided by E-Control in Oct 2026). A
    # winter season is identified by the year it STARTS in: Oct-Dec of
    # that year, Jan-Mar of the next one. So Jan-Mar 2027 (= season
    # 2026/27) is still WiNAP-free.
    WINAP_FIRST_SEASON_YEAR = 2027

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
            # Season start year: Oct-Dec belong to this year, Jan-Mar
            # to the previous one. WiNAP only from the 2027/28 season.
            season_year = (dt_local.year if month >= 10
                           else dt_local.year - 1)
            if (season_year >= GridTariff.WINAP_FIRST_SEASON_YEAR
                    and (hour >= GridTariff.WINAP_FROM
                         or hour < GridTariff.WINAP_TO)):
                return True
        if snap_enabled and month in GridTariff.SUMMER_MONTHS:
            if GridTariff.SNAP_FROM <= hour < GridTariff.SNAP_TO:
                return True
        return False

    @classmethod
    def work_price_ct(cls, dt_local, config=None):
        """
        Effective grid work price (ct/kWh) for the given local
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
    def auto_fee_millicents(starttime_utc, config=None):
        """
        The zone-aware grid work price for an item's start time as a
        potency-14 millicent fee (the scale Utils.calculate_fee uses),
        so it can be ADDED to a price directly. 0 when the grid tariff
        is off or no work price is configured.
        """
        try:
            from core.utils import Utils
            from core.timeutilities import TimeUtilities
            local = TimeUtilities.convert_utc_to_local(starttime_utc, False)
            ct = GridTariff.work_price_ct(local, config)
            if ct <= 0:
                return 0
            return int(Utils.convert_to_millicents(ct, 14))
        except Exception as e:
            CustomLogger().log.debug(
                f"grid fee auto-add failed, using 0: {e}")
            return 0

    @staticmethod
    def substitute_grid_fee(fee_str, starttime_utc, config=None):
        """
        Replace every {grid_fee} token in a market fee expression with
        the zone-aware grid work price (ct/kWh) for the item's start
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