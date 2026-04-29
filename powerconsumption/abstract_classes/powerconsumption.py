#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2025 Christian Kvasny chris(at)ckvsoft.at
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

import threading
import time
import calendar
from datetime import date, datetime, timedelta

from core.log import CustomLogger
from core.statsmanager import StatsManager
from core.timeutilities import TimeUtilities

class PowerDataHandler:
    def __init__(self):
        self._logger = CustomLogger()
        self.num_ac_phases = None  # Wird per MQTT gesetzt
        self.num_grid_phases = None
        self.ac_phases = {}
        self.grid_phases = {}
        self.dc_data = {}
        self.pv_data = {}
        self.updated_ac_phases = set()
        self.updated_grid_phases = set()
        self.final_data = {}
        self.checked_data = {}
        self.total_loss = 0
        self.last_loss_efficiency = (0, 100)

    def update_values(self, topic, payload):
        """Empfängt MQTT-Daten und aktualisiert Werte."""
        value = payload.get("value")
        if value is not None:
            self.checked_data[topic] = True

        if topic == "number_of_phases":
            self.num_ac_phases = int(value)
        elif topic == "number_of_grid_phases":
            self.num_grid_phases = int(value)

        # PV-Daten erfassen
        elif topic == "PV_DC":
            self.pv_data["PV_DC"] = value if value else 0
        elif "PV_AC_OUT" in topic:
            if "L1" in topic:
                self.pv_data["PV_AC_OUT_L1"] = value if value is not None else 0
            elif "L2" in topic:
                self.pv_data["PV_AC_OUT_L2"] = value if value is not None else 0
            elif "L3" in topic:
                self.pv_data["PV_AC_OUT_L3"] = value if value is not None else 0
        elif "PV_AC_GRID" in topic:
            if "L1" in topic:
                self.pv_data["PV_AC_GRID_L1"] = value if value is not None else 0
            elif "L2" in topic:
                self.pv_data["PV_AC_GRID_L2"] = value if value is not None else 0
            elif "L3" in topic:
                self.pv_data["PV_AC_GRID_L3"] = value if value is not None else 0
        elif "PV_AC_GENSET" in topic:
            if "L1" in topic:
                self.pv_data["PV_AC_GENSET_L1"] = value if value is not None else 0
            elif "L2" in topic:
                self.pv_data["PV_AC_GENSET_L2"] = value if value is not None else 0
            elif "L3" in topic:
                self.pv_data["PV_AC_GENSET_L3"] = value if value is not None else 0

        # AC-Verbrauch erfassen
        elif topic.startswith("P_AC_consumption_L"):
            phase = topic.split("_")[-1]
            self.ac_phases[phase] = value
            self.updated_ac_phases.add(phase)

        # Grid-Verbrauch erfassen
        elif topic.startswith("G_AC_consumption_L"):
            phase = topic.split("_")[-1]
            self.grid_phases[phase] = value
            self.updated_grid_phases.add(phase)

        # Batterie-Verbrauch
        elif topic == "P_DC_consumption_Battery":
            if value is not None:
                self.dc_data["Battery"] = value

        elif topic == "SOC":
            self.final_data["SOC"] = value

        # Berechnungen ausführen
        self.calculate_power()

    def calculate_power(self):
        """Berechnet AC_POWER, AC_GRID_POWER, PV_POWER, DC_POWER und TOTAL_POWER."""

        # Sicherstellen, dass für AC und Grid mindestens ein gültiger Wert da ist
        if self.data_complete(self.updated_ac_phases, self.num_ac_phases):
            self.final_data["AC_POWER"] = sum(v for v in self.ac_phases.values() if v is not None)
            self.reset(self.updated_ac_phases)

        if self.data_complete(self.updated_grid_phases, self.num_grid_phases):
            self.final_data["AC_GRID_POWER"] = sum(v for v in self.grid_phases.values() if v is not None)
            self.reset(self.updated_grid_phases)

        battery_value = self.dc_data.get("Battery")
        if battery_value is not None:
            self.final_data["DC_POWER"] = battery_value
            self.dc_data.clear()

        keys = [
            "PV_AC_OUT_L1", "PV_AC_OUT_L2", "PV_AC_OUT_L3",
            "PV_AC_GRID_L1", "PV_AC_GRID_L2", "PV_AC_GRID_L3",
            "PV_AC_GENSET_L1", "PV_AC_GENSET_L2", "PV_AC_GENSET_L3",
            "PV_DC"
        ]

        if all(self.pv_data.get(key) is not None for key in keys):
            self.final_data["PV_POWER"] = sum(self.pv_data.values())
            self.reset(self.pv_data)

        if len([value for value in self.final_data.values() if value is not None]) >= 3:
            if self.all_required_data_complete():
                self.final_data["TOTAL_POWER"], self.final_data["EFFICIENCY"] = self.process_data()

    def data_complete(self, phase_set, num_phases):
        """Überprüft, ob alle Phasen vorhanden sind oder wenn Phasenanzahl nicht bekannt ist."""
        if num_phases is None:
            return False
        return len(phase_set) >= num_phases

    def all_required_data_complete(self):
        """Prüft, ob alle relevanten Werte für die Berechnung vorhanden sind."""
        return all(key in self.final_data for key in ["AC_POWER", "AC_GRID_POWER", "DC_POWER", "PV_POWER"])

    def check_for_data(self):
        missing_data = []

        # Prüfen, ob alle notwendigen Felder vorhanden sind
        if self.checked_data.get("P_AC_consumption_L1") is None:
            missing_data.append("P_AC_consumption_L1")
        if self.num_ac_phases is None:
            missing_data.append("number_of_phases")

        # Nur für 2 oder 3 Phasen:
        if self.num_ac_phases is not None and self.num_ac_phases >= 2 and self.checked_data.get(
                "P_AC_consumption_L2") is None:
            missing_data.append("P_AC_consumption_L2")
        if self.num_ac_phases is not None and self.num_ac_phases == 3 and self.checked_data.get(
                "P_AC_consumption_L3") is None:
            missing_data.append("P_AC_consumption_L3")

        # Grid-Daten
        if self.checked_data.get("G_AC_consumption_L1") is None:
            missing_data.append("G_AC_consumption_L1")
        if self.num_grid_phases is None:
            missing_data.append("number_of_grid_phases")

        # Nur für 2 oder 3 Phasen:
        if self.num_grid_phases is not None and self.num_grid_phases >= 2 and self.checked_data.get(
                "G_AC_consumption_L2") is None:
            missing_data.append("G_AC_consumption_L2")
        if self.num_grid_phases is not None and self.num_grid_phases == 3 and self.checked_data.get(
                "G_AC_consumption_L3") is None:
            missing_data.append("G_AC_consumption_L3")

        # Hier auch die PV_DC-Überprüfung und ggf. Initialisierung:
        if self.checked_data.get("PV_DC") is None:
            self.final_data["PV_DC"] = 0
            # missing_data.append("PV_DC")

        if missing_data:
            self._logger.log.debug(f"Missing data: {', '.join(missing_data)}")
            return False

        return True

    def process_data(self):
        """Perform calculations with complete data."""

        ac_grid_power = self.final_data.get("AC_GRID_POWER", 0)
        dc_power = self.final_data.get("DC_POWER", 0)
        # Energy entering the system from known sources:
        #   battery discharge (dc_power < 0 means OUT of pack), grid
        #   import (ac_grid_power > 0 means INTO the house), and PV.
        # Each term is taken as a positive Watt contribution.
        energy_input = (
            -min(dc_power, 0)
            + max(ac_grid_power, 0)
            + self.final_data.get("PV_POWER", 0)
        )

        # Energy leaving the system to known sinks:
        #   AC consumption (always positive), grid export (the
        #   ac_grid_power < 0 case), and battery charge (dc_power > 0).
        # Grid export was previously added as `min(ac_grid_power, 0)`
        # (a negative number), which subtracted instead of summing
        # and made `usable_energy` go strongly negative on export-heavy
        # PV days, producing nonsensical "Loss > total throughput" and
        # "Efficiency < 0" readings. Fix: add the magnitude of the
        # export, i.e. `-min(ac_grid_power, 0)` which is non-negative.
        usable_energy = (
            self.final_data.get("AC_POWER", 0)
            + (-min(ac_grid_power, 0))
            + max(dc_power, 0)
        )

        # Loss is the unaccounted-for excess of input over usable. With
        # both terms now correctly signed, this is the inverter /
        # wiring loss when positive; negative values indicate a sensor
        # or convention issue and are clamped to 0 here (the daily
        # `imbalance_wh` accumulator preserves the signed value for
        # diagnostics).
        loss = max(energy_input - usable_energy, 0)


        # Calculate efficiency and ensure it doesn't exceed 100%
        efficiency = (usable_energy / energy_input) * 100 if energy_input > 0 else 100

        # Clamp efficiency to 100% if necessary
        efficiency = min(efficiency, 100)

        if efficiency < 100.0 and loss > 0.0:
            self.total_loss = loss
            self.last_loss_efficiency = (loss, efficiency)

        return self.last_loss_efficiency

    def is_complete(self, phase_set, num_phases):
        """Überprüft, ob alle Phasen im Set aktualisiert wurden."""
        required_phases = {f"L{i + 1}" for i in range(num_phases)}
        return required_phases.issubset(phase_set)

    def reset(self, phase_set):
        """Setzt das Phase-Set zurück, nachdem die Berechnung abgeschlossen ist."""
        phase_set.clear()  # Alle Phasen in diesem Set zurücksetzen

    def get_power(self, power_type):
        """
        Gibt den aggregierten Power-Wert für den angegebenen Typ zurück:
          - "PV_POWER": Summe aus PV_DC und allen PV_AC-Werten
          - "AC_GRID_POWER": Aggregierte Grid-Leistung
          - "AC_POWER": Aggregierte AC-Leistung
          - "BATTERY_POWER": Den Batterieverbrauchswert (P_DC_consumption_Battery)
          - "TOTAL_POWER": Der berechnete Gesamtverbrauch (total_consumption)
        """
        if power_type == "PV_POWER":
            pv = self.final_data.get("PV_POWER", 0)
            return pv

        elif power_type == "AC_GRID_POWER":
            return self.final_data.get("AC_GRID_POWER", 0)

        elif power_type == "AC_POWER":
            return self.final_data.get("AC_POWER", 0)

        elif power_type == "BATTERY_POWER":
            return self.final_data.get("DC_POWER", 0)

        elif power_type == "TOTAL_POWER":
            return self.total_loss

        elif power_type == "EFFICIENCY":
            return self.final_data.get("EFFICIENCY", 0)

        elif power_type == "SOC":
            soc = self.final_data.get("SOC", 0)
            return soc


        else:
            return None


