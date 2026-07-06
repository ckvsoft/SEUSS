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
        # Total minutes of discharging window we still face before next
        # charge. For a block that's currently active we want the
        # REMAINING duration, not the full one -- otherwise the log
        # line keeps reporting 120 minutes for a 2h block until it
        # fully expires, even though only 30 minutes are actually left.
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        future_minutes = 0
        for blk in future_high:
            blk_end = blk.get_end_datetime() if hasattr(blk, "get_end_datetime") else None
            if blk_end is None:
                # Fallback: compute from start + total duration.
                blk_start = blk.get_start_datetime()
                if blk_start is None:
                    continue
                if blk_start.tzinfo is None:
                    blk_start = blk_start.replace(tzinfo=timezone.utc)
                from datetime import timedelta
                blk_end = blk_start + timedelta(minutes=blk.get_duration_minutes() or 0)
            if blk_end.tzinfo is None:
                blk_end = blk_end.replace(tzinfo=timezone.utc)
            remaining_seconds = max(0, (blk_end - now_utc).total_seconds())
            future_minutes += int(remaining_seconds / 60)

        # Smart-discharge priority: if the user has enabled it AND the
        # battery's usable energy can't cover the FULL remaining
        # expensive phase, pre-compute a set of allowed discharge
        # blocks that prioritises the most expensive ones. Cheaper
        # discharge blocks get dropped from the allow-set so the grid
        # covers them instead, saving the battery for the priciest
        # hours. The set is rebuilt on every Conditions instantiation,
        # so it reflects the current SOC each evaluation cycle.
        self._discharge_allow_set = self._compute_smart_discharge_allow_set(
            future_high, current_soc, min_soc
        )

        self.conditions_by_operation_mode["discharging"].update({
            f"Discharge allowed: {self.available_surplus / 1000:.2f} kWh "
            f"surplus (SOC: {current_soc / 1000:.2f} kWh, expensive minutes: "
            f"{future_minutes}, required capacity: "
            f"{required_capacity / 1000:.2f} kWh)":
                lambda fh=future_high: self._calculate_discharge_conditions(fh)
        })

        # Per-block "now active" conditions. When smart-discharge is
        # active and a block is NOT in the allow-set, we replace the
        # active-now check with a constant False so the block never
        # triggers discharge -- letting the grid cover that block's
        # hours instead.
        for i, blk in enumerate(self._discharge_blocks, start=1):
            key = (
                f"highestprice_block_{i} {blk.describe(localtime=True)} "
                f"active"
            )
            if (self._discharge_allow_set is not None
                    and blk not in self._discharge_allow_set):
                # Smart-discharge says: skip this block, save the
                # battery for pricier blocks. Mark with a clear key
                # so the user can see in the log why discharge didn't
                # fire here.
                key = (
                    f"highestprice_block_{i} {blk.describe(localtime=True)} "
                    f"SKIPPED by smart-discharge (battery prioritised "
                    f"to higher-priced blocks)"
                )
                self.conditions_by_operation_mode["discharging"][key] = (
                    lambda: False
                )
            else:
                self.conditions_by_operation_mode["discharging"][key] = (
                    self._make_block_active_condition(blk)
                )

    def _compute_smart_discharge_allow_set(self, future_high, current_soc_wh, min_soc_wh):
        """
        Return a set of discharge-blocks that are allowed to actually
        discharge, prioritising the most expensive ones. Returns None
        if smart-discharge is disabled or doesn't apply (battery has
        enough headroom for the full phase).

        Algorithm:
          1. If feature flag off -> None (legacy behaviour: every
             discharge block is allowed if surplus permits).
          2. Compute total energy needed to cover the full upcoming
             expensive phase (future_high) at avg consumption.
          3. If usable_soc >= total_required, the battery can cover
             the whole phase -> allow all blocks (return None).
          4. Otherwise, sort blocks by price descending and accumulate
             expected consumption for each block until usable_soc is
             exhausted. Return the set of blocks above the cut.

        Returned: a set of block objects, or None.
        """
        if not getattr(self.config, "smart_discharge_priority_to_expensive_hours", False):
            return None
        if not future_high:
            return None

        usable_soc_wh = max(0.0, (current_soc_wh or 0) - (min_soc_wh or 0))
        if usable_soc_wh <= 0:
            # Nothing to allocate -- no discharge possible at all.
            # Returning empty set means "no blocks allowed".
            return set()

        avg_list = self.statsmanager.get_data(
            "powerconsumption", "hourly_watt_average"
        )
        avg_per_hour = round(avg_list[0], 2) if avg_list else 0
        if avg_per_hour <= 0:
            # No consumption history -- can't make a meaningful split,
            # default to legacy behaviour.
            return None

        # Compute per-block remaining-duration energy needs.
        # Use REMAINING duration for active blocks (block already partly
        # used), full duration for future ones.
        from datetime import datetime, timezone, timedelta
        now_utc = datetime.now(timezone.utc)

        block_costs = []  # list of (block, energy_wh, avg_price)
        for blk in future_high:
            blk_end = blk.get_end_datetime() if hasattr(blk, "get_end_datetime") else None
            if blk_end is None:
                blk_start = blk.get_start_datetime()
                if blk_start is None:
                    continue
                if blk_start.tzinfo is None:
                    blk_start = blk_start.replace(tzinfo=timezone.utc)
                blk_end = blk_start + timedelta(minutes=blk.get_duration_minutes() or 0)
            if blk_end.tzinfo is None:
                blk_end = blk_end.replace(tzinfo=timezone.utc)
            remaining_h = max(0.0, (blk_end - now_utc).total_seconds() / 3600)
            energy_wh = remaining_h * avg_per_hour
            try:
                price = blk.get_avg_price(convert=False)
            except (TypeError, ValueError):
                price = 0
            block_costs.append((blk, energy_wh, price))

        if not block_costs:
            return None

        # Total needed to cover full phase at avg consumption.
        total_required = sum(e for _, e, _ in block_costs) * 1.10

        if usable_soc_wh >= total_required:
            # Comfortable -- allow all blocks (legacy behaviour).
            return None

        # Tight -- prioritise the most expensive blocks.
        # Sort descending by price.
        block_costs.sort(key=lambda t: t[2], reverse=True)
        allow = set()
        budget_wh = usable_soc_wh
        for blk, energy_wh, _price in block_costs:
            # Accept the block if at least its first slice fits. We
            # don't partial-allow blocks (the discharge gate is binary
            # per block); any block we accept consumes its full
            # expected energy from the budget.
            if energy_wh <= budget_wh:
                allow.add(blk)
                budget_wh -= energy_wh
            else:
                # Doesn't fully fit -- skip it. The remaining budget
                # may still fit a cheaper-but-shorter later block.
                continue

        self.logger.log.info(
            f"Smart-discharge: usable_soc={usable_soc_wh:.0f}Wh, "
            f"phase_required={total_required:.0f}Wh -> "
            f"allowing {len(allow)}/{len(block_costs)} discharge blocks "
            f"(highest-price first)."
        )
        return allow

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

        # Always-on safety abort: don't try to charge past the SOC
        # target the user has set in the Victron Scheduler. Without
        # this, SEUSS happily reports "charging is turned on" while
        # the battery is already at 100% and the inverter has nothing
        # left to charge -- the symptom that triggered this fix. The
        # check uses the live scheduler-SOC value from D-Bus so a
        # change in the Victron UI takes effect immediately on the
        # next evaluation cycle.
        self.abort_conditions_by_operation_mode["charging_abort"].update({
            "Abort charge - SOC target reached":
                self._abort_charging_soc_target_reached
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
                "until next equally-cheap charge cluster (DEPRECATED: "
                "use skip_charge_when_battery_covers_expensive_phase)":
                    self._abort_charging_battery_reaches_next_cluster
            })

        # Deprecated -- redundant with the regular battery_reaches abort.
        # Kept registered so users with the flag set don't see a silent
        # change in behaviour, but the underlying method is documented
        # as deprecated and will be removed in a future release.
        if getattr(self.config, "skip_charge_when_battery_covers_overnext", False):
            self.abort_conditions_by_operation_mode["charging_abort"].update({
                "Abort charge - battery covers consumption "
                "until OVERNEXT equally-cheap charge cluster (DEPRECATED: "
                "use skip_charge_when_battery_covers_expensive_phase)":
                    self._abort_charging_battery_covers_until_overnext_cluster
            })

        # Cheaper-cluster-coming: even while inside a cheap cluster
        # (i.e. SEUSS would normally charge), skip if a strictly
        # cheaper cluster is due later AND a forward simulation of
        # the pack's SOC across the full remaining shelter chain
        # never goes negative. Prevents "charging at 23 ct when 19 ct
        # will come in 2 hours" while still being safe if the horizon
        # gets tight.
        #
        # Registered BEFORE covers_expensive_phase on purpose: the
        # abort loop stops at the first True, and this check is the
        # more specific one -- when both would fire, the user should
        # see "cheaper cluster coming" (with the price it's waiting
        # for) in the log, not the generic expensive-phase message.
        if getattr(self.config, "skip_charge_when_cheaper_cluster_coming", False):
            self.abort_conditions_by_operation_mode["charging_abort"].update({
                "Abort charge - strictly cheaper cluster coming and "
                "battery bridges the gap safely":
                    self._abort_charging_cheaper_cluster_coming
            })

        # Current preferred check: abort if the battery covers the entire
        # upcoming expensive phase by itself (until the next charge cluster
        # of any price). Broader and more correct horizon than the older
        # checks above. Conservative: doesn't model recharge from the
        # next cluster, only counts what's in the pack right now.
        if getattr(self.config, "skip_charge_when_battery_covers_expensive_phase", False):
            self.abort_conditions_by_operation_mode["charging_abort"].update({
                "Abort charge - battery covers entire expensive phase "
                "until next charge cluster":
                    self._abort_charging_battery_covers_expensive_phase
            })

        # Negative-price-ahead optimisation: when the upcoming spot
        # market has at least one quarter priced below zero, prefer
        # to keep battery headroom open for that "free" energy rather
        # than burning it on a current cheap-but-positive quarter.
        # The check internally decides whether the SOC + expected
        # consumption till then will be enough -- so a small negative
        # window with a near-full battery will skip cheap charging,
        # but a long negative window will still allow current charging
        # because the battery couldn't absorb all of it anyway.
        if getattr(self.config, "skip_charge_for_upcoming_negative_prices", False):
            self.abort_conditions_by_operation_mode["charging_abort"].update({
                "Abort charge - negative-price quarters ahead "
                "and battery will have room":
                    self._abort_charging_negative_price_ahead
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

    def _abort_charging_soc_target_reached(self):
        """
        True if the battery has already reached (or exceeded) the SOC
        target configured in the Victron Scheduler. Always-on safety:
        there's no scenario where charging past this target is useful,
        and without the check SEUSS keeps reporting "charging on" while
        the inverter has nothing to do.

        Reads the live values:
          * current_soc           -- via essunit.get_soc()
          * scheduler_soc target  -- via essunit.get_scheduler_soc()

        Falls back to "don't abort" on any read failure, so a transient
        D-Bus glitch can't lock charging out entirely.

        Includes a 1% tolerance so the abort doesn't oscillate around
        the threshold due to SOC measurement noise (e.g. 99.6 vs 100.1
        flapping at the boundary).
        """
        try:
            if not self.essunit:
                return False
            current_soc = self.essunit.get_soc()
            scheduler_soc = self.essunit.get_scheduler_soc()
            if current_soc is None or scheduler_soc is None:
                return False

            # 1% tolerance: trip the abort once we're within 1 of the
            # target, not only AT or above it. Avoids stop/start churn
            # when the BMS hovers just below 100%.
            should_abort = float(current_soc) >= (float(scheduler_soc) - 1.0)
            if should_abort:
                self.logger.log.info(
                    f"SOC-target abort: current_soc={current_soc}% "
                    f">= scheduler_soc_target={scheduler_soc}% "
                    f"(with 1% tolerance), charging is unnecessary."
                )
                self._record_abort_fired("soc_target")
            return should_abort
        except Exception as e:
            self.logger.log.warning(
                f"SOC-target abort check failed: {e}. "
                "Keeping charging allowed."
            )
            return False

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
            forecast_today = sd.forecast_today_wh or 0.0
            forecast_tomorrow = sd.forecast_tomorrow_wh or 0.0
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

            result = condition_a and condition_b
            if result:
                # Log the same numbers at INFO so the user sees WHY
                # the skip fired without having to flip the log level.
                self.logger.log.info(
                    f"Solar-abort details: "
                    f"forecast={total_forecast_wh:.0f}Wh, "
                    f"2-day-consumption={two_day_consumption_wh:.0f}Wh, "
                    f"usable_soc={usable_soc_wh:.0f}Wh, "
                    f"required_until_solar={required_until_solar_wh:.0f}Wh "
                    f"(over {hours_until_solar:.1f}h)."
                )
                self._record_abort_fired("solar_forecast")
            return result

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
        DEPRECATED -- replaced by
        `_abort_charging_battery_covers_expensive_phase` which uses a
        broader, more correct horizon (until the next charge cluster
        of any price). This older check only looks for the next
        equally-cheap-or-cheaper block, which can leave the system
        short if a cheaper cluster comes too late.

        Kept for now so existing setups with
        `skip_charge_when_battery_sufficient = true` continue to work.
        Migrate to `skip_charge_when_battery_covers_expensive_phase`
        when convenient.

        ----- original docstring follows -----

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
            if should_skip:
                # Same numbers at INFO so the user sees WHY the skip
                # fired without flipping log level to DEBUG.
                self.logger.log.info(
                    f"Battery-range abort details: target_block "
                    f"{target_block.describe(localtime=True)} "
                    f"(starts in {hours_until:.1f}h), "
                    f"required={required_wh:.0f}Wh, "
                    f"usable_soc={usable_soc_wh:.0f}Wh."
                )
                self._record_abort_fired("battery_range")
            return should_skip

        except Exception as e:
            self.logger.log.error(
                f"Battery-range abort check failed: {e}. "
                "Keeping charging allowed."
            )
            return False

    def _abort_charging_battery_covers_expensive_phase(self):
        """
        Skip the current charge attempt if the battery's currently-usable
        SOC alone covers consumption all the way through the upcoming
        expensive phase, until the next charge cluster (the next time
        SEUSS would actively charge).

        "Expensive phase" =
            from now until the start of the next cheap charge cluster
            (regardless of price -- it's the next moment SEUSS would
            actively charge, which ends the phase by definition).

        This is broader than `_abort_charging_battery_reaches_next_cluster`
        which only looked for the next equally-cheap-or-cheaper block.
        Here we look at the actual horizon: we don't care if the next
        charge cluster is cheaper; we just care that there IS one
        coming, because that's when we'd be re-charging anyway.

        Conservative on purpose: doesn't model how much the next
        charge cluster will recharge. Only counts what's already in
        the pack. So a True here is genuinely safe -- if the user has
        enough headroom right now to bridge the entire expensive phase
        AND maintain min_soc, charging now is unnecessary.

        Returns False (= don't skip) on missing data.
        """
        try:
            if not self._charge_blocks:
                return False

            # Find the next charge cluster after now -- any price is
            # fine, because the question is "when do we next get to
            # actively charge again?" not "is it cheaper than now?".
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)

            # Read the current quarter's price so we can filter out
            # "fake" charge clusters -- ones that are cheaper than the
            # rest of the expensive phase but NOT cheaper than the
            # current quarter. Waiting for a "shelter" that isn't
            # actually cheaper than right now is worse than charging
            # right now, since it also uses up the battery in between.
            cur_price_mc = None
            try:
                cur_price_mc = self.items.get_current_price(convert=False)
                if cur_price_mc is not None:
                    cur_price_mc = int(cur_price_mc)
            except (TypeError, ValueError):
                cur_price_mc = None

            future_charge_blocks = []
            for blk in self._charge_blocks:
                if blk.is_expired():
                    continue
                blk_start = blk.get_start_datetime()
                if blk_start is None:
                    continue
                if blk_start.tzinfo is None:
                    blk_start = blk_start.replace(tzinfo=timezone.utc)
                if blk_start <= now_utc:
                    # Active or already-started cluster -- treat as now.
                    continue
                future_charge_blocks.append((blk_start, blk))

            if not future_charge_blocks:
                # No future charge cluster known -- can't define the
                # phase end. Don't skip; let the normal evaluation
                # handle the current cycle.
                return False

            future_charge_blocks.sort(key=lambda x: x[0])
            future_charge_starts = [s for s, _ in future_charge_blocks]

            # ------------------------------------------------------------
            # Filter "fake shelters" out of the list of future clusters
            # ------------------------------------------------------------
            # A "fake shelter" is a future charge cluster that:
            #   (a) is priced HIGHER than the current quarter, OR
            #   (b) is a short (1h) island surrounded by expensive
            #       quarters on BOTH sides -- i.e. it doesn't mark the
            #       real end of the expensive phase.
            #
            # Without this filter, SEUSS would skip charging right now
            # (28.93 ct) because a single 1h cluster later (e.g. 29.23 ct
            # at 18:00) is technically classified as a "charge cluster"
            # by the top-N-cheap-quarters logic. But that cluster is
            # neither cheaper than now nor a real safe harbour: 14 more
            # expensive hours follow it. If we wait, we waste battery
            # and end up paying MORE for the top-up.
            #
            # A cluster is only a valid shelter if it's cheaper than
            # now AND either (i) contiguous with a run of cluster hours
            # that adds up to enough headroom, or (ii) followed by a
            # sustained cheap window. We approximate "(i) or (ii)" with:
            # the cluster's own duration + the gap until the NEXT
            # cluster (or price-list end) has to represent a >=1.5h
            # cheap window.
            filtered_blocks = []
            for i, (start_i, blk_i) in enumerate(future_charge_blocks):
                try:
                    blk_price = int(blk_i.get_avg_price(convert=False))
                except (TypeError, ValueError):
                    # Can't judge price -- keep to be safe (matches old
                    # behaviour before this filter existed).
                    filtered_blocks.append((start_i, blk_i))
                    continue

                # Filter (a): must be cheaper than current quarter.
                if cur_price_mc is not None and blk_price >= cur_price_mc:
                    continue

                # Filter (b): must not be a lone 1h island. Check gap
                # BACK to previous kept cluster and FORWARD to next
                # future cluster.
                blk_end = blk_i.get_end_datetime()
                if blk_end is not None and blk_end.tzinfo is None:
                    blk_end = blk_end.replace(tzinfo=timezone.utc)
                blk_dur_h = 0.0
                if blk_end is not None:
                    blk_dur_h = max(
                        0.0, (blk_end - start_i).total_seconds() / 3600
                    )

                # Distance to next future cluster. If none, we treat
                # it as "far enough" -- last cluster in the list is
                # implicitly a shelter.
                gap_forward_h = None
                if i + 1 < len(future_charge_blocks):
                    next_start = future_charge_blocks[i + 1][0]
                    gap_forward_h = max(
                        0.0, (next_start - blk_end).total_seconds() / 3600
                    ) if blk_end is not None else 0.0

                # A short (<=1h) cluster followed within 1.5h by another
                # cluster is an island: not a real end of the expensive
                # phase. Skip it.
                if (
                    blk_dur_h <= 1.0
                    and gap_forward_h is not None
                    and gap_forward_h < 1.5
                ):
                    continue

                filtered_blocks.append((start_i, blk_i))

            if not filtered_blocks:
                # No valid shelter in sight -- the entire remaining
                # horizon is expensive relative to right now. We can't
                # skip; charge now.
                self.logger.log.debug(
                    "Expensive-phase abort: no valid cheaper shelter "
                    "found in future clusters (all higher than current "
                    "price or fake 1h islands). Allowing charge."
                )
                return False

            # Replace future_charge_starts with the filtered set so the
            # subsequent gap-based phase_end selection walks only real
            # shelters.
            future_charge_starts = [s for s, _ in filtered_blocks]

            # Find the next REAL expensive phase. The naive
            # `min(future_charge_starts)` would be the next cluster --
            # but if cheap hours run consecutively (e.g. 11, 12, 13, 14
            # are all charge clusters), the gap between them is only
            # one hour and the bridge would always evaluate as
            # "0.2h until next cluster, easy to bridge", causing the
            # battery to never fill up during the long cheap window
            # in preparation for an actual long expensive evening.
            #
            # Walk the sorted list of future cluster starts and find
            # the FIRST cluster that has a >= 1h gap to the previous
            # one. That cluster is the start of the post-expensive
            # cheap window; the expensive phase ends right there.
            future_charge_starts.sort()
            phase_end = future_charge_starts[0]
            cluster_block_h = 1.0  # blocks are 60 min
            gap_threshold_h = 1.5  # >1h gap = expensive phase between
            for i, start in enumerate(future_charge_starts):
                if i == 0:
                    continue
                prev = future_charge_starts[i - 1]
                gap_h = (start - prev).total_seconds() / 3600.0
                if gap_h >= gap_threshold_h:
                    phase_end = start
                    break
            else:
                # All future clusters are contiguous -- the expensive
                # phase only starts AFTER the last one. So the phase
                # ends with the last known cluster's end + 1h-block.
                # This is the conservative choice: we plan for the
                # expensive phase to be at least one hour long.
                phase_end = future_charge_starts[-1]

            total_hours = max(
                0.0, (phase_end - now_utc).total_seconds() / 3600
            )
            if total_hours <= 0:
                return False

            # Required reserve = avg consumption × hours × 1.10 buffer.
            avg_list = self.statsmanager.get_data(
                "powerconsumption", "hourly_watt_average"
            )
            avg_consumption_per_hour = (
                round(avg_list[0], 2) if avg_list else 0
            )
            if avg_consumption_per_hour <= 0:
                return False
            required_wh = total_hours * avg_consumption_per_hour * 1.10

            # Current usable SOC = full × (current - min) %.
            current_soc_wh = (
                self.essunit.get_battery_current_wh()
                if self.essunit else 0
            ) or 0
            min_soc_wh = (
                self.essunit.get_battery_min_wh()
                if self.essunit else 0
            ) or 0
            usable_soc_wh = max(0.0, current_soc_wh - min_soc_wh)

            should_skip = usable_soc_wh >= required_wh

            # Layer 2: forward-simulate the shelter chain to verify
            # that even IF we skip charging now, subsequent shelters
            # will refill enough to bridge the remaining expensive
            # phases without emptying the pack. See
            # _simulate_shelter_chain for the reasoning; if it returns
            # False, override the layer-1 skip decision.
            if should_skip and filtered_blocks:
                chain_ok, trace = self._simulate_shelter_chain(
                    filtered_blocks, usable_soc_wh, current_soc_wh,
                    min_soc_wh, avg_consumption_per_hour, now_utc,
                )
                if chain_ok is False:
                    self.logger.log.info(
                        f"Expensive-phase abort: layer-1 said OK but "
                        f"shelter-chain simulation says SOC would go "
                        f"negative. Charging anyway. Trace: {trace}"
                    )
                    should_skip = False

            self.logger.log.debug(
                f"Expensive-phase abort: phase_end={phase_end.isoformat()}, "
                f"total_hours={total_hours:.1f}h, "
                f"required={required_wh:.0f}Wh, "
                f"usable_soc={usable_soc_wh:.0f}Wh, "
                f"skip={should_skip}"
            )
            if should_skip:
                self.logger.log.info(
                    f"Expensive-phase abort details: "
                    f"phase ends at next charge cluster "
                    f"{phase_end.astimezone().strftime('%Y-%m-%d %H:%M')} "
                    f"({total_hours:.1f}h from now), "
                    f"required={required_wh:.0f}Wh, "
                    f"usable_soc={usable_soc_wh:.0f}Wh."
                )
                self._record_abort_fired("battery_expensive_phase")
            return should_skip

        except Exception as e:
            self.logger.log.error(
                f"Expensive-phase abort check failed: {e}. "
                "Keeping charging allowed."
            )
            return False

    def _get_estimated_grid_charge_w(self):
        """
        Estimated grid-charging power (W) taken from live/persisted
        measurements. The value is written by PowerConsumption whenever
        both battery_power AND grid_power are simultaneously positive
        (= grid is feeding the pack). Returns 0 if no measurement has
        ever been recorded -- in that case Layer-2 simulation is
        skipped and we fall back to the Layer-1 answer.
        """
        try:
            val = self.statsmanager.get_data(
                "powerconsumption", "last_grid_charge_power_w"
            )
            if isinstance(val, (int, float)) and val > 0:
                return float(val)
        except Exception:
            pass
        return 0.0

    def _current_soc_pct_safe(self):
        """Best-effort SOC percentage read; returns 50.0 if unavailable
        (a neutral midpoint so `full_wh` fallback math stays sane)."""
        try:
            if self.essunit:
                s = self.essunit.get_soc()
                if isinstance(s, (int, float)) and 0 <= s <= 100:
                    return float(s)
        except Exception:
            pass
        return 50.0

    def _simulate_shelter_chain(
        self, filtered_blocks, usable_soc_wh, current_soc_wh,
        min_soc_wh, avg_consumption_per_hour, now_utc,
    ):
        """
        Forward-simulate the pack's SOC across the remaining chain of
        real shelter clusters. Between each pair, drain at the
        recent-average hourly consumption. At each shelter, top up by
        (cluster_duration_h × estimated_grid_charge_w), capped at the
        pack's usable ceiling.

        If the simulated SOC ever crosses zero, layer-1's optimistic
        "we can bridge until phase_end" is wrong on the wider horizon
        and skipping charging right now would leave the pack empty
        during a later expensive stretch.

        Returns (chain_ok: bool | None, trace: str). `None` means the
        simulation could not run (missing data); the caller should
        keep the layer-1 answer in that case.
        """
        from datetime import timezone

        grid_charge_w = self._get_estimated_grid_charge_w()
        if grid_charge_w <= 0:
            return (None, "no grid_charge_w measurement yet")

        # Pack usable ceiling: try full_wh from essunit; else derive
        # roughly from current SOC.
        full_wh = None
        try:
            if self.essunit and hasattr(self.essunit, "get_battery_full_wh"):
                full_wh = self.essunit.get_battery_full_wh()
        except Exception:
            full_wh = None
        if not full_wh or full_wh <= 0:
            soc_pct = self._current_soc_pct_safe()
            if soc_pct > 1:
                full_wh = current_soc_wh / (soc_pct / 100.0)
            else:
                full_wh = current_soc_wh
        full_wh = max(full_wh, current_soc_wh)
        usable_ceiling = max(0.0, full_wh - min_soc_wh)

        sim_soc = usable_soc_wh
        prev_time = now_utc
        trace_parts = []
        for start_i, blk_i in filtered_blocks:
            drain_h = max(
                0.0, (start_i - prev_time).total_seconds() / 3600
            )
            sim_soc -= drain_h * avg_consumption_per_hour
            if sim_soc < 0:
                trace_parts.append(
                    f"drained {drain_h:.1f}h to "
                    f"{start_i.astimezone().strftime('%H:%M')} "
                    f"-> SOC {sim_soc:.0f}Wh (negative)"
                )
                return (False, "; ".join(trace_parts))
            blk_end = blk_i.get_end_datetime()
            if blk_end is not None and blk_end.tzinfo is None:
                blk_end = blk_end.replace(tzinfo=timezone.utc)
            cluster_dur_h = (
                (blk_end - start_i).total_seconds() / 3600
                if blk_end is not None else 1.0
            )
            add_wh = cluster_dur_h * grid_charge_w
            sim_soc = min(usable_ceiling, sim_soc + add_wh)
            trace_parts.append(
                f"drain {drain_h:.1f}h, then charge {cluster_dur_h:.1f}h "
                f"@ {grid_charge_w:.0f}W = +{add_wh:.0f}Wh, "
                f"SOC={sim_soc:.0f}Wh"
            )
            prev_time = blk_end or start_i

        # Post-last-shelter drain until end of price horizon.
        try:
            item_list = getattr(self.items, "_item_list", [])
            if item_list:
                horizon_end = item_list[-1].get_end_datetime()
                if horizon_end is not None and horizon_end.tzinfo is None:
                    horizon_end = horizon_end.replace(tzinfo=timezone.utc)
                if horizon_end and horizon_end > prev_time:
                    drain_h = (horizon_end - prev_time).total_seconds() / 3600
                    sim_soc -= drain_h * avg_consumption_per_hour
                    trace_parts.append(
                        f"post-shelter drain {drain_h:.1f}h -> "
                        f"SOC {sim_soc:.0f}Wh"
                    )
                    if sim_soc < 0:
                        return (False, "; ".join(trace_parts))
        except Exception:
            pass

        return (True, "; ".join(trace_parts))

    def _abort_charging_battery_covers_until_overnext_cluster(self):
        """
        DEPRECATED -- kept temporarily for backward compatibility.

        This abort is logically redundant with
        `_abort_charging_battery_reaches_next_cluster` (if the SOC
        doesn't reach the next cheap cluster, it can't reach the
        OVERNEXT one either). It will be removed in a future revision.
        Use `skip_charge_when_battery_covers_expensive_phase` instead,
        which addresses the actual look-ahead intent: "battery covers
        the entire expensive phase until SEUSS next charges".
        """
        try:
            # 1) Need a pre-computed list of charge clusters.
            if not self._charge_blocks:
                return False

            # 2) Find the next cheaper-or-equal cluster (same logic as
            #    the existing battery-range abort).
            next_cluster = self._find_next_cheaper_or_equal_charge_block()
            if next_cluster is None:
                return False

            # 3) Find the OVERNEXT cheaper-or-equal cluster -- the
            #    first one whose start is after `next_cluster`'s end.
            from datetime import datetime, timezone, timedelta
            now_utc = datetime.now(timezone.utc)

            next_end = next_cluster.get_end_datetime() if hasattr(
                next_cluster, "get_end_datetime") else None
            if next_end is None:
                return False
            if next_end.tzinfo is None:
                next_end = next_end.replace(tzinfo=timezone.utc)

            # Reference price = active block's avg if we'd be charging
            # right now, else current quarter's price. Same definition
            # as in _find_next_cheaper_or_equal_charge_block.
            active_block = next(
                (blk for blk in self._charge_blocks if blk.is_active_now()),
                None,
            )
            if active_block is not None:
                reference_price = active_block.get_avg_price(convert=False)
            else:
                cur = self.items.get_current_price(convert=False)
                if cur is None:
                    return False
                try:
                    reference_price = int(cur)
                except (TypeError, ValueError):
                    return False

            overnext = None
            for blk in sorted(
                self._charge_blocks,
                key=lambda b: b.get_start_datetime() or now_utc,
            ):
                if blk is active_block or blk is next_cluster:
                    continue
                if blk.is_expired():
                    continue
                blk_start = blk.get_start_datetime()
                if blk_start is None:
                    continue
                if blk_start.tzinfo is None:
                    blk_start = blk_start.replace(tzinfo=timezone.utc)
                if blk_start < next_end:
                    continue
                try:
                    if blk.get_avg_price(convert=False) <= reference_price:
                        overnext = blk
                        break
                except (TypeError, ValueError):
                    continue

            if overnext is None:
                # No defined end of expensive phase -- can't make a
                # confident skip decision.
                return False

            overnext_start = overnext.get_start_datetime()
            if overnext_start is None:
                return False
            if overnext_start.tzinfo is None:
                overnext_start = overnext_start.replace(tzinfo=timezone.utc)

            # 4) Total hours we need to cover from now until the
            #    overnext cluster STARTS (after that we'd charge again).
            total_hours = max(
                0.0, (overnext_start - now_utc).total_seconds() / 3600
            )
            if total_hours <= 0:
                return False

            # 5) Required energy = avg consumption * hours * 1.10 buffer.
            avg_list = self.statsmanager.get_data(
                "powerconsumption", "hourly_watt_average"
            )
            avg_consumption_per_hour = (
                round(avg_list[0], 2) if avg_list else 0
            )
            required_wh = total_hours * avg_consumption_per_hour * 1.10

            # 6) Current usable SOC = full_wh * (current_soc - min_soc).
            current_soc = self.essunit.get_soc() or 0
            min_soc = self.essunit.get_battery_minimum_soc_limit() or 0
            full_wh = self.essunit.get_battery_full_wh() or 0
            current_soc_wh = (current_soc / 100.0) * full_wh
            min_soc_wh = (min_soc / 100.0) * full_wh
            usable_soc_wh = max(0.0, current_soc_wh - min_soc_wh)

            should_skip = usable_soc_wh >= required_wh

            self.logger.log.debug(
                f"Overnext-cluster abort: next={next_cluster.describe(localtime=True)}, "
                f"overnext={overnext.describe(localtime=True)}, "
                f"total_hours={total_hours:.1f}h, "
                f"required={required_wh:.0f}Wh, "
                f"usable_soc={usable_soc_wh:.0f}Wh, "
                f"skip={should_skip}"
            )
            if should_skip:
                self.logger.log.info(
                    f"Overnext-cluster abort details: "
                    f"horizon to overnext cluster = "
                    f"{overnext.describe(localtime=True)} "
                    f"({total_hours:.1f}h from now), "
                    f"required={required_wh:.0f}Wh, "
                    f"usable_soc={usable_soc_wh:.0f}Wh."
                )
                self._record_abort_fired("battery_overnext")
            return should_skip

        except Exception as e:
            self.logger.log.error(
                f"Overnext-cluster abort check failed: {e}. "
                "Keeping charging allowed."
            )
            return False

    def _abort_charging_negative_price_ahead(self):
        """
        Skip the current charge attempt when there is at least one future
        quarter (today or tomorrow) priced below zero AND the battery
        will have enough headroom to absorb that future cheap-as-free
        energy without needing the current quarter's charge.

        Logic:
          1. Find all future quarters in the price list whose price is
             strictly negative (< 0 ct/kWh). If none, do nothing.
          2. NEVER skip when the current quarter is itself negative --
             we must charge as much as possible while we're being paid
             for it.
          3. Compute how many Wh the battery still has room to absorb:
                headroom_wh = full_wh - current_soc_wh
          4. Compute how many Wh we could plausibly push in during the
             negative quarters (sum of quarter durations × max charge
             rate from config). This is the "free slot we want to keep
             empty for".
          5. Compute how many Wh we expect to consume between now and
             the first negative quarter (avg consumption × hours_until).
             That's energy the battery will release naturally.
          6. Skip when:
                headroom_wh + expected_consumption_wh >= absorbable_negative_wh
             ie. by the time the negative quarters arrive, we'll have at
             least that many empty Wh to fill -- so spending money on
             *positive*-price charging right now would be wasted.

        Returns False on any error so charging stays allowed when in doubt.
        """
        try:
            from datetime import datetime, timezone

            # Step 1+2: scan future items.
            cur_price = self.items.get_current_price(convert=False)
            if cur_price is not None:
                try:
                    if int(cur_price) < 0:
                        # Currently paid to charge -- don't skip.
                        return False
                except (TypeError, ValueError):
                    pass

            now_utc = datetime.now(timezone.utc)
            negative_items = []
            first_negative_start = None
            for it in getattr(self.items, "_item_list", []):
                start = it.get_start_datetime()
                if start is None:
                    continue
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if start <= now_utc:
                    continue
                try:
                    if int(it.get_price(False)) < 0:
                        negative_items.append(it)
                        if first_negative_start is None or start < first_negative_start:
                            first_negative_start = start
                except (TypeError, ValueError):
                    continue

            if not negative_items:
                return False  # nothing to optimise for

            # Step 3: battery headroom right now.
            full_wh = (self.essunit.get_battery_full_wh() if self.essunit else 0) or 0
            current_soc = (self.essunit.get_soc() if self.essunit else 0) or 0
            current_soc_wh = (current_soc / 100.0) * full_wh
            headroom_wh = max(0.0, full_wh - current_soc_wh)

            # Step 4: how much energy the negative quarters could absorb.
            # Items are 15min long (quarter-resolution) regardless of
            # tariff_resolution. Use charge_rate from config; fall back
            # to a sensible default if the user hasn't pinned one.
            charge_rate_w = float(getattr(self.config, "charge_rate", 0) or 0)
            if charge_rate_w <= 0:
                # Best-effort fallback: ESS max DC charging current
                # (Settings/CGwacs/MaxChargePower) isn't always available
                # via essunit; assume a conservative 3 kW so we still
                # gate on something reasonable. The user should set
                # charge_rate in the config for accurate results.
                charge_rate_w = 3000.0
            quarter_duration_h = 0.25
            absorbable_negative_wh = (
                len(negative_items) * charge_rate_w * quarter_duration_h
            )

            # Step 5: expected consumption between now and the first
            # negative quarter -- this empties the battery on its own.
            hours_until_first_neg = max(
                (first_negative_start - now_utc).total_seconds() / 3600.0, 0.0
            )
            avg_list = self.statsmanager.get_data(
                "powerconsumption", "hourly_watt_average"
            )
            avg_hourly_wh = (
                round(avg_list[0], 2)
                if isinstance(avg_list, (list, tuple)) and avg_list
                else 0.0
            )
            expected_consumption_wh = avg_hourly_wh * hours_until_first_neg

            # Step 6: skip iff the battery will have room for the
            # negative-price energy by the time it arrives.
            should_skip = (
                headroom_wh + expected_consumption_wh >= absorbable_negative_wh
            )

            self.logger.log.debug(
                f"Negative-price-ahead abort: {len(negative_items)} negative quarter(s) "
                f"starting {first_negative_start.isoformat()}, "
                f"absorbable={absorbable_negative_wh:.0f}Wh, "
                f"headroom_now={headroom_wh:.0f}Wh, "
                f"hours_until={hours_until_first_neg:.1f}h, "
                f"expected_consumption={expected_consumption_wh:.0f}Wh, "
                f"skip={should_skip}"
            )
            if should_skip:
                self.logger.log.info(
                    f"Negative-price-ahead abort details: "
                    f"{len(negative_items)} negative quarter(s) ahead "
                    f"({absorbable_negative_wh:.0f}Wh absorbable), "
                    f"battery has {headroom_wh:.0f}Wh free now and will "
                    f"free another ~{expected_consumption_wh:.0f}Wh by "
                    f"consuming until they start in {hours_until_first_neg:.1f}h."
                )
                self._record_abort_fired("negative_price_ahead")
            return should_skip

        except Exception as e:
            self.logger.log.error(
                f"Negative-price-ahead abort check failed: {e}. "
                "Keeping charging allowed."
            )
            return False

    def _pv_forecast_wh_between(self, t0_utc, t1_utc):
        """
        Sum of forecast PV Wh inside [t0_utc, t1_utc).

        Uses today's per-hour forecast array
        (solar.forecast_hourly_wh_by_day[today], adjusted values as
        captured by the solar provider). For days without an hourly
        array (tomorrow), falls back to spreading the day total
        (solar.forecast_tomorrow_wh) evenly across 08:00-18:00 local
        -- crude, but far better than assuming zero sun when the
        chain simulation reaches into tomorrow.

        Returns 0.0 on any missing data so the simulation stays
        conservative.
        """
        try:
            from datetime import datetime, timedelta
            import pytz
            tz = pytz.timezone(self.config.time_zone)

            hourly_by_day = self.statsmanager.get_data(
                "solar", "forecast_hourly_wh_by_day"
            ) or {}
            if not isinstance(hourly_by_day, dict):
                hourly_by_day = {}
            tomorrow_total = self.statsmanager.get_data(
                "solar", "forecast_tomorrow_wh"
            ) or 0
            now_local = datetime.now(tz)
            tomorrow_iso = (now_local + timedelta(days=1)).strftime('%Y-%m-%d')

            total = 0.0
            t = t0_utc
            while t < t1_utc:
                hour_start = t.replace(minute=0, second=0, microsecond=0)
                hour_end = hour_start + timedelta(hours=1)
                seg_start = max(t0_utc, hour_start)
                seg_end = min(t1_utc, hour_end)
                frac = max(
                    0.0, (seg_end - seg_start).total_seconds() / 3600
                )

                t_local = seg_start.astimezone(tz)
                day_iso = t_local.strftime('%Y-%m-%d')
                hour = t_local.hour

                wh_hour = 0.0
                arr = hourly_by_day.get(day_iso)
                if isinstance(arr, list) and len(arr) == 24:
                    try:
                        wh_hour = float(arr[hour] or 0)
                    except (TypeError, ValueError):
                        wh_hour = 0.0
                elif day_iso == tomorrow_iso and tomorrow_total and 8 <= hour < 18:
                    try:
                        wh_hour = float(tomorrow_total) / 10.0
                    except (TypeError, ValueError):
                        wh_hour = 0.0

                total += wh_hour * frac
                t = hour_end
            return total
        except Exception:
            return 0.0

    def _abort_charging_cheaper_cluster_coming(self):
        """
        Skip the current charge attempt when a strictly cheaper future
        charge cluster exists AND a forward simulation of the pack's
        SOC across the remaining shelter chain never goes negative.

        Rationale: SEUSS is right now inside a cheap cluster (e.g.
        23 ct) so its normal condition would say "charging on". But
        the price list shows a materially cheaper cluster ahead
        (e.g. 19 ct in 2h). If the pack has enough energy AND PV is
        actively topping it up AND that cheaper cluster can then
        cover the following expensive phase, there's no reason to
        pay the extra ct/kWh right now.

        Decision:
          1. `charging_price_limit` safety floor wins -- never skip
             when the current price is already at or below the
             always-on floor the user configured.
          2. Find the earliest future charge block whose average
             price is STRICTLY lower than the reference price we'd
             be paying if we charged this cycle.
          3. If none exists -> current attempt is already the
             cheapest; don't skip.
          4. Forward-simulate SOC through every subsequent charge
             cluster (drain between them at
             hourly_watt_average, top up during them at
             `last_grid_charge_power_w` capped by pack full).
          5. If the simulation ever crosses zero -> skipping is
             unsafe, don't skip. Otherwise -> skip.

        Returns False on any missing data (SOC, avg consumption,
        grid-charge power) -- when in doubt, keep charging allowed
        (matches the pattern of the other abort checks).
        """
        try:
            # ------------------------------------------------------------
            # 1) charging_price_limit safety floor
            # ------------------------------------------------------------
            cur = self.items.get_current_price(convert=False)
            if cur is not None:
                try:
                    if int(cur) <= self.charging_price_limit:
                        self.logger.log.info(
                            "Cheaper-cluster-coming abort: current price at "
                            "or below charging_price_limit -- not skipping."
                        )
                        return False
                except (TypeError, ValueError):
                    pass

            # ------------------------------------------------------------
            # 2) find the next STRICTLY-cheaper future charge block
            # ------------------------------------------------------------
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)

            # Reference price = active block's avg, or current-quarter.
            active_block = None
            for blk in self._charge_blocks:
                if blk.is_active_now():
                    active_block = blk
                    break
            if active_block is not None:
                try:
                    reference_price = int(active_block.get_avg_price(convert=False))
                except (TypeError, ValueError):
                    return False
            else:
                if cur is None:
                    return False
                try:
                    reference_price = int(cur)
                except (TypeError, ValueError):
                    return False

            future_cheaper = []
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
                    continue
                try:
                    blk_price = int(blk.get_avg_price(convert=False))
                except (TypeError, ValueError):
                    continue
                if blk_price < reference_price:
                    future_cheaper.append((blk_start, blk))

            if not future_cheaper:
                self.logger.log.info(
                    "Cheaper-cluster-coming abort: no strictly cheaper "
                    "future block found -- not skipping."
                )
                return False

            future_cheaper.sort(key=lambda pair: pair[0])
            target_start, target_block = future_cheaper[0]

            # ------------------------------------------------------------
            # 3) prerequisites for the shelter-chain simulation
            # ------------------------------------------------------------
            avg_list = self.statsmanager.get_data(
                "powerconsumption", "hourly_watt_average"
            )
            avg_hourly_wh = (
                round(avg_list[0], 2)
                if isinstance(avg_list, (list, tuple)) and avg_list
                else 0.0
            )
            if avg_hourly_wh <= 0:
                self.logger.log.info(
                    "Cheaper-cluster-coming abort: no consumption history "
                    "yet -- not skipping."
                )
                return False

            grid_charge_w_raw = self.statsmanager.get_data(
                "powerconsumption", "last_grid_charge_power_w"
            )
            try:
                grid_charge_w = float(grid_charge_w_raw) if grid_charge_w_raw else 0.0
            except (TypeError, ValueError):
                grid_charge_w = 0.0
            if grid_charge_w <= 0:
                self.logger.log.info(
                    "Cheaper-cluster-coming abort: no measured grid-charge "
                    "power yet -- not skipping (waiting for first grid-charge "
                    "cycle to calibrate)."
                )
                return False

            current_soc_wh = (
                self.essunit.get_battery_current_wh()
                if self.essunit else 0
            ) or 0
            min_soc_wh = (
                self.essunit.get_battery_min_wh()
                if self.essunit else 0
            ) or 0
            usable_soc_wh = max(0.0, current_soc_wh - min_soc_wh)

            # Pack usable ceiling (full - min). Fall back to a rough
            # estimate from current SOC% if get_battery_full_wh isn't
            # exposed by this essunit.
            full_wh = None
            try:
                if self.essunit and hasattr(self.essunit, "get_battery_full_wh"):
                    full_wh = self.essunit.get_battery_full_wh()
            except Exception:
                full_wh = None
            if not full_wh or full_wh <= 0:
                soc_pct = 50.0
                try:
                    if self.essunit:
                        s = self.essunit.get_soc()
                        if isinstance(s, (int, float)) and 1 <= s <= 100:
                            soc_pct = float(s)
                except Exception:
                    pass
                full_wh = current_soc_wh / (soc_pct / 100.0)
            full_wh = max(full_wh, current_soc_wh)
            usable_ceiling = max(0.0, full_wh - min_soc_wh)

            # ------------------------------------------------------------
            # 4) forward simulation
            # ------------------------------------------------------------
            # Build ordered list of future charge blocks (cheaper AND
            # not-cheaper) so the simulation walks the full remaining
            # chain, not just the cheaper subset -- otherwise we'd
            # miss the recharge from any non-cheaper cluster that
            # follows the cheaper target.
            all_future_blocks = []
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
                    continue
                all_future_blocks.append((blk_start, blk))
            all_future_blocks.sort(key=lambda pair: pair[0])

            sim_soc = usable_soc_wh
            prev_time = now_utc
            trace_parts = []
            chain_ok = True

            for start_i, blk_i in all_future_blocks:
                drain_h = max(
                    0.0, (start_i - prev_time).total_seconds() / 3600
                )
                pv_wh = self._pv_forecast_wh_between(prev_time, start_i)
                sim_soc = min(
                    usable_ceiling,
                    sim_soc - drain_h * avg_hourly_wh + pv_wh,
                )
                if sim_soc < 0:
                    trace_parts.append(
                        f"drained {drain_h:.1f}h (PV +{pv_wh:.0f}Wh) to "
                        f"{start_i.astimezone().strftime('%H:%M')} "
                        f"-> SOC {sim_soc:.0f}Wh (would run out)"
                    )
                    chain_ok = False
                    break

                blk_end = blk_i.get_end_datetime()
                if blk_end is not None and blk_end.tzinfo is None:
                    blk_end = blk_end.replace(tzinfo=timezone.utc)
                cluster_dur_h = (
                    (blk_end - start_i).total_seconds() / 3600
                    if blk_end is not None else 1.0
                )
                add_wh = cluster_dur_h * grid_charge_w
                sim_soc = min(usable_ceiling, sim_soc + add_wh)
                trace_parts.append(
                    f"drain {drain_h:.1f}h (PV +{pv_wh:.0f}Wh) then charge "
                    f"{cluster_dur_h:.1f}h @ {grid_charge_w:.0f}W = "
                    f"+{add_wh:.0f}Wh, SOC={sim_soc:.0f}Wh"
                )
                prev_time = blk_end or start_i

            # Post-last-cluster drain to end of price horizon.
            if chain_ok:
                try:
                    item_list = getattr(self.items, "_item_list", []) or []
                    horizon_end = None
                    for it in item_list:
                        he = it.get_end_datetime()
                        if he is None:
                            continue
                        if he.tzinfo is None:
                            he = he.replace(tzinfo=timezone.utc)
                        if horizon_end is None or he > horizon_end:
                            horizon_end = he
                    if horizon_end and horizon_end > prev_time:
                        drain_h = (horizon_end - prev_time).total_seconds() / 3600
                        pv_wh = self._pv_forecast_wh_between(prev_time, horizon_end)
                        sim_soc = min(
                            usable_ceiling,
                            sim_soc - drain_h * avg_hourly_wh + pv_wh,
                        )
                        trace_parts.append(
                            f"post-chain drain {drain_h:.1f}h "
                            f"(PV +{pv_wh:.0f}Wh) -> SOC {sim_soc:.0f}Wh"
                        )
                        if sim_soc < 0:
                            chain_ok = False
                except Exception:
                    # If we can't peek at the horizon we still trust
                    # the mid-chain result; drain would only make the
                    # decision more conservative anyway.
                    pass

            trace = "; ".join(trace_parts) if trace_parts else "(no chain steps)"

            if not chain_ok:
                self.logger.log.info(
                    f"Cheaper-cluster-coming abort: chain simulation would "
                    f"drain the pack -- not skipping. Trace: {trace}"
                )
                return False

            # ------------------------------------------------------------
            # 5) safe to skip
            # ------------------------------------------------------------
            hours_until = (target_start - now_utc).total_seconds() / 3600.0
            self.logger.log.info(
                f"Cheaper-cluster-coming abort: strictly cheaper cluster "
                f"{target_block.describe(localtime=True)} starts in "
                f"{hours_until:.1f}h; chain simulation ends with "
                f"SOC={sim_soc:.0f}Wh (>=0). Skipping current charge."
            )
            self._record_abort_fired("cheaper_cluster_coming")
            return True

        except Exception as e:
            self.logger.log.error(
                f"Cheaper-cluster-coming abort check failed: {e}. "
                "Keeping charging allowed."
            )
            return False

    def _record_abort_fired(self, kind):
        """
        Increment the per-day skip counter for an abort condition so
        the stats page can show how often each one actually saved a
        charge. Counters are kept in StatsManager under the `aborts`
        group, keyed by ISO date and abort kind.

        Structure:
            stats.aborts.skip_count_by_day = {
                "solar_forecast":  {"2026-04-27": 3, "2026-04-26": 1},
                "battery_range":   {"2026-04-27": 0, "2026-04-26": 2},
            }

        Plus a running total per kind (`solar_forecast_total`, etc.)
        that survives history retention pruning.

        Best-effort: any failure is swallowed because we never want
        stats book-keeping to break a control-loop decision.
        """
        try:
            from datetime import date as _date
            today = _date.today().isoformat()

            by_day = self.statsmanager.get_data("aborts", "skip_count_by_day")
            if not isinstance(by_day, dict):
                by_day = {}
            kind_dict = by_day.get(kind)
            if not isinstance(kind_dict, dict):
                kind_dict = {}
            kind_dict[today] = int(kind_dict.get(today, 0)) + 1
            by_day[kind] = kind_dict
            # Use save_data=True so the counter survives an unexpected
            # restart between now and the next reguler save. Aborts
            # fire infrequently enough that the disk write is cheap.
            self.statsmanager.set_status_data(
                "aborts", "skip_count_by_day", by_day,
            )

            total_key = f"{kind}_total"
            current_total = self.statsmanager.get_data("aborts", total_key) or 0
            self.statsmanager.set_status_data(
                "aborts", total_key, int(current_total) + 1,
            )
        except Exception as e:
            self.logger.log.debug(f"Skip-counter update failed: {e}")

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

        # Use REMAINING minutes per block, not full duration. A block
        # that's currently active 18:00-20:00 still has only 30 minutes
        # left at 19:30 -- we shouldn't reserve capacity for the full 2h.
        from datetime import datetime, timezone, timedelta
        now_utc = datetime.now(timezone.utc)
        total_minutes = 0
        for blk in future_high_blocks:
            blk_end = blk.get_end_datetime() if hasattr(blk, "get_end_datetime") else None
            if blk_end is None:
                blk_start = blk.get_start_datetime()
                if blk_start is None:
                    continue
                if blk_start.tzinfo is None:
                    blk_start = blk_start.replace(tzinfo=timezone.utc)
                blk_end = blk_start + timedelta(minutes=blk.get_duration_minutes() or 0)
            if blk_end.tzinfo is None:
                blk_end = blk_end.replace(tzinfo=timezone.utc)
            remaining_seconds = max(0, (blk_end - now_utc).total_seconds())
            total_minutes += int(remaining_seconds / 60)

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
