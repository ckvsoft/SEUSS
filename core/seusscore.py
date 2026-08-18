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
# -*- coding: utf-8 -*-

import os
import signal
import sys
import threading
import time
import random
import json
from datetime import datetime, timedelta

import core.version as version
from core.statsmanager import StatsManager
from core.websocketserver import WebSocketServer
from solar.openmeteo import OpenMeteo  # noqa: F401  (kept for backward compat)
from solar.solarforecastmanager import SolarForecastManager
from solar.solardata import Solardata
from core.conditions import Conditions, ConditionResult
from core.config import Config
from core.log import CustomLogger
from design_patterns.factory.generic_loader_factory import GenericLoaderFactory
from spotmarket.abstract_classes.itemlist import Itemlist
from core.seussweb import SEUSSWeb
from core.timeutilities import TimeUtilities
from powerconsumption.powerconsumptionmanager import PowerConsumptionManager
from smartswitches.smartswitchesmanager import SmartSwitchesManager

class SEUSS:
    def __init__(self):
        self.config = Config()
        self.logger = CustomLogger()
        self.svs_thread = None
        self.ws_server = WebSocketServer()
        self.seuss_web = SEUSSWeb()
        self.power_consumption_manager = PowerConsumptionManager()
        self.statsmanager = StatsManager()
        self.statsmanager.remove_unused_datagroups()

        self.no_data = [0]
        self.interval_minutes = 5
        self.svs_thread_stop_flag = threading.Event()
        self.solardata = Solardata()
        self.items = Itemlist.create_item_list([])
        self.smartswitches = SmartSwitchesManager()
        self.smartswitches.turn_off_all()
        self.current_time = datetime.now()

    def handle_config_update(self, config_data):
        self.logger.log.info("Run checks while configuration was changed")
        self.load_configuration()
        self.items.remove_all_items()
        self.smartswitches = SmartSwitchesManager()
        self.run_markets()

    def run_markets(self):
        self.items = self.update_items()
        self.seuss_web.set_item_list(self.items)
        self.run_essunit()

    def run_essunit(self):
        essunit = self.initialize_essunit()
        if essunit is not None:
            unit_config = essunit.get_config()
            active_soc_limit = essunit.get_active_soc_limit()
            soc = essunit.get_soc()

            # Persist battery capacity in Wh into the StatsManager so
            # the web layer (stats page in particular) can read it
            # without holding a reference to the essunit. Victron
            # reports capacity in Ah; get_battery_full_wh() converts
            # using the configured pack voltage. Best-effort -- if the
            # essunit can't deliver values right now (D-Bus timeout
            # etc.) we just skip this update.
            try:
                full_wh = essunit.get_battery_full_wh() or 0
                if full_wh > 0:
                    # Persist to disk (save_data=True): the stats handler
                    # creates a fresh StatsManager() on every page load,
                    # which calls load_data() and overwrites the class-
                    # level dict with whatever's on disk. RAM-only writes
                    # with save_data=False would be wiped out before the
                    # web layer ever sees them, leaving cycles=0 forever.
                    self.statsmanager.set_status_data(
                        "ess_unit", "battery_full_wh", round(float(full_wh), 1),
                    )
            except Exception as e:
                self.logger.log.debug(f"battery_full_wh persist skipped: {e}")

            delay_active_soc_limit = self.config.config_data.get("delay_grid_charging_below_active_soc_limit", False)
            self.logger.log.debug(f"Active Soc Limit: {active_soc_limit} Soc: {soc}")

            if delay_active_soc_limit and (soc if soc is not None else 0) < (active_soc_limit if active_soc_limit is not None else 0):
                check_limit = self.statsmanager.get_data("ess_unit", "soc_limit")
                if check_limit is None:
                    self.statsmanager.set_status_data("ess_unit", "soc_limit", active_soc_limit, save_data=False)
                    self.logger.log.info(f"Save Active Soc Limit Status: {active_soc_limit}")

                self.statsmanager.set_status_data("ess_unit", "soc_delay", 1)
                t_soc = soc #(soc // 5) * 5
                if t_soc < active_soc_limit:
                    self._apply_active_soc_limit(essunit, t_soc)

            else:
                check_limit = self.statsmanager.get_data("ess_unit", "soc_limit")

                if check_limit is not None:
                    if soc and active_soc_limit:
                        if soc > active_soc_limit:
                            t_soc = soc # (soc // 5) * 5
                            if t_soc < check_limit:
                                self._apply_active_soc_limit(essunit, t_soc)

                        if active_soc_limit > check_limit:
                            self.statsmanager.set_status_data("ess_unit", "soc_limit", active_soc_limit)
                            self.logger.log.info(f"Update Active Soc Limit Status: {active_soc_limit}")

                        if abs(soc - check_limit) <= 1:
                                # Auf gespeicherten Wert zurücksetzen und Delay beenden
                                self._apply_active_soc_limit(essunit, check_limit)
                                self.statsmanager.remove_data("ess_unit", "date_soc_limit", save_data=False)
                                self.statsmanager.remove_data("ess_unit", "soc_limit", save_data=False)
                                self.statsmanager.set_status_data("ess_unit", "soc_delay", 0)

            self.power_consumption_manager.update_instance(unit_config)
            if self.ws_server:
                power_consumption_instance = self.power_consumption_manager.get_instance()
                if power_consumption_instance:
                    power_consumption_instance.set_ws_server(self.ws_server)
                    power_consumption_instance.set_current_price(self.items.get_current_price(True))

            # if essunit is not None:
            #    essunit.get_data()
            inverter_sum_today_wh = self.process_solar_data(essunit)
            self.process_solar_forecast(inverter_sum_today_wh)
            if self.items.get_item_count() > 0:
                self.evaluate_conditions_and_control_charging_discharging(essunit)
            else:
                self.handle_no_data(essunit)

            next_minute = (self.current_time.minute // self.interval_minutes + 1) * self.interval_minutes
            if next_minute >= 60:
                next_hour = self.current_time.replace(second=0, microsecond=0, minute=0) + timedelta(hours=1)
            else:
                next_hour = self.current_time.replace(second=0, microsecond=0, minute=next_minute)
            next_run_time = next_hour
            self.logger.log.info(f"Next {essunit.get_name()} check at {next_run_time.strftime('%H:%M')}")
            return

        self.power_consumption_manager.stop_instance()
        self.logger.log.info("No enabled essunit found.")

    def run_svs(self):
        self.load_configuration()
        self.initialize_logging()
        self.config.observer.add_observer("seuss", self)
        lasttime_minute = None  # Startwert bleibt None, damit die erste Ausführung sofort möglich ist

        try:
            while True:
                # Per-iteration safety net: any unhandled exception inside
                # run_markets/run_essunit/perform_test_run (e.g. a network
                # timeout that wasn't caught at the provider level) must
                # NOT kill this thread. The thread IS the main eval loop;
                # if it dies, SEUSS goes silent until the next process
                # restart. Observed 2026-06-12: ENTSO-E ReadTimeout
                # escaped entsoe.load_data, killed run_svs, no prices
                # updated for hours until kill -9 + auto-restart.
                try:
                    self.current_time = datetime.now()

                    if (self.current_time.minute == 0 and self.current_time.second == 5) or self.items.get_item_count() == 0:
                        self.run_markets()
                        if self.items:
                            next_hour = self.current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                            self.logger.log.info(f"Next price check at {next_hour.strftime('%H:%M')}")
                            self.logger.log.info(
                                f"Current Spotmarket: {self.items.current_market_name}, failback: {self.items.failback_market_name}"
                            )

                    if self.current_time.minute % self.interval_minutes == 0 and self.current_time.minute != 0 and self.current_time.minute != lasttime_minute:
                        lasttime_minute = self.current_time.minute

                        count = self.items.get_item_count()
                        self.logger.log.debug(f"Item count: {count}")
                        self.logger.log.debug(f"Current hour: {self.current_time.hour}")
                        if (self.config.use_second_day and count < 25) and 13 <= self.current_time.hour < 15:
                            self.run_markets()
                        else:
                            self.run_essunit()

                        if self.items:
                            next_hour = self.current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                            self.logger.log.info(f"Next price check at {next_hour.strftime('%H:%M')}")
                            self.logger.log.info(
                                f"Current Spotmarket: {self.items.current_market_name}, failback: {self.items.failback_market_name}"
                            )

                    self.perform_test_run()
                    self.handle_no_data_sleep()
                except KeyboardInterrupt:
                    raise  # Let the outer handler do graceful_exit
                except Exception as iter_exc:
                    self.logger.log.exception(
                        f"Unhandled error in run_svs iteration: {iter_exc}. "
                        f"Continuing -- next iteration will retry."
                    )

                self.current_time = datetime.now()
                sleep_time = 1 - (self.current_time.microsecond / 1_000_000)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.graceful_exit(signal.SIGINT, None)

    def load_configuration(self):
        self.config.load_config()

    def initialize_logging(self):
        self.logger.log.info(f"SEUSS v{version.__version__} started...")
        self.logger.log.info(f"{self.config.config_data}")

    def update_items(self):
        return self.items.perform_update(self.items)

    def initialize_essunit(self):
        if self.config.essunit is None:
            self.logger.log.warning(f"essunit is None. Try to reload config")
            self.config.load_config()

        return GenericLoaderFactory.create_loader("essunit", self.config.essunit)

    def process_solar_data(self, essunit):
        inverter_sum_today_wh = 0.0
        if essunit is not None:
            inverter_sum_today_wh = self.collect_meters_and_inverter_sum(essunit)

        return inverter_sum_today_wh

    def collect_meters_and_inverter_sum(self, essunit):
        """
        Walks the configured grid meters (for logging + the
        forward_hourly stats update) and the configured PV inverters
        (to sum their forward-counter Wh for today).

        Two outputs are produced:

        * `inverter_sum_today_wh` -- the sum of inverter forward
          counters since 00:00, returned to the caller. Used downstream
          ONLY for the "solar hour performance" log line in
          process_solar_forecast (observed-vs-forecast ratio for ops
          visibility). NOT pushed to solardata anymore -- it has been
          observed to drift ~25% from reality (e.g. 26500 Wh inverter
          sum vs ~21000 Wh actual yield), so feeding it into the
          adjustment-factor learning loop poisoned that loop.

        * `pv_measured_today_wh` -- the authoritative measured yield,
          read from PowerConsumption.daily_pv_wh (GX-bus integrated
          PV power, matches Victron VRM and the home-page "PV today"
          tile). This is what gets pushed to solardata for downstream
          consumers (openmeteo learning loop, conditions abort logic,
          stats page).
        """
        gridmeters = essunit.get_grid_meters()
        inverters = essunit.get_solar_energy()
        inverter_sum_today_wh = 0.0

        for key_outer, value_outer in gridmeters.gridmeters.items():
            customname = gridmeters.get_value(key_outer, 'CustomName')
            productname = gridmeters.get_value(key_outer, 'ProductName')
            forward = gridmeters.get_forward_kwh(key_outer)
            forward_hourly = gridmeters.get_hourly_kwh(key_outer)
            self.logger.log.debug(f"Found Gridmeter:  {productname} {customname}.")
            self.logger.log.info(
                f"{productname} {customname} today:  {round(forward, 2)} Wh, average hour: {round(forward_hourly, 2)} Wh")

            for key_inner, value_inner in value_outer.items():
                self.logger.log.debug(f"  {key_inner}: {json.loads(value_inner)['value']}")

        total_forward_hourly_list = self.statsmanager.get_data("powerconsumption","hourly_watt_average")
        total_forward_hourly = total_forward_hourly_list[0] if total_forward_hourly_list else 0.0
        manager_instance = self.power_consumption_manager.get_instance()
        pv_measured_today_wh = 0.0
        if manager_instance:
            value = manager_instance.get_hourly_average()
            consumption = manager_instance.get_daily_wh()
            pv_measured_today_wh = float(manager_instance.get_daily_pv_wh() or 0.0)
            if value > 0.0:
                total_forward_hourly = (total_forward_hourly + value) / 2
            self.logger.log.info(
                f"Consumption today: {round(consumption, 2):.2f} Wh, forecast today: {total_forward_hourly * 24:.2f} Wh average hour: {round(total_forward_hourly, 2):.2f} Wh")

            self.statsmanager.update_percent_status_data('gridmeters', 'forward_hourly', total_forward_hourly)

        for key_outer, value_outer in inverters.inverters.items():
            customname = inverters.get_value(key_outer, 'CustomName')
            productname = inverters.get_value(key_outer, 'ProductName')
            forward = inverters.get_forward_kwh(key_outer)
            inverter_sum_today_wh += float(forward)
            self.logger.log.debug(f"Found PV Inverter:  {productname} {customname}.")
            self.logger.log.info(f"{productname} {customname} yield today:  {round(forward, 2)} Wh.")

            for key_inner, value_inner in value_outer.items():
                self.logger.log.debug(f"  {key_inner}: {json.loads(value_inner)['value']}")

        self.logger.log.info(
            f"All Inverters yield today (forward-counter sum):  {round(inverter_sum_today_wh, 2)} Wh, "
            f"authoritative PV measured today (GX-bus): {round(pv_measured_today_wh, 2)} Wh.")

        # Authoritative override: the inverter forward-counter is
        # robust against SEUSS being offline (the inverter keeps
        # counting on its own). The GX-bus integration we run in
        # PowerConsumption can only count PV power it actually saw
        # tick-by-tick, so any restart, network hiccup, or process
        # downtime leaves a gap. If the forward-counter sum is higher
        # than the integrated value, the gap exists -- adopt the
        # counter value as the authoritative "PV today" so the stats
        # page, pv_wh_by_day, and the openmeteo learning loop see
        # the real yield. We only adjust UPWARD; if the counter is
        # somehow lower (forward_start race condition, counter reset)
        # we keep the integrated value to avoid going backwards.
        if (inverter_sum_today_wh > 0
                and inverter_sum_today_wh > pv_measured_today_wh):
            gap = inverter_sum_today_wh - pv_measured_today_wh
            self.logger.log.info(
                f"PV gap detected: integrator {pv_measured_today_wh:.0f} Wh "
                f"vs forward-counter {inverter_sum_today_wh:.0f} Wh "
                f"(+{gap:.0f} Wh). Adopting counter value."
            )
            try:
                if manager_instance and hasattr(manager_instance, "set_daily_pv_wh"):
                    manager_instance.set_daily_pv_wh(inverter_sum_today_wh)
                pv_measured_today_wh = inverter_sum_today_wh
            except Exception as e:
                self.logger.log.warning(
                    f"Couldn't apply forward-counter override: {e}"
                )

        # Push the authoritative value to solardata, NOT the inverter
        # forward-counter sum -- see method docstring for why.
        self.solardata.update_pv_measured_today_wh(round(pv_measured_today_wh, 2))
        # Also hand the counter sum over so the forecast learning loop
        # can cross-check both chains and skip learning while they
        # disagree (broken measurement basis, e.g. WLAN outage).
        self.solardata.update_inverter_sum_today_wh(round(inverter_sum_today_wh, 2))
        # PV-feed staleness: no complete PV aggregate for >3 min means
        # the DTU/WLAN path is down. During MULTI-DAY outages both
        # chains read ~0 and the cross-check above can't fire, so the
        # learning loop needs this explicit signal to stay paused.
        try:
            import time as _time
            last_ts = getattr(manager_instance, "last_pv_aggregate_ts", 0) or 0
            stale = bool(last_ts) and (_time.time() - last_ts) > 180
            self.solardata.update_pv_feed_stale(stale)
        except Exception:
            pass
        return inverter_sum_today_wh

    def process_solar_forecast(self, inverter_sum_today_wh):
        forecast_provider = SolarForecastManager()
        # Now returns a dictionary
        forecast_results = forecast_provider.forecast(self.solardata)

        adj = self.statsmanager.get_data('solar', 'adjustment_factor') or [1.0]
        adj_factor = adj[0]
        efficiency_display = round(adj_factor * 100, 2)

        # Calculate expected yield from 00:00 until the end of the current hour
        # We apply the adjustment_factor to the raw forecast
        expected_until_now = (forecast_results["past_today"] + forecast_results["current_hour"]) * adj_factor

        if expected_until_now > 0.0:
            # Ops-visibility log: how does the inverter forward-counter
            # sum compare to the adjusted forecast for the same window?
            # We deliberately use the inverter sum here (not the
            # authoritative pv_measured_today_wh) because this metric
            # is meant to surface inverter-vs-model drift -- the same
            # drift that motivated switching the learning loop OFF the
            # inverter sum.
            solar_performance = round((inverter_sum_today_wh / expected_until_now) * 100, 2)

            self.logger.log.info(f"Solar hour performance (inverter sum vs adjusted forecast): {solar_performance}%.")
            self.logger.log.info(f"Current System Efficiency (Adj-Factor): {efficiency_display}%")
        else:
            self.logger.log.info(f"Solar forecast until now is zero. Current Adj-Factor: {efficiency_display}%")

    def evaluate_conditions_and_control_charging_discharging(self, essunit):
        # Previously this method was completely skipped when an essunit
        # was in observation mode -- which meant no condition evaluation
        # at all, and the user couldn't see WHAT SEUSS would do. We now
        # always run the evaluation, and let the _apply_* wrappers (in
        # control_charging / control_discharging / control_switching)
        # decide whether to actually touch the hardware. Lines prefixed
        # with [OBSERVATION] mark the points where a real run would
        # have changed state.
        condition_charging_result = ConditionResult()
        condition_discharging_result = ConditionResult()
        condition_switching_result = ConditionResult()
        conditions_instance = Conditions(self.items, essunit, self.solardata)
        conditions_instance.info()
        conditions_instance.evaluate_conditions(condition_charging_result, "charging")
        conditions_instance.evaluate_conditions(condition_discharging_result, "discharging")
        conditions_instance.evaluate_conditions(condition_switching_result, "switching")

        self.control_charging(essunit, condition_charging_result)
        self.control_discharging(essunit, condition_discharging_result)
        self.control_switching(condition_switching_result, essunit=essunit)

        self.items.log_items()
        self.no_data[0] = 0

    def control_switching(self, condition_switching_result, essunit=None):
        # Per-IP switching: when at least one configured smart switch
        # has per-IP overrides (lowest_prices_per_ip / block_minutes_per_ip),
        # we delegate the on/off decision to the manager's per-IP
        # evaluator instead of toggling all switches in lockstep.
        # The legacy bulk path (turn_on_all / turn_off_all) is kept for
        # configurations without any per-IP overrides, so existing setups
        # behave exactly as before.
        if self._smart_switches_have_per_ip_overrides():
            if self._is_observation_mode(essunit):
                self.logger.log.info(
                    "[OBSERVATION] Would evaluate per-IP smartswitch logic"
                )
                return
            charging_count = getattr(
                self.config, "number_of_lowest_prices_for_charging", 0
            ) or 0
            self.smartswitches.evaluate_per_ip(self.items, charging_count)
            return

        if condition_switching_result.execute:
            self.logger.log.info(
                f"Condition {condition_switching_result.condition} result: {condition_switching_result.execute}, switching mode is turned on."
            )
            self._apply_smartswitches(turn_on=True, essunit=essunit)

        elif condition_switching_result.condition:
            self.logger.log.info(
                f"{condition_switching_result.condition}, switching mode is turned off."
            )
            self._apply_smartswitches(turn_on=False, essunit=essunit)

        else:
            self.logger.log.info("Since none of the switching conditions are true, switching mode is turned off.")
            self._apply_smartswitches(turn_on=False, essunit=essunit)

    def _smart_switches_have_per_ip_overrides(self):
        """Return True iff any configured smart switch has a non-empty
        lowest_prices_per_ip or block_minutes_per_ip setting."""
        for entry in self.config.config_data.get("smart_switches", []):
            if not entry.get("enabled", True):
                continue
            if (entry.get("lowest_prices_per_ip", "").strip()
                    or entry.get("block_minutes_per_ip", "").strip()):
                return True
        return False

    def control_charging(self, essunit, condition_charging_result):
        if condition_charging_result.execute and essunit is not None:
            self.logger.log.info(
                f"Condition {condition_charging_result.condition} result: {condition_charging_result.execute}, charging is turned on.")
            self._apply_charge(essunit, "on")
            self._apply_smartswitches(turn_on=True, essunit=essunit)

            initial_data = self.statsmanager.get_data('energy', "initial_charge_state_wh")
            if not initial_data:
                self.statsmanager.set_status_data('energy', "initial_charge_state_wh", (essunit.get_battery_current_wh(), TimeUtilities.get_now().isoformat()))

            self.update_charging_statistics(essunit)

        elif condition_charging_result.condition and essunit is not None:
            self.logger.log.info(f"{condition_charging_result.condition}, charging is turned off.")
            self._apply_charge(essunit, "off")
            self._apply_smartswitches(turn_on=False, essunit=essunit)
            self.statsmanager.remove_data('energy', "initial_charge_state_wh")

        elif essunit is not None:
            self.logger.log.info("Since none of the charging conditions are true, charging is turned off.")
            self._apply_charge(essunit, "off")
            self._apply_smartswitches(turn_on=False, essunit=essunit)
            self.statsmanager.remove_data('energy', "initial_charge_state_wh")

    def control_discharging(self, essunit, condition_discharging_result):
        if condition_discharging_result.execute and essunit is not None:
            self.logger.log.info(
                f"Condition {condition_discharging_result.condition} result: {condition_discharging_result.execute}, discharging is turned on.")
            self._apply_discharge(essunit, "on")
        elif condition_discharging_result.condition and essunit is not None:
            self.logger.log.info(f"{condition_discharging_result.condition}, discharging is turned off.")
            self._apply_discharge(essunit, "off")
        elif essunit is not None:
            self.logger.log.info("Since none of the discharging conditions are true, discharging is turned off.")
            self._apply_discharge(essunit, "off")

    def update_charging_statistics(self, essunit):
        current_wh = essunit.get_battery_current_wh()

        stored_data = self.statsmanager.get_data('energy', "initial_charge_state_wh")
        if not stored_data:
            return

        initial_wh, timestamp_str = stored_data
        start_time = datetime.fromisoformat(timestamp_str)
        now = TimeUtilities.get_now()

        if start_time is None or start_time == 0 or current_wh <= initial_wh:
            return

        minutes_passed = (now - start_time).total_seconds() / 60
        if minutes_passed <= 0:
            return

        current_wh_per_min = (current_wh - initial_wh) / minutes_passed

        self.statsmanager.update_percent_status_data('energy', "average_charge_wh_per_min", current_wh_per_min)
        self.logger.log.debug(f"Updated charge average: {current_wh_per_min:.2f} Wh/min over {minutes_passed:.1f} min")

    def handle_no_data(self, essunit):
        self.logger.log.warning("No data available")
        self.no_data[0] += 1
        if essunit is not None:
            self.logger.log.info("There are currently no prices, so the charging mode is turned off.")
            self._apply_discharge(essunit, "off")
            self.logger.log.info("There are currently no prices, so the discharging mode is turned on.")
            self._apply_discharge(essunit, "on")

    def perform_test_run(self):
        test_run = os.environ.get('TESTRUN')
        if test_run is not None:
            self.graceful_exit(signal.SIGINT, None)

    # ------------------------------------------------------------------
    # Hardware-write wrappers that respect `only_observation`.
    #
    # When an essunit is in observation mode, we still let SEUSS run
    # the full conditions/abort evaluation (so the user can see in the
    # log what would happen), but we do NOT actually flip charge state,
    # discharge state, the active SOC limit, or the smartswitch relays.
    # Each wrapper logs an [OBSERVATION] line describing what would
    # have happened.
    #
    # IMPORTANT: every direct call to `essunit.set_charge(...)`,
    # `essunit.set_discharge(...)`, `essunit.set_active_soc_limit(...)`
    # and `self.smartswitches.turn_on_all()/turn_off_all()` in the
    # control flow goes through one of these wrappers instead. New
    # places that need to write hardware must use these wrappers --
    # bypassing them would silently break observation mode.
    # ------------------------------------------------------------------

    def _is_observation_mode(self, essunit):
        """True if the given essunit is configured `only_observation: true`."""
        if essunit is None:
            return False
        try:
            info = self.config.get_essunit_info(essunit.get_name())
            return bool(info.get("only_observation", False))
        except Exception:
            return False

    def _apply_charge(self, essunit, state):
        if essunit is None:
            return
        if self._is_observation_mode(essunit):
            self.logger.log.info(
                f"[OBSERVATION] Would set charge -> {state} on {essunit.get_name()}"
            )
            return
        essunit.set_charge(state)

    def _apply_discharge(self, essunit, state):
        if essunit is None:
            return
        if self._is_observation_mode(essunit):
            self.logger.log.info(
                f"[OBSERVATION] Would set discharge -> {state} on {essunit.get_name()}"
            )
            return
        essunit.set_discharge(state)

    def _apply_active_soc_limit(self, essunit, value):
        if essunit is None:
            return
        if self._is_observation_mode(essunit):
            self.logger.log.info(
                f"[OBSERVATION] Would set active SOC limit -> {value}% on {essunit.get_name()}"
            )
            return
        essunit.set_active_soc_limit(value)

    def _apply_smartswitches(self, turn_on, essunit=None):
        """
        Smartswitches don't belong to a single essunit, but they're part
        of the same control decision. We treat them as observation-bound
        when ANY essunit currently in scope is in observation mode --
        the typical setup has one essunit, so this is a clean rule.
        """
        if self._is_observation_mode(essunit):
            self.logger.log.info(
                f"[OBSERVATION] Would turn smartswitches "
                f"{'on' if turn_on else 'off'}"
            )
            return
        if turn_on:
            self.smartswitches.turn_on_all()
        else:
            self.smartswitches.turn_off_all()

    def handle_no_data_sleep(self):
        if 0 < self.no_data[0] < 4:
            sleeptime = random.randint(10, 60)
            self.logger.log.info(
                f"There is no data available, attempt number {self.no_data[0]}/3 failed. wait {sleeptime} seconds for the next attempt.")
            time.sleep(sleeptime)
        else:
            self.no_data[0] = 0  # Aktualisiere die verpackte Variable

    def handle_time_to_next_hour(self, current_time):
        next_hour = (current_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        time_to_next_hour = int((next_hour - current_time).total_seconds())
        self.logger.log.info(f"Next price check at {next_hour.strftime('%H:%M')}")
        if self.items:
            self.logger.log.info(
                f"Current Spotmarket: {self.items.current_market_name}, failback: {self.items.failback_market_name}")
        time.sleep(max(0, time_to_next_hour + 2))

    def graceful_exit(self, signum, frame):
        print("\r   ")  # clear ^C
        print(f"Program will be terminated... signal: {signum}")
        self.logger.log.info(f"Program will be terminated... signal: {signum}")

        self.power_consumption_manager.stop_instance()
        self.statsmanager.save_data()
        self.ws_server.stop()
        self.seuss_web.stop()
        self.svs_thread_stop_flag.set()

        sys.exit(0)

    def excepthook_handler(self, exc_type, exc_value, exc_traceback):
        self.logger.log.error(f"Unknown Exception exc_info=({exc_type}, {exc_value}, {exc_traceback})")

    def start(self):
        sys.excepthook = self.excepthook_handler

        # WebSocket-Server starten
        ws_server_thread = threading.Thread(target=self.ws_server.run, daemon=True)
        ws_server_thread.start()

        bottle_thread = threading.Thread(target=self.seuss_web.run, daemon=True)
        bottle_thread.start()

        self.svs_thread = threading.Thread(target=self.run_svs, daemon=True)
        self.svs_thread.start()

        signal.signal(signal.SIGINT, self.graceful_exit)
        signal.signal(signal.SIGTERM, self.graceful_exit)

        try:
            while not self.svs_thread_stop_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.graceful_exit(signal.SIGINT, None)
