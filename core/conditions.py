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

    def __init__(self, itemlist, essunit):
        self.items = itemlist
        self.essunit = essunit
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
