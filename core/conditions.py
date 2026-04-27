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

from datetime import datetime, timedelta, timezone

from core.config import Config
from core.statsmanager import StatsManager
from core.log import CustomLogger
from core.utils import Utils


class ConditionResult:
    def __init__(self):
        self.execute = False
        self.condition = ""


class Conditions:
    """
    Builds and evaluates the charging / discharging / switching conditions.

    Block-based model:
    - Charging is allowed when `now` lies within an active "lowest charge
      block" -- a sliding 60min (configurable) window of consecutive
      quarter items with the cheapest average price.
    - Discharging is allowed when `now` lies within an active "highest
      discharge block", PROVIDED there is enough battery surplus left to
      cover consumption until the next charge block.
    - Switching uses its own block selection (independent count and
      block-minutes) so the user can run smart switches longer than the
      ESS charge window when needed.

    Hard cap is checked against the BLOCK AVERAGE, not the current
    quarter price. So a single expensive 15min slot inside an otherwise
    cheap 60min block won't abort charging mid-block.
    """

    def __init__(self, itemlist, essunit, solardata=None):
        self.items = itemlist
        self.essunit = essunit
        # solardata is optional -- callers that don't have a solar
        # subsystem (or have it disabled) can leave it None. The solar
        # forecast abort condition only registers when both
        # `use_solar_forecast_to_abort` is set AND solardata is present.
        self.solardata = solardata
        self.config = Config()
        self.logger = CustomLogger()
        self.statsmanager = StatsManager()
        self.available_surplus = 0.0
        self.current_price = itemlist.get_current_price()
        self.charging_price_limit = Utils.convert_to_millicents(
            self.config.charging_price_limit
        )
        self.charging_price_hard_cap = Utils.convert_to_millicents(
            self.config.charging_price_hard_cap
        )
        self.available_operation_modes = ["switching", "charging", "discharging"]
        self.conditions_by_operation_mode = {
            mode: {} for mode in self.available_operation_modes
        }
        self.abort_conditions_by_operation_mode = {
            mode + "_abort": {} for mode in self.available_operation_modes
        }

        # Pre-compute the active blocks once. evaluate_conditions reuses
        # them across all three modes.
        self._charge_blocks = self.items.get_lowest_charging_blocks(
            self.config.number_of_lowest_prices_for_charging,
            block_minutes=self.config.charging_block_minutes,
        )
        self._discharge_blocks = self.items.get_highest_discharging_blocks(
            self.config.number_of_highest_prices_for_discharging,
            block_minutes=self.config.discharging_block_minutes,
            exclude_blocks=self._charge_blocks,
            fill_gaps=getattr(self.config, "fill_gaps_with_short_clusters", True),
        )

        # Switching uses its own count, falling back to the charging count
        # if the switching key is absent / zero.
        switching_count = self.config.number_of_lowest_prices_for_switching
        if not switching_count:
            switching_count = self.config.number_of_lowest_prices_for_charging
        self._switching_blocks = self.items.get_lowest_charging_blocks(
            switching_count,
            block_minutes=self.config.switching_block_minutes,
        )

        self._build_charging_conditions()
        self._build_discharging_conditions()
        self._build_switching_conditions()
        self._build_abort_conditions()

    # ------------------------------------------------------------------
    # Logging summary
    # ------------------------------------------------------------------

    def info(self):
        self.logger.log.info(
            f"Current price: {self.items.get_current_price(True)} Cent/kWh"
        )
        avg_today, avg_tomorrow = self.items.get_average_price_by_date(True)
        self.logger.log.info(f"Average price Today: {avg_today} Cent/kWh")
        if avg_tomorrow:
            self.logger.log.info(f"Average price Tomorrow: {avg_tomorrow} Cent/kWh")

        # Group blocks by local date so the log shows the per-day
        # breakdown. With use_second_day=True the totals are typically
        # double the configured count -- one set per day -- which can
        # otherwise look wrong to the user.
        from core.timeutilities import TimeUtilities

        def _by_day(blocks):
            buckets = {}
            for blk in blocks:
                local = TimeUtilities.convert_utc_to_local(
                    blk.get_start_datetime(), False
                )
                if local is None:
                    continue
                key = local.date() if hasattr(local, "date") else None
                if key is None:
                    continue
                buckets.setdefault(key, 0)
                buckets[key] += 1
            return buckets

        charge_by_day = _by_day(self._charge_blocks)
        discharge_by_day = _by_day(self._discharge_blocks)
        switching_by_day = _by_day(self._switching_blocks)

        def _fmt(buckets):
            if not buckets:
                return "0"
            parts = [f"{d.isoformat()}={n}" for d, n in sorted(buckets.items())]
            return f"{sum(buckets.values())} ({', '.join(parts)})"

        self.logger.log.info(
            f"Charging blocks: {_fmt(charge_by_day)} x "
            f"{self.config.charging_block_minutes}min, "
            f"Discharging blocks: {_fmt(discharge_by_day)} x "
            f"{self.config.discharging_block_minutes}min, "
            f"Switching blocks: {_fmt(switching_by_day)} x "
            f"{self.config.switching_block_minutes}min"
        )

        for i, blk in enumerate(self._charge_blocks, start=1):
            self.logger.log.info(
                f"lowestprice_block_{i} {blk.describe(localtime=True)}"
            )
            if self.config.log_level == "DEBUG":
                self.logger.log.debug(
                    f"lowestprice_block_{i} quarters: "
                    f"{blk.describe_quarters(localtime=True)}"
                )

        for i, blk in enumerate(self._discharge_blocks, start=1):
            self.logger.log.info(
                f"highestprice_block_{i} {blk.describe(localtime=True)}"
            )
            if self.config.log_level == "DEBUG":
                self.logger.log.debug(
                    f"highestprice_block_{i} quarters: "
                    f"{blk.describe_quarters(localtime=True)}"
                )

        # SOC summary
        soc_wh = self.essunit.get_battery_current_wh() if self.essunit else 0
        min_soc_wh = self.essunit.get_battery_min_wh() if self.essunit else 0
        if soc_wh and min_soc_wh:
            self.logger.log.info(
                f"Current SOC: {soc_wh / 1000:.2f} kWh, "
                f"Min SOC: {min_soc_wh / 1000:.2f} kWh"
            )

    # ------------------------------------------------------------------
    # Helpers for building condition dicts
    # ------------------------------------------------------------------

    @staticmethod
    def _make_block_active_condition(block):
        """Return a callable that checks 'is now inside this block'."""
        return lambda: block.is_active_now()

    def _build_charging_conditions(self):
        # Always-on rule: price below limit
        self.conditions_by_operation_mode["charging"].update({
            f"charging_price_limit "
            f"({Utils.millicent_to_cent(self.charging_price_limit)}) "
            f"> {Utils.millicent_to_cent(self.current_price)}":
                lambda: self.charging_price_limit > self.current_price
        })

        # One condition per active charge block: "now in block N?"
        for i, blk in enumerate(self._charge_blocks, start=1):
            key = (
                f"lowestprice_block_{i} {blk.describe(localtime=True)} "
                f"active"
            )
            self.conditions_by_operation_mode["charging"][key] = (
                self._make_block_active_condition(blk)
            )

    def _build_discharging_conditions(self):
        # Surplus check first -- pre-compute and stash a description.
        future_high = self.items.get_future_high_blocks_until_next_low(
            self._discharge_blocks, self._charge_blocks
        )
        current_soc, min_soc, required_capacity = (
            self._calculate_available_surplus(future_high)
        )
        # Total minutes of discharging window we still face before next charge:
        future_minutes = sum(
            (blk.get_duration_minutes() or 0) for blk in future_high
        )

        self.conditions_by_operation_mode["discharging"].update({
            f"Discharge allowed: {self.available_surplus / 1000:.2f} kWh "
            f"surplus (SOC: {current_soc / 1000:.2f} kWh, expensive minutes: "
            f"{future_minutes}, required capacity: "
            f"{required_capacity / 1000:.2f} kWh)":
                lambda fh=future_high: self._calculate_discharge_conditions(fh)
        })

        # Per-block "now active" conditions
        for i, blk in enumerate(self._discharge_blocks, start=1):
            key = (
                f"highestprice_block_{i} {blk.describe(localtime=True)} "
                f"active"
            )
            self.conditions_by_operation_mode["discharging"][key] = (
                self._make_block_active_condition(blk)
            )

    def _build_switching_conditions(self):
        # Switching mirrors charging: per-block "now active" check.
        # Hard cap and price limit are NOT applied here -- the switching
        # logic only cares about block membership. The abort conditions
        # below handle cap behaviour separately.
        for i, blk in enumerate(self._switching_blocks, start=1):
            key = (
                f"switch_block_{i} {blk.describe(localtime=True)} active"
            )
            self.conditions_by_operation_mode["switching"][key] = (
                self._make_block_active_condition(blk)
            )

    def _build_abort_conditions(self):
        """
        Hard caps and overrides. Hard cap is checked against the
        currently active charging block's AVERAGE price, not the current
        quarter -- so a single expensive quarter inside an otherwise cheap
        block doesn't abort the block mid-run.
        """
        self.abort_conditions_by_operation_mode["charging_abort"].update({
            "Abort charge condition - Block average exceeds hard cap":
                self._abort_charging_block_above_hard_cap
        })

        # Solar forecast abort: skip charging when both
        #   (a) total expected solar (today + tomorrow) covers two days
        #       of average consumption, AND
        #   (b) current SOC alone covers consumption until the next solar
        #       event.
        # Both must hold -- (a) alone would drain the battery overnight
        # if today is mostly past; (b) alone would skip charging on a
        # week of bad weather. Together they only skip when we're truly
        # in the comfort zone.
        #
        # Only registered when the config flag is on AND we actually have
        # solardata to check against. The user can flip the flag without
        # restart -- conditions are rebuilt on every evaluation cycle.
        if (getattr(self.config, "use_solar_forecast_to_abort", False)
                and self.solardata is not None):
            self.abort_conditions_by_operation_mode["charging_abort"].update({
                "Abort charge - solar forecast covers consumption "
                "and battery is sufficient":
                    self._abort_charging_solar_forecast_sufficient
            })

        # Battery-range abort: skip charging when the current battery
        # state alone covers consumption until the next equally-cheap-
        # or-cheaper future charge cluster. Independent of solar -- this
        # is for runs when there's no usable solar (winter, indoor PV)
        # but the user still wants to avoid topping up at a less-cheap
        # cluster when a cheaper one is coming up later in the day.
        #
        # Registered AFTER the solar abort: when both flags are on, the
        # solar check runs first and a True there short-circuits this
        # one (see evaluate_conditions, which breaks on the first
        # matching abort).
        if getattr(self.config, "skip_charge_when_battery_sufficient", False):
            self.abort_conditions_by_operation_mode["charging_abort"].update({
                "Abort charge - battery covers consumption "
                "until next equally-cheap charge cluster":
                    self._abort_charging_battery_reaches_next_cluster
            })

        # Switching uses the same hard cap rule by default.
        self.abort_conditions_by_operation_mode["switching_abort"].update({
            "Abort switching - Block average exceeds hard cap":
                self._abort_switching_block_above_hard_cap
        })

        self.abort_conditions_by_operation_mode["discharging_abort"].update({
            "Abort discharge while charging is allowed":
                lambda: any(
                    c() for c in
                    self.conditions_by_operation_mode.get("charging", {}).values()
                )
        })

    def _abort_charging_block_above_hard_cap(self):
        """
        True if any charging-condition is matched but the CURRENT QUARTER
        (the item that contains 'now') has a price above the hard cap.

        We deliberately check the per-quarter price rather than the
        block average -- so a single expensive quarter inside an
        otherwise cheap charge cluster will pause SEUSS for that 15 min
        rather than letting it charge anyway. This mirrors the chart,
        where such quarters show as olive instead of green.
        """
        return self._current_quarter_above_hard_cap()

    def _abort_switching_block_above_hard_cap(self):
        return self._current_quarter_above_hard_cap()

    def _abort_charging_solar_forecast_sufficient(self):
        """
        True if BOTH of these hold:
          (a) Today's + tomorrow's adjusted solar forecast covers at
              least two days of average consumption.
          (b) Current battery SOC alone covers consumption until the
              next "solar event" (sunrise tomorrow if we're past sunset
              today, end of today's daylight otherwise) plus a safety
              margin.

        The double check is on purpose. Either condition alone has a
        well-known failure mode:

          * (a) alone fails when the day is mostly over -- we'd skip
            charging tonight on the strength of "tomorrow will be
            sunny", then drain the battery overnight.
          * (b) alone fails on a streak of bad-weather days -- the SOC
            check works for the next 12h but doesn't see that day 2/3/4
            won't recharge either.

        Combining them means we only skip charging when we're in the
        comfort zone on BOTH the long horizon (forecast) and the short
        horizon (battery). Anything else -> charging stays allowed.

        Returns False on any error or missing data, which is the safe
        side: we'd rather charge a battery we didn't need to than skip
        charging we did need.
        """
        try:
            sd = self.solardata
            if sd is None:
                return False

            # ---- (a) Two-day horizon: forecast vs consumption ----
            forecast_today = sd.total_current_day or 0.0
            forecast_tomorrow = sd.total_tomorrow_day or 0.0
            total_forecast_wh = forecast_today + forecast_tomorrow

            # Consumption baseline. `daily_watt_average` from the stats
            # manager is the projected hourly-average consumption in
            # Wh/h (despite the name -- see
            # PowerConsumptionBase.get_daily_average which divides
            # projected daily Wh by 24). So:
            #   avg_hourly_wh        = avg_list[0]   # Wh per hour
            #   one-day consumption  = avg_hourly_wh * 24
            #   two-day consumption  = avg_hourly_wh * 48
            avg_list = self.statsmanager.get_data(
                "powerconsumption", "daily_watt_average"
            )
            avg_hourly_wh = (
                round(avg_list[0], 2)
                if isinstance(avg_list, (list, tuple)) and avg_list
                else 0.0
            )

            # If we have no consumption history yet (fresh install,
            # stats reset, etc.) we can't honestly evaluate either
            # condition. Defer -- charging stays allowed until we have
            # data to reason about.
            if avg_hourly_wh <= 0:
                self.logger.log.debug(
                    "Solar abort: no consumption history yet, "
                    "keeping charging allowed."
                )
                return False

            two_day_consumption_wh = avg_hourly_wh * 48.0

            condition_a = total_forecast_wh >= two_day_consumption_wh

            # ---- (b) Short horizon: SOC vs consumption-until-solar ----
            from core.timeutilities import TimeUtilities
            now = TimeUtilities.get_now()

            target_dt = self._next_solar_target(now)
            if target_dt is None:
                # Missing sunrise/sunset data -> can't safely evaluate.
                self.logger.log.debug(
                    "Solar abort: sunrise/sunset data missing, "
                    "keeping charging allowed."
                )
                return False

            hours_until_solar = max(
                (target_dt - now).total_seconds() / 3600.0, 0.0
            )

            # Required reserve in Wh: hourly avg * hours-until-solar +
            # 10% safety buffer (mirrors the discharge-side calculation).
            required_until_solar_wh = (
                avg_hourly_wh * hours_until_solar * 1.10
            )

            current_soc_wh = (
                self.essunit.get_battery_current_wh()
                if self.essunit else 0
            ) or 0
            min_soc_wh = (
                self.essunit.get_battery_min_wh()
                if self.essunit else 0
            ) or 0

            usable_soc_wh = max(0.0, current_soc_wh - min_soc_wh)

            condition_b = usable_soc_wh >= required_until_solar_wh

            self.logger.log.debug(
                f"Solar abort check: "
                f"(a) forecast={total_forecast_wh:.0f}Wh "
                f"vs 2-day consumption={two_day_consumption_wh:.0f}Wh "
                f"-> {condition_a}; "
                f"(b) usable_soc={usable_soc_wh:.0f}Wh "
                f"vs required_until_solar={required_until_solar_wh:.0f}Wh "
                f"(over {hours_until_solar:.1f}h) -> {condition_b}"
            )

            return condition_a and condition_b

        except Exception as e:
            self.logger.log.error(
                f"Solar forecast abort check failed: {e}. "
                "Keeping charging allowed."
            )
            return False

    def _next_solar_target(self, now):
        """
        Return the next "meaningful solar event" datetime (in local
        timezone) the battery has to hold out for. We always use
        tomorrow's sunrise as the conservative target -- the SOC has to
        last through the rest of today AND the night, because today's
        remaining yield may be small.

        Returns None if sunrise data is missing or unparseable.
        """
        sd = self.solardata
        if sd is None:
            return None

        sunrise_str = sd.sunrise_tomorrow_day
        if not sunrise_str:
            return None

        from datetime import datetime
        from core.timeutilities import TimeUtilities

        try:
            naive = datetime.strptime(sunrise_str, "%Y-%m-%dT%H:%M")
            # OpenMeteo returns sunrise in the requested timezone (we
            # pass `timezone=config.time_zone`), so the naive value is
            # already wall-clock local time. Attach the same tz that
            # `now` carries so the subtraction below is valid. With
            # pytz that needs localize(), not replace().
            tz = getattr(TimeUtilities, "TZ", None)
            if tz is not None and hasattr(tz, "localize"):
                return tz.localize(naive)
            # Fallback for non-pytz tzinfo (e.g. zoneinfo)
            return naive.replace(tzinfo=tz) if tz else naive
        except (ValueError, TypeError) as e:
            self.logger.log.debug(
                f"Solar abort: cannot parse sunrise '{sunrise_str}': {e}"
            )
            return None

    # ------------------------------------------------------------------
    # Battery-range abort
    # ------------------------------------------------------------------

    def _abort_charging_battery_reaches_next_cluster(self):
        """
        True if the user has enabled `skip_charge_when_battery_sufficient`
        AND we can confidently skip the current charge attempt because
        the battery will hold us until a future, at-least-equally-cheap
        charge cluster.

        Decision tree:
          1. If current_price <= charging_price_limit:
             -- the always-on safety floor wins, NEVER skip. The
                user explicitly asked "always charge below this price".
          2. Find the next future, non-expired, non-active charge block
             whose avg price is <= the currently active block's avg.
             -- if NONE: the current cluster IS the cheapest left;
                skipping it means we'd later charge at a higher price.
                Don't skip.
          3. Compute hours_until_target = start of that block - now.
          4. Required Wh = avg_hourly_consumption * hours * 1.10
             (10% safety buffer, mirrors discharge calc).
          5. Usable SOC = current_soc_wh - min_soc_wh.
          6. Skip iff usable_soc >= required.

        Like the solar abort, returns False on any error or missing
        data -- charging stays allowed when in doubt.
        """
        try:
            # Step 1: charging_price_limit is a hard "always charge" rule.
            # Never let this abort override that.
            cur = self.items.get_current_price(convert=False)
            if cur is not None:
                try:
                    if int(cur) <= self.charging_price_limit:
                        self.logger.log.debug(
                            "Battery-range abort: current price "
                            f"({Utils.millicent_to_cent(cur)} c) at or "
                            "below charging_price_limit -- not skipping."
                        )
                        return False
                except (TypeError, ValueError):
                    pass  # fall through and let the rest decide

            # Step 2: find the cheaper-or-equal future block.
            target_block = self._find_next_cheaper_or_equal_charge_block()
            if target_block is None:
                self.logger.log.debug(
                    "Battery-range abort: no future charge block at "
                    "current price level or cheaper -- not skipping."
                )
                return False

            # Step 3: hours until that block starts.
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)
            block_start = target_block.get_start_datetime()
            if block_start is None:
                return False
            if block_start.tzinfo is None:
                block_start = block_start.replace(tzinfo=timezone.utc)
            hours_until = max(
                (block_start - now_utc).total_seconds() / 3600.0, 0.0
            )

            # Step 4: required reserve.
            avg_list = self.statsmanager.get_data(
                "powerconsumption", "daily_watt_average"
            )
            avg_hourly_wh = (
                round(avg_list[0], 2)
                if isinstance(avg_list, (list, tuple)) and avg_list
                else 0.0
            )
            if avg_hourly_wh <= 0:
                # No history -> can't decide safely.
                self.logger.log.debug(
                    "Battery-range abort: no consumption history yet, "
                    "not skipping."
                )
                return False

            required_wh = avg_hourly_wh * hours_until * 1.10

            # Step 5: usable SOC headroom.
            current_soc_wh = (
                self.essunit.get_battery_current_wh()
                if self.essunit else 0
            ) or 0
            min_soc_wh = (
                self.essunit.get_battery_min_wh()
                if self.essunit else 0
            ) or 0
            usable_soc_wh = max(0.0, current_soc_wh - min_soc_wh)

            # Step 6: decision.
            should_skip = usable_soc_wh >= required_wh

            self.logger.log.debug(
                f"Battery-range abort: target_block "
                f"{target_block.describe(localtime=True)} "
                f"(starts in {hours_until:.1f}h), "
                f"required={required_wh:.0f}Wh, "
                f"usable_soc={usable_soc_wh:.0f}Wh, "
                f"skip={should_skip}"
            )
            return should_skip

        except Exception as e:
            self.logger.log.error(
                f"Battery-range abort check failed: {e}. "
                "Keeping charging allowed."
            )
            return False

    def _find_next_cheaper_or_equal_charge_block(self):
        """
        From the pre-computed `_charge_blocks`, return the earliest
        future (non-expired, non-currently-active) block whose average
        price is <= the price level we'd be charging at right now.

        "Right now's price level" is:
          * the avg of the currently active charge block, if any;
          * otherwise the current per-quarter price.

        Returns None if no such block exists (current attempt is the
        cheapest remaining option).
        """
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)

        # Establish the price reference -- what would we be paying if
        # we charged in this evaluation cycle?
        active_block = None
        for blk in self._charge_blocks:
            if blk.is_active_now():
                active_block = blk
                break

        if active_block is not None:
            reference_price = active_block.get_avg_price(convert=False)
        else:
            cur = self.items.get_current_price(convert=False)
            if cur is None:
                return None
            try:
                reference_price = int(cur)
            except (TypeError, ValueError):
                return None

        # Walk all future charge blocks, pick the earliest one that's
        # cheaper or equal. We sort by start time so "earliest" actually
        # means earliest -- the input list is greedy-by-price, not by
        # time.
        candidates = []
        for blk in self._charge_blocks:
            if blk is active_block:
                continue
            if blk.is_expired():
                continue
            blk_start = blk.get_start_datetime()
            if blk_start is None:
                continue
            if blk_start.tzinfo is None:
                blk_start = blk_start.replace(tzinfo=timezone.utc)
            if blk_start <= now_utc:
                # Active or already-started but not expired -- treat as
                # "now" and skip (we'd be charging right now anyway if
                # we wanted to).
                continue
            try:
                if blk.get_avg_price(convert=False) <= reference_price:
                    candidates.append((blk_start, blk))
            except (TypeError, ValueError):
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    def _current_quarter_above_hard_cap(self):
        """
        Return True iff the item that covers 'now' has a price above
        the configured hard cap. Used for both charging and switching
        abort conditions. Falls back to False when no item covers now
        (e.g. data gap) -- in that case the caller's normal evaluation
        decides.
        """
        cur = self.items.get_current_price(convert=False)
        if cur is None:
            return False
        try:
            return int(cur) > self.charging_price_hard_cap
        except (TypeError, ValueError):
            return False

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_conditions(self, condition_result, operation_mode):
        if operation_mode not in self.available_operation_modes:
            self.logger.log.error(f"Invalid operation mode: {operation_mode}")
            return

        matched = False
        for key, func in self.conditions_by_operation_mode.get(
                operation_mode, {}).items():
            try:
                result = func()
                self.logger.log.debug(
                    f"Evaluating condition: {key} - Result: {result}"
                )
                if result and not condition_result.condition:
                    condition_result.execute = True
                    condition_result.condition = key
                    matched = True
                    if self.config.log_level != "DEBUG":
                        break
            except Exception as e:
                self.logger.log.error(f"Error evaluating condition {key}: {e}")

        if not matched:
            self.logger.log.debug(
                "No conditions matched. Skipping abort conditions."
            )
            return

        for key, func in self.abort_conditions_by_operation_mode.get(
                operation_mode + "_abort", {}).items():
            try:
                if func():
                    condition_result.execute = False
                    condition_result.condition = key
                    break
            except Exception as e:
                self.logger.log.error(
                    f"Error evaluating abort condition {key}: {e}"
                )

    # ------------------------------------------------------------------
    # Surplus / discharge math
    # ------------------------------------------------------------------

    def _calculate_required_capacity(self, future_high_blocks):
        """
        Required reserve = expected average consumption rate * minutes
        we still need to cover before the next charge block.
        """
        avg_list = self.statsmanager.get_data(
            "powerconsumption", "hourly_watt_average"
        )
        avg_consumption_per_hour = round(avg_list[0], 2) if avg_list else 0
        total_minutes = sum(
            (blk.get_duration_minutes() or 0) for blk in future_high_blocks
        )
        # Convert to hours, apply 10% safety buffer like before.
        required = (total_minutes / 60.0) * avg_consumption_per_hour * 1.10
        self.logger.log.debug(f"Required capacity: {required:.2f} Wh")
        return required

    def _calculate_available_surplus(self, future_high_blocks):
        if not self.essunit:
            self.available_surplus = 0
            return 0, 0, 0
        current_soc = self.essunit.get_battery_current_wh() or 0
        min_soc = self.essunit.get_battery_min_wh() or 0
        required = self._calculate_required_capacity(future_high_blocks)
        buffer = 0.10 * current_soc
        self.available_surplus = max(
            0, current_soc - min_soc - buffer - required
        )
        self.logger.log.debug(
            f"Available surplus: {self.available_surplus:.2f} Wh"
        )
        return current_soc, min_soc, required

    def _calculate_discharge_conditions(self, future_high_blocks):
        if not self.essunit:
            return False
        current_soc = self.essunit.get_battery_current_wh() or 0
        min_soc = self.essunit.get_battery_min_wh() or 0
        required = self._calculate_required_capacity(future_high_blocks)

        if future_high_blocks:
            max_dischargeable = current_soc - (required + min_soc)
            if max_dischargeable < 0:
                return False
            return min(self.available_surplus, max_dischargeable) > 0

        return self.available_surplus > 0

    # ------------------------------------------------------------------
    # External access (used by web layer)
    # ------------------------------------------------------------------

    def get_charge_blocks(self):
        return self._charge_blocks

    def get_discharge_blocks(self):
        return self._discharge_blocks

    def get_switching_blocks(self):
        return self._switching_blocks