class PowerConsumptionBase:
    def __init__(self, interval_duration=5):
        self.handler = PowerDataHandler()
        self.interval_duration = interval_duration
        self.stop_event = threading.Event()
        self.ws_server = None
        self.logger = CustomLogger()
        self.statsmanager = StatsManager()
        self.running = False
        self.last_minute = None
        self.last_value = None  # Last power value in watts
        self.last_grid_value = None
        self.last_dc_value = 0
        self.last_time = None   # Last timestamp (seconds since epoch)
        self.current_price = 0

        self.hourly_wh = 0          # Consumption for the current hour in kWh
        self.hour_grid_wh = 0
        self.energy_costs_by_hour = {}
        self.energy_costs_by_day = {}    # ISO-date-keyed: "2026-04-27" -> €
        self.consumption_wh_by_day = {}  # ISO-date-keyed daily totals (Wh)
        self.grid_wh_by_day = {}
        self.grid_export_wh_by_day = {}
        self.pv_wh_by_day = {}
        self.battery_charge_wh_by_day = {}
        self.battery_discharge_wh_by_day = {}
        self.loss_wh_by_day = {}
        self.imbalance_wh_by_day = {}
        self.hourly_wh_by_day = {}  # ISO_date -> [24] hourly Wh array
        self.hourly_start_time = time.time()  # Start time of the current hour

        # Daily totals (Wh, in-RAM running sums; persisted across restarts).
        self.daily_wh = 0           # House consumption
        self.daily_grid_wh = 0      # Grid import only (positive flow)
        self.daily_grid_export_wh = 0   # Grid export only (negative flow)
        self.daily_pv_wh = 0        # PV production
        # Battery split. Convention: BATTERY_POWER > 0 = charging (energy
        # into the battery), BATTERY_POWER < 0 = discharging. Matches
        # Victron's signs and the existing process_data() interpretation.
        # Both totals are stored as positive Wh -- it's nicer to read
        # "1234 Wh discharged" than "-1234".
        self.daily_battery_charge_wh = 0
        self.daily_battery_discharge_wh = 0
        # Diagnostic accumulators for energy-balance integrity.
        # daily_loss_wh:  integrated max(input - usable, 0). Same
        #     "Loss" definition that process_data() shows as a single
        #     instantaneous number, but accumulated over the day.
        # daily_imbalance_wh: integrated (input - usable) WITHOUT the
        #     max(...,0) clamp. Negative values mean "more energy went
        #     to sinks than came from known sources" -- a sign that a
        #     sensor or our interpretation of it is missing energy.
        # Both are sanity-check fields that get rendered in the stats
        # tiles; they don't drive any control decisions.
        self.daily_loss_wh = 0
        self.daily_imbalance_wh = 0
        # Per-hour Wh breakdown for today (key "0".."23"). Reset on
        # day-rollover. Lets the stats UI show in WHICH hour a negative
        # imbalance accumulates -- nights with no PV vs days with PV
        # tend to have very different signs.
        self.loss_wh_by_hour_today = {}
        self.imbalance_wh_by_hour_today = {}
        self.current_hour = time.localtime(time.time()).tm_hour
        self.current_day = time.localtime(time.time()).tm_yday
        self.curent_year = time.localtime(time.time()).tm_year

        # Initialized variables
        self.P_DC_consumption_Battery = None
        self.P_DC_inverter_Charger = None
        self.P_AC_consumption_L1 = self.P_AC_consumption_L2 = self.P_AC_consumption_L3 = None
        self.G_AC_consumption_L1 = self.G_AC_consumption_L2 = self.G_AC_consumption_L3 = None
        self.number_of_phases = 3  # Default number of phases, adjust if needed
        self.number_of_grid_phases = 3  # Default number of phases, adjust if needed
        self.current_power = 0
        self.current_grid_power = 0
        # Last-seen instantaneous values for new daily accumulators.
        # update() multiplies these by dt to integrate Wh.
        self.last_pv_value = 0
        self.last_battery_value = 0
        self.soc = None

        self.data_file = "consumption_data.json"
        self.load_data()

        self.thread = None
        self.average = (0,0)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
            self.logger.log.debug(f"{self.__class__.__name__} started with interval {self.interval_duration} minutes.")
        else:
            self.logger.log.debug(f"{self.__class__.__name__} is already running.")

    def stop(self):
        """Stop the running thread."""
        self.save_data(True)
        self.stop_event.set()  # Set the stop flag to end the run loop
        if self.thread:
            self.thread.join()  # Wait for the main thread to finish



    def run(self):
        """Main process - Implementation in derived classes."""
        raise NotImplementedError("This method must be implemented in the derived class.")

    def set_ws_server(self, ws):
        self.ws_server = ws

    def set_current_price(self, current_price):
        self.current_price = current_price

    @staticmethod
    def _today_iso():
        """Today's local date as ISO string (YYYY-MM-DD)."""
        return date.today().isoformat()

    @staticmethod
    def _migrate_yday_to_iso(d, year=None):
        """
        Bring a `*_by_day` dict to the current ISO-date scheme.

        Older builds keyed these dicts by `tm_yday` (e.g. "117" for
        April 27 in a non-leap year). We now key them by ISO date
        ("2026-04-27"). On load we walk the dict and:

          * pass ISO-date keys through unchanged (10 chars, 2 dashes)
          * convert numeric / numeric-string keys 1..366 to an ISO
            date in the given year (defaults to today's year, which
            is the assumption that fits the user's situation -- legacy
            yday data was accumulated within the current calendar year)
          * drop garbage keys

        This is intentionally a one-way migration: once an entry is
        rewritten with an ISO key, save_data() persists it that way
        and subsequent loads see only ISO keys. There's no harm
        running the migrator on already-migrated data; it just becomes
        a no-op pass-through.
        """
        if not isinstance(d, dict):
            return {}
        if year is None:
            year = date.today().year
        days_in_year = 366 if calendar.isleap(year) else 365

        out = {}
        for k, v in d.items():
            sk = str(k)
            # Already ISO -> passthrough
            if len(sk) == 10 and sk.count("-") == 2:
                out[sk] = v
                continue
            # yday key -> convert
            try:
                yday = int(sk)
            except (TypeError, ValueError):
                # garbage key, drop
                continue
            if not (1 <= yday <= 366):
                continue
            yday = min(yday, days_in_year)
            iso = (date(year, 1, 1) + timedelta(days=yday - 1)).isoformat()
            # If both an ISO and a yday entry existed for the same day,
            # the ISO one wins (it's the newer scheme; treat it as
            # authoritative).
            if iso not in out:
                out[iso] = v
        return out

    def load_data(self):
        self.daily_wh = self.statsmanager.get_data("powerconsumption", "daily_wh") or 0.0
        self.daily_grid_wh = self.statsmanager.get_data("powerconsumption", "daily_grid_wh") or 0.0
        self.daily_grid_export_wh = self.statsmanager.get_data(
            "powerconsumption", "daily_grid_export_wh") or 0.0
        self.daily_pv_wh = self.statsmanager.get_data("powerconsumption", "daily_pv_wh") or 0.0

        # Battery split. New keys; if missing on first run after upgrade
        # we just start at zero. (Earlier code split a legacy
        # `daily_battery_throughput_wh` 50/50 into the two new daily
        # counters, but that's a daily total -- inheriting yesterday's
        # leftover throughput as today's starting balance is misleading.
        # The history-dict migration in load_data() handles past days
        # separately, which is the right place for it.)
        self.daily_battery_charge_wh = self.statsmanager.get_data(
            "powerconsumption", "daily_battery_charge_wh") or 0.0
        self.daily_battery_discharge_wh = self.statsmanager.get_data(
            "powerconsumption", "daily_battery_discharge_wh") or 0.0
        self.daily_loss_wh = self.statsmanager.get_data(
            "powerconsumption", "daily_loss_wh") or 0.0
        self.daily_imbalance_wh = self.statsmanager.get_data(
            "powerconsumption", "daily_imbalance_wh") or 0.0
        self.loss_wh_by_hour_today = self.statsmanager.get_data(
            "powerconsumption", "loss_wh_by_hour_today") or {}
        self.imbalance_wh_by_hour_today = self.statsmanager.get_data(
            "powerconsumption", "imbalance_wh_by_hour_today") or {}

        # JSON serialisation collapses Python tuples to lists, so on
        # reload `isinstance(x, tuple)` is always False -- the previous
        # check defaulted everything back to zero on every restart and
        # silently lost daily_wh, hourly averages, last_value, and the
        # hour start time. Accept both tuple and list as the persisted
        # shape.
        def _as_pair(v, fallback):
            if isinstance(v, (tuple, list)) and len(v) == 2:
                return tuple(v)
            return fallback

        hourly_wh_list = self.statsmanager.get_data("powerconsumption", "hourly_wh")
        self.hourly_wh, self.hourly_start_time = _as_pair(hourly_wh_list, (0, time.time()))

        average_list = self.statsmanager.get_data("powerconsumption", "average")
        self.average = _as_pair(average_list, (0, 0))

        last_value_list = self.statsmanager.get_data("powerconsumption", "last_power_value")
        last_grid_value_list = self.statsmanager.get_data("powerconsumption", "last_grid_power_value")
        # Persist last_pv_value and last_battery_value too (they were
        # only loaded as 0 on init before, which made the very first
        # post-restart tick of the energy-balance accumulator compute
        # `input = 0 + grid_import + 0` while `usable` already had the
        # real AC + grid_export -- producing a several-hundred-Wh
        # phantom imbalance on every restart. With these persisted,
        # the first tick has consistent inputs OR is short-circuited
        # by the pause-clamp above.
        last_pv_value_list = self.statsmanager.get_data("powerconsumption", "last_pv_power_value")
        last_battery_value_list = self.statsmanager.get_data("powerconsumption", "last_battery_power_value")

        self.last_value, self.last_time = _as_pair(last_value_list, (0, time.time()))
        self.last_grid_value, _ = _as_pair(last_grid_value_list, (0, time.time()))
        self.last_pv_value, _ = _as_pair(last_pv_value_list, (0, time.time()))
        self.last_battery_value, _ = _as_pair(last_battery_value_list, (0, time.time()))

        energy_costs_by_hour = self.statsmanager.get_data("powerconsumption", "energy_costs_by_hour")

        # All `*_by_day` dicts are now keyed by ISO-date. Earlier builds
        # used tm_yday integers, which silently overwrote across years.
        # The migrator converts legacy yday keys into ISO dates assuming
        # the current calendar year -- per discussion with the user,
        # legacy data from previous years is acceptable to lose, but
        # current-year data should be preserved. Already-ISO keys pass
        # through unchanged so it's safe to run unconditionally.
        raw_costs = self.statsmanager.get_data("powerconsumption", "energy_costs_by_day") or {}
        raw_consumption = self.statsmanager.get_data("powerconsumption", "consumption_wh_by_day") or {}
        raw_grid = self.statsmanager.get_data("powerconsumption", "grid_wh_by_day") or {}
        raw_grid_export = self.statsmanager.get_data("powerconsumption", "grid_export_wh_by_day") or {}
        raw_pv = self.statsmanager.get_data("powerconsumption", "pv_wh_by_day") or {}
        raw_battery_charge = self.statsmanager.get_data("powerconsumption", "battery_charge_wh_by_day") or {}
        raw_battery_discharge = self.statsmanager.get_data("powerconsumption", "battery_discharge_wh_by_day") or {}
        raw_loss = self.statsmanager.get_data("powerconsumption", "loss_wh_by_day") or {}
        raw_imbalance = self.statsmanager.get_data("powerconsumption", "imbalance_wh_by_day") or {}
        # Legacy throughput dict, used as fallback if the new split
        # dicts haven't been populated yet (first load after upgrade).
        raw_battery_throughput = self.statsmanager.get_data("powerconsumption", "battery_throughput_wh_by_day") or {}

        self.energy_costs_by_day = self._migrate_yday_to_iso(raw_costs)
        self.consumption_wh_by_day = self._migrate_yday_to_iso(raw_consumption)
        self.grid_wh_by_day = self._migrate_yday_to_iso(raw_grid)
        self.grid_export_wh_by_day = self._migrate_yday_to_iso(raw_grid_export)
        self.pv_wh_by_day = self._migrate_yday_to_iso(raw_pv)
        self.battery_charge_wh_by_day = self._migrate_yday_to_iso(raw_battery_charge)
        self.battery_discharge_wh_by_day = self._migrate_yday_to_iso(raw_battery_discharge)
        # Loss/imbalance are new fields -- they never had yday-keyed
        # data, so just filter to ISO-keyed entries.
        self.loss_wh_by_day = {
            k: v for k, v in raw_loss.items()
            if isinstance(k, str) and len(k) == 10 and k.count("-") == 2
        }
        self.imbalance_wh_by_day = {
            k: v for k, v in raw_imbalance.items()
            if isinstance(k, str) and len(k) == 10 and k.count("-") == 2
        }
        # If neither split dict has data but the legacy throughput dict
        # does, split each day's value 50/50 as a one-time migration.
        # This is rough but lets the stats page show a sensible
        # historical comparison instead of zeros.
        if not self.battery_charge_wh_by_day and not self.battery_discharge_wh_by_day and raw_battery_throughput:
            legacy = self._migrate_yday_to_iso(raw_battery_throughput)
            for k, v in legacy.items():
                half = round(v / 2.0, 2)
                self.battery_charge_wh_by_day[k] = half
                self.battery_discharge_wh_by_day[k] = half
            self.logger.log.info(
                f"Migrated {len(legacy)} day(s) of legacy battery_throughput "
                "to charge/discharge split (50/50 estimate)."
            )

        # Log a migration summary if any keys were converted (i.e. the
        # raw counts differ from the migrated dict's keys, or any raw
        # key was numeric).
        def _had_yday(raw):
            for k in (raw or {}).keys():
                sk = str(k)
                if not (len(sk) == 10 and sk.count("-") == 2):
                    return True
            return False

        if any(_had_yday(r) for r in [raw_costs, raw_consumption, raw_grid, raw_grid_export, raw_pv, raw_battery_charge, raw_battery_discharge, raw_battery_throughput]):
            self.logger.log.info(
                "Migrated legacy yday-keyed entries in powerconsumption history "
                f"to ISO dates (assumed year {date.today().year})."
            )

        # Per-day hourly arrays. Keys are ISO date strings, values
        # are 24-element lists of Wh per hour. Populated in save_hour().
        # No yday migration here -- yday never had hourly arrays.
        raw_hourly = self.statsmanager.get_data(
            "powerconsumption", "hourly_wh_by_day") or {}
        self.hourly_wh_by_day = {
            k: v for k, v in raw_hourly.items()
            if isinstance(k, str) and len(k) == 10 and k.count("-") == 2
            and isinstance(v, list) and len(v) == 24
        }

        self.logger.log.debug(f"Loaded energy costs by hour: {energy_costs_by_hour}")
        self.logger.log.debug(f"Loaded energy_costs_by_day (post-migration): {self.energy_costs_by_day}")
        self.logger.log.debug(f"Loaded consumption_wh_by_day: {self.consumption_wh_by_day}")
        self.logger.log.debug(f"Loaded grid_wh_by_day: {self.grid_wh_by_day}")
        self.logger.log.debug(f"Loaded pv_wh_by_day: {self.pv_wh_by_day}")
        self.logger.log.debug(
            f"Loaded battery_charge_wh_by_day: {self.battery_charge_wh_by_day}")
        self.logger.log.debug(
            f"Loaded battery_discharge_wh_by_day: {self.battery_discharge_wh_by_day}")

        self.energy_costs_by_hour = energy_costs_by_hour if energy_costs_by_hour else {}
        current_hour_grid_wh = self.statsmanager.get_data("powerconsumption", "current_hour_grid_wh")
        if current_hour_grid_wh and current_hour_grid_wh[1] == self.current_hour:
            self.hour_grid_wh = current_hour_grid_wh[0]
        else:
            self.statsmanager.remove_data("powerconsumption", "current_hourly_grid_wh")

    def save_data(self, logging=False):
        self.statsmanager.set_status_data("powerconsumption","energy_costs_by_hour", self.energy_costs_by_hour, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","energy_costs_by_day", self.energy_costs_by_day, save_data=False)
        # New per-day history dicts.
        self.statsmanager.set_status_data("powerconsumption","consumption_wh_by_day", self.consumption_wh_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","grid_wh_by_day", self.grid_wh_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","grid_export_wh_by_day", self.grid_export_wh_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","pv_wh_by_day", self.pv_wh_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","battery_charge_wh_by_day", self.battery_charge_wh_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","battery_discharge_wh_by_day", self.battery_discharge_wh_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","loss_wh_by_day", self.loss_wh_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","imbalance_wh_by_day", self.imbalance_wh_by_day, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","hourly_wh", (self.hourly_wh, self.hourly_start_time), save_data=False)
        self.statsmanager.update_percent_status_data("powerconsumption","average", self.average, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","last_power_value", (self.last_value, self.last_time), save_data=False)
        self.statsmanager.set_status_data("powerconsumption","last_grid_power_value", (self.last_grid_value, self.last_time))
        self.statsmanager.set_status_data("powerconsumption","last_pv_power_value", (self.last_pv_value, self.last_time), save_data=False)
        self.statsmanager.set_status_data("powerconsumption","last_battery_power_value", (self.last_battery_value, self.last_time), save_data=False)
        self.statsmanager.set_status_data("powerconsumption","current_hour_grid_wh", (self.hour_grid_wh, self.current_hour))
        # New running daily totals -- persisted alongside daily_wh so a
        # restart mid-day doesn't lose the day's accumulated values.
        self.statsmanager.set_status_data("powerconsumption","daily_grid_wh", self.daily_grid_wh, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","daily_grid_export_wh", self.daily_grid_export_wh, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","daily_pv_wh", self.daily_pv_wh, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","daily_battery_charge_wh", self.daily_battery_charge_wh, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","daily_battery_discharge_wh", self.daily_battery_discharge_wh, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","daily_loss_wh", self.daily_loss_wh, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","daily_imbalance_wh", self.daily_imbalance_wh, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","loss_wh_by_hour_today", self.loss_wh_by_hour_today, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","imbalance_wh_by_hour_today", self.imbalance_wh_by_hour_today, save_data=False)

        if logging:
            self.logger.log.debug("data saved.")

    def save_hour(self):
        """Speichert den Durchschnitt des aktuellen Stundenverbrauchs."""
        elapsed_time = (self.last_time - self.hourly_start_time) / 3600  # Zeit in Stunden
        value, count = self.average
        value *= count
        if elapsed_time > 0:
            avg_wh = self.hourly_wh / elapsed_time
            value += avg_wh
            count += 1
            value /= count
            self.average = (value, count)

        # Persist the just-finished hour's Wh value into a per-day
        # 24-slot array. Used by the stats page charts later.
        # Structure: hourly_wh_by_day[ISO_date] = [h0, h1, ..., h23].
        # Called from update() BEFORE current_hour is rotated, so
        # self.current_hour is still the hour we're closing out.
        try:
            today_iso = self._today_iso()
            day_arr = self.hourly_wh_by_day.get(today_iso)
            if not isinstance(day_arr, list) or len(day_arr) != 24:
                day_arr = [0] * 24
            hour_idx = max(0, min(23, int(self.current_hour)))
            day_arr[hour_idx] = round(self.hourly_wh, 2)
            self.hourly_wh_by_day[today_iso] = day_arr
        except Exception as e:
            self.logger.log.debug(f"hourly_wh_by_day update failed: {e}")

        self.statsmanager.update_percent_status_data("powerconsumption", "average", self.average, save_data=False)
        self.logger.log.debug(f"save ... update average: {self.average}")
        self.statsmanager.update_percent_status_data("powerconsumption", "hourly_watt_average", value, save_data=False)
        self.statsmanager.update_percent_status_data("powerconsumption", "daily_watt_average", self.get_daily_average(), save_data=False)
        self.statsmanager.set_status_data("powerconsumption","daily_wh", self.daily_wh, save_data=False)
        self.statsmanager.set_status_data("powerconsumption","hourly_wh_by_day", self.hourly_wh_by_day, save_data=False)

        # Speichert die Daten
        self.save_data()

    def save_day(self):
        """
        Called from update() when the calendar day rolls over. The
        day-rotation in update() happens AFTER this returns, so when
        we're called the running totals (daily_wh, daily_grid_wh,
        daily_grid_export_wh, daily_pv_wh, daily_battery_charge_wh,
        daily_battery_discharge_wh) still hold the
        just-finished day's values. We close them out here:

          1. Update the daily_watt_average EWMA.
          2. Compute the just-finished day's ISO date (yesterday from
             the system clock's perspective at the moment of crossover).
          3. Roll the four running daily totals plus total cost into
             their respective `*_by_day` history dicts under that key.
          4. Persist via save_data().

        Reset of the running totals (daily_wh, daily_grid_wh, ...) is
        done by update() right after we return -- we keep that
        responsibility split because the existing code already structured
        it that way.
        """
        self.statsmanager.update_percent_status_data(
            "powerconsumption", "daily_watt_average", self.get_daily_average(), save_data=False)

        # The day boundary was just crossed by update(); subtract one
        # day from "now" to get the date we're closing out. (Using
        # date.today() at exactly midnight could land on either side
        # depending on scheduling; subtracting one day is unambiguous
        # because update() only enters this branch AFTER tm_yday changed.)
        yesterday_iso = (date.today() - timedelta(days=1)).isoformat()

        total_cost = sum(self.energy_costs_by_hour.values())
        self.energy_costs_by_day[yesterday_iso] = round(total_cost, 4)
        self.consumption_wh_by_day[yesterday_iso] = round(self.daily_wh, 2)
        self.grid_wh_by_day[yesterday_iso] = round(self.daily_grid_wh, 2)
        self.grid_export_wh_by_day[yesterday_iso] = round(self.daily_grid_export_wh, 2)
        self.pv_wh_by_day[yesterday_iso] = round(self.daily_pv_wh, 2)
        self.battery_charge_wh_by_day[yesterday_iso] = round(self.daily_battery_charge_wh, 2)
        self.battery_discharge_wh_by_day[yesterday_iso] = round(self.daily_battery_discharge_wh, 2)
        self.loss_wh_by_day[yesterday_iso] = round(self.daily_loss_wh, 2)
        self.imbalance_wh_by_day[yesterday_iso] = round(self.daily_imbalance_wh, 2)

        # Reset the per-hour cost bucket for the new day.
        self.energy_costs_by_hour = {}

        # Trim history dicts to the configured retention window. We do
        # this once per day right after the rotation so old entries
        # fall off gradually rather than all at once on a config change.
        self._prune_history()

        # Persist all of the above (save_data writes the history dicts
        # plus the running totals; daily_wh/daily_grid_wh/etc are reset
        # to 0 by update() right after we return).
        self.save_data()

    def _prune_history(self):
        """
        Drop ISO-date entries from all per-day history dicts that are
        older than `stats_history_retention_days`. Retention=0 disables
        pruning entirely.
        """
        try:
            from core.config import Config
            cfg = Config()
            retention = int(getattr(cfg, "stats_history_retention_days", 400) or 0)
        except Exception:
            retention = 400

        if retention <= 0:
            return

        from datetime import date as _date, timedelta as _td
        cutoff = (_date.today() - _td(days=retention)).isoformat()

        history_dicts = [
            self.energy_costs_by_day,
            self.consumption_wh_by_day,
            self.grid_wh_by_day,
            self.grid_export_wh_by_day,
            self.pv_wh_by_day,
            self.battery_charge_wh_by_day,
            self.battery_discharge_wh_by_day,
            self.hourly_wh_by_day,
            self.loss_wh_by_day,
            self.imbalance_wh_by_day,
        ]
        dropped = 0
        for d in history_dicts:
            old_keys = [k for k in d.keys() if isinstance(k, str) and k < cutoff]
            for k in old_keys:
                del d[k]
                dropped += 1
        if dropped:
            self.logger.log.info(
                f"Pruned {dropped} history entries older than {cutoff} "
                f"(retention={retention} days)."
            )

    def update(self, power, grid_power, battery_power, timestamp,
               pv_power=0):
        """
        Aktualisiert den Verbrauch basierend auf neuer Leistung und Zeit.

        Parameters
        ----------
        power : W
            Aggregated AC house consumption.
        grid_power : W
            Grid power; positive = import, negative = export.
        battery_power : W
            DC battery power. Victron convention: positive = charging
            (energy into the pack), negative = discharging. The split
            accumulators rely on this; the live UI also uses the signed
            value as-is. If your hardware shows the opposite signs,
            check the shunt wiring (Victron's manual covers the fix).
        timestamp : float
            Seconds since epoch (time.time()).
        pv_power : W, optional
            Solar production. Defaults to 0 so callers that don't yet
            wire it through (or whose MQTT setup has no PV topic) keep
            working without breaking.
        """
        # Setze den Startwert, wenn es die erste Messung ist
        if self.last_time is None:
            self.last_value = power
            self.last_grid_value = grid_power
            self.last_pv_value = pv_power or 0
            self.last_battery_value = battery_power or 0
            self.last_time = timestamp
            self.current_hour = time.localtime(timestamp).tm_hour
            self.current_day = time.localtime(timestamp).tm_yday
            self.hourly_start_time = timestamp
            return

        # Berechne das Zeitintervall in Stunden
        time_diff = (timestamp - self.last_time) / 3600  # Zeitdifferenz in Stunden

        # Guard against restart / pause artefacts. `last_time` is
        # persisted across SEUSS restarts, so the first tick after a
        # multi-hour pause computes time_diff = (now - hours_ago).
        # Multiplying that against the *current* power readings would
        # invent thousands of Wh of fake energy in a single tick --
        # most visibly in `daily_imbalance_wh`, where `last_pv_value`
        # and `last_battery_value` are NOT persisted (they default to
        # 0 on init), while `last_value` and `last_grid_value` ARE,
        # so the balance equation is fundamentally inconsistent for
        # the first tick. Real intervals here are seconds, so anything
        # over 60 seconds is a startup or a connection hiccup, not a
        # real measurement gap. Refresh the baseline and skip
        # integration for this tick.
        if time_diff > (60.0 / 3600.0):
            self.logger.log.info(
                f"Skipping integration for first tick after pause "
                f"(gap={time_diff*3600:.0f}s); resetting baseline."
            )
            self.last_value = power
            self.last_grid_value = grid_power
            self.last_pv_value = pv_power or 0
            self.last_battery_value = battery_power or 0
            self.last_time = timestamp
            return

        # Berechne den Wh-Verbrauch für diesen Zeitraum
        wh = (self.last_value * time_diff)
        self.hourly_wh += wh  # Addiere zum aktuellen Stundenverbrauch
        self.daily_wh += wh   # Update des täglichen Verbrauchs

        grid_wh = (self.last_grid_value * time_diff)
        if grid_wh > 0.0:
            self.hour_grid_wh += grid_wh  # Addiere zum aktuellen Stundenverbrauch
            self.daily_grid_wh += grid_wh   # Update des täglichen Verbrauchs
        elif grid_wh < 0.0:
            # Negative grid power = export to grid. Track as positive Wh
            # (it's nicer to read "1234 Wh exported" than "-1234").
            self.daily_grid_export_wh += -grid_wh

        # PV: positive only -- a negative reading would be a sensor
        # glitch, not real reverse flow.
        pv_wh = max(self.last_pv_value, 0) * time_diff
        self.daily_pv_wh += pv_wh

        # Battery split. Victron convention: positive battery_power =
        # charging (energy into the pack), negative = discharging. Both
        # daily totals stored as positive Wh.
        battery_dt_wh = self.last_battery_value * time_diff
        if battery_dt_wh > 0:
            self.daily_battery_charge_wh += battery_dt_wh
        elif battery_dt_wh < 0:
            self.daily_battery_discharge_wh += -battery_dt_wh

        # Diagnostic energy-balance integration (sanity-check fields).
        # Same definition of input/usable as process_data() uses, but
        # integrated over the timestep:
        #   energy_input  = battery discharge (positive) + grid import
        #                   + PV
        #   usable_energy = AC consumption + grid export + battery charge
        # If sensors and convention are correct, input ≈ usable + losses,
        # so (input - usable) is non-negative and equals the inverter /
        # wiring losses. A negative value means we record more
        # consumption than known sources can supply, which points at a
        # missing source or a sign-convention bug rather than at real
        # losses.
        grid_p = self.last_grid_value or 0
        battery_p = self.last_battery_value or 0
        pv_p = self.last_pv_value or 0
        ac_p = self.last_value or 0
        input_p = (-min(battery_p, 0)) + max(grid_p, 0) + pv_p
        usable_p = ac_p + (-min(grid_p, 0)) + max(battery_p, 0)
        delta_wh = (input_p - usable_p) * time_diff
        self.daily_loss_wh += max(delta_wh, 0)
        self.daily_imbalance_wh += delta_wh
        # Per-hour breakdown so we can spot WHEN the balance goes
        # negative -- the daily total alone hides night-vs-day patterns.
        # Keys are hour strings "0".."23"; values are running Wh for the
        # current day. They reset together with the daily totals at
        # day-rollover. Stored separately from daily_*_wh so the stats
        # UI can render a 24-hour breakdown table.
        hkey = str(self.current_hour)
        self.loss_wh_by_hour_today[hkey] = self.loss_wh_by_hour_today.get(hkey, 0) + max(delta_wh, 0)
        self.imbalance_wh_by_hour_today[hkey] = self.imbalance_wh_by_hour_today.get(hkey, 0) + delta_wh
        self.logger.log.debug(
            f"Power balance tick: AC={ac_p:.0f}W grid={grid_p:.0f}W "
            f"battery={battery_p:.0f}W PV={pv_p:.0f}W -> input={input_p:.0f}W "
            f"usable={usable_p:.0f}W delta={input_p-usable_p:+.0f}W "
            f"({delta_wh:+.2f}Wh in {time_diff*3600:.0f}s); "
            f"daily_loss={self.daily_loss_wh:.0f}Wh "
            f"imbalance={self.daily_imbalance_wh:+.0f}Wh "
            f"hour_imbalance={self.imbalance_wh_by_hour_today.get(hkey, 0):+.1f}Wh"
        )

        self.energy_costs_by_hour[str(self.current_hour)] = (self.hour_grid_wh / 1000) * float(self.current_price)

        # Mirror today's running totals into the per-day history dicts
        # so the stats page can render "today" without waiting for the
        # day boundary. These keys overwrite each tick which is fine --
        # the values just walk up over the day, then save_day() seals
        # them with the final values.
        today_iso = self._today_iso()
        self.consumption_wh_by_day[today_iso] = round(self.daily_wh, 2)
        self.grid_wh_by_day[today_iso] = round(self.daily_grid_wh, 2)
        self.grid_export_wh_by_day[today_iso] = round(self.daily_grid_export_wh, 2)
        self.pv_wh_by_day[today_iso] = round(self.daily_pv_wh, 2)
        self.battery_charge_wh_by_day[today_iso] = round(self.daily_battery_charge_wh, 2)
        self.battery_discharge_wh_by_day[today_iso] = round(self.daily_battery_discharge_wh, 2)
        self.loss_wh_by_day[today_iso] = round(self.daily_loss_wh, 2)
        self.imbalance_wh_by_day[today_iso] = round(self.daily_imbalance_wh, 2)
        self.energy_costs_by_day[today_iso] = round(sum(self.energy_costs_by_hour.values()), 4)

        # Bestimme aktuelle Stunde und Tag
        current_hour = time.localtime(timestamp).tm_hour
        current_day = time.localtime(timestamp).tm_yday

        # Überprüfe, ob ein neuer Tag begonnen hat
        if current_day != self.current_day:
            self.save_day()  # Speichere den täglichen Verbrauch
            self.current_day = current_day
            # Reset all four daily running totals. Note that
            # daily_grid_wh used to NOT be reset here -- a bug that
            # caused it to grow unbounded across days. Fixed now.
            self.daily_wh = 0
            self.daily_grid_wh = 0
            self.daily_grid_export_wh = 0
            self.daily_pv_wh = 0
            self.daily_battery_charge_wh = 0
            self.daily_battery_discharge_wh = 0
            self.daily_loss_wh = 0
            self.daily_imbalance_wh = 0
            self.loss_wh_by_hour_today = {}
            self.imbalance_wh_by_hour_today = {}

            # Seed the new day's slot in the history dicts to 0
            # immediately. Otherwise the running update() block above
            # only refreshes the today-slot when MQTT data arrives,
            # which can be several minutes -- during that window the
            # stats page would show yesterday's final value as today.
            today_iso_new = self._today_iso()
            self.consumption_wh_by_day[today_iso_new] = 0
            self.grid_wh_by_day[today_iso_new] = 0
            self.grid_export_wh_by_day[today_iso_new] = 0
            self.pv_wh_by_day[today_iso_new] = 0
            self.battery_charge_wh_by_day[today_iso_new] = 0
            self.battery_discharge_wh_by_day[today_iso_new] = 0
            self.energy_costs_by_day[today_iso_new] = 0
            # And persist immediately so a restart in the first few
            # minutes of the new day doesn't restore yesterday's slot.
            self.save_data()

        # Überprüfe, ob eine neue Stunde begonnen hat
        if current_hour != self.current_hour:
            self.save_hour()  # Speichere den Durchschnitt für die letzte Stunde
            self.current_hour = current_hour
            self.hourly_wh = 0  # Setze den stündlichen Verbrauch zurück
            self.hourly_start_time = timestamp
            self.hour_grid_wh = 0

        # Speichern der Daten alle 5 Minuten
        current_minute = time.localtime(timestamp).tm_min
        if current_minute in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55] and current_minute != self.last_minute:
            self.save_data()
            self.last_minute = current_minute

        # Aktualisieren der letzten Werte
        self.last_value = power
        self.last_grid_value = grid_power
        self.last_pv_value = pv_power or 0
        self.last_battery_value = battery_power or 0
        self.last_dc_value = self.P_DC_consumption_Battery
        self.last_time = timestamp

    def get_hourly_average(self):
        """Calculates the projected hourly average."""
        elapsed_time_in_hours = (self.last_time - self.hourly_start_time) / 3600  # Elapsed time in hours
        if elapsed_time_in_hours > 0:
            # Project the hourly average based on the time already passed
            projected_wh = self.hourly_wh / elapsed_time_in_hours
            return projected_wh
        return 0

    def get_daily_average(self):
        total_duration_minutes, _ = self.get_minutes_since_until__midnight()
        if total_duration_minutes > 0:
            consumption_per_minute = self.daily_wh / total_duration_minutes
            projected_consumption_wh = consumption_per_minute * 1440
            return projected_consumption_wh / 24

        return 0

    def get_daily_wh(self):
        """Returns the current daily consumption in Wh."""
        return self.daily_wh

    def get_daily_grid_wh(self):
        """Returns the current daily grid import in Wh (positive flow only)."""
        return self.daily_grid_wh

    def get_daily_grid_export_wh(self):
        """Returns the current daily grid export in Wh (positive value, accumulated from negative flow)."""
        return self.daily_grid_export_wh

    def get_daily_pv_wh(self):
        """Returns the current daily PV production in Wh."""
        return self.daily_pv_wh

    def get_daily_battery_charge_wh(self):
        """Returns Wh that went INTO the battery today (sum of positive battery_power × dt)."""
        return self.daily_battery_charge_wh

    def get_daily_battery_discharge_wh(self):
        """Returns Wh that came OUT of the battery today (sum of |negative battery_power| × dt)."""
        return self.daily_battery_discharge_wh

    def get_daily_loss_wh(self):
        """Returns the integrated daily energy loss in Wh (input - usable, clamped >= 0)."""
        return self.daily_loss_wh

    def get_daily_imbalance_wh(self):
        """Returns the integrated daily signed imbalance in Wh (input - usable, signed)."""
        return self.daily_imbalance_wh

    def get_hour_grid_wh(self):
        """Returns the current hour's grid import in Wh."""
        return self.hour_grid_wh

    def get_minutes_since_until__midnight(self):
        """Berechnet die vergangenen Minuten seit Mitternacht."""
        now = TimeUtilities.get_now()  # Lokale Zeit holen
        elapsed_minutes = now.hour * 60 + now.minute + now.second / 60  # Umrechnung in Minuten
        remaining_minutes = 1440 - elapsed_minutes  # Verbleibende Minuten bis Mitternacht
        return elapsed_minutes, remaining_minutes

    def reset_data(self):
        """Reset all tracked data to default values."""
        self.hourly_wh = 0
        self.hour_grid_wh = 0
        self.daily_wh = 0
        self.daily_grid_wh = 0
        self.daily_grid_export_wh = 0
        self.daily_pv_wh = 0
        self.daily_battery_charge_wh = 0
        self.daily_battery_discharge_wh = 0
        self.daily_loss_wh = 0
        self.daily_imbalance_wh = 0
        self.loss_wh_by_hour_today = {}
        self.imbalance_wh_by_hour_today = {}
        self.hourly_start_time = time.time()
        self.last_value = 0
        self.last_grid_value = 0
        self.last_pv_value = 0
        self.last_battery_value = 0
        self.last_time = time.time()
        self.current_hour = time.localtime(time.time()).tm_hour
        self.current_day = time.localtime(time.time()).tm_yday
        self.curent_year = time.localtime(time.time()).tm_year

    def get_monthly_cost(self, year, month):
        """
        Sum of grid energy costs for the given calendar month, taken
        from `energy_costs_by_day` which is keyed by ISO-date strings
        ("YYYY-MM-DD").
        """
        days_in_month = calendar.monthrange(year, month)[1]
        total = 0.0
        for day in range(1, days_in_month + 1):
            iso_key = date(year, month, day).isoformat()
            total += self.energy_costs_by_day.get(iso_key, 0)
        return total
