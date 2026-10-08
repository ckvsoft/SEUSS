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
GridDemandTracker: measures the grid-import demand that the Austrian
Leistungspreis (Netzentgelt from ~2027) is billed on -- the highest
15-minute block average per calendar month.

- Fixed 15-minute blocks aligned to the clock (:00/:15/:30/:45). The
  epoch grid coincides with the local grid in Austria because the UTC
  offset (+1/+2 h) is a whole multiple of 15 minutes.
- Powered by the measured grid import (AC_GRID_POWER, positive side
  only -- export samples are 0 here, the demand is billed in
  Entnahmerichtung).
- The monthly peak is monotonic within a month and persisted through
  StatsManager (status.json). A NEW peak is force-saved (the normal
  6-h flush debounce of status.json would lose a fresh peak on a
  power cut).
- The state is read-only: the limiter/peak-shaving lives in the
  SetpointKeeper; this tracker only measures and reports.
"""

import time

from core.log import CustomLogger


class GridDemandTracker:
    BLOCK_S = 900.0          # 15 minutes
    GROUP = "griddemand"

    def __init__(self, statsmanager, logger=None):
        self.statsmanager = statsmanager
        self.logger = logger or CustomLogger()
        self.block_wh = 0.0
        self.block_start_ts = None
        self._last_power = 0.0
        self._last_ts = None
        self.month_key = None
        self.month_peak_w = 0.0
        self._load()

    # ------------------------------------------------------------------
    # Persistence (StatsManager group "griddemand")
    # ------------------------------------------------------------------

    def _load(self):
        try:
            self.month_key = self.statsmanager.get_data(
                self.GROUP, "month_key")
            raw = self.statsmanager.get_data(self.GROUP, "month_peak_w")
            self.month_peak_w = float(raw or 0.0)
        except (TypeError, ValueError):
            self.month_peak_w = 0.0
        current = time.strftime("%Y-%m")
        if self.month_key != current:
            # New month: the demand charge resets with the calendar
            # month, so the peak starts from zero again.
            self.month_key = current
            self.month_peak_w = 0.0
            self._save(force=True)
            self.logger.log.info(
                f"griddemand: new month {current}, demand peak reset.")

    def _save(self, force=False):
        try:
            self.statsmanager.set_status_data(
                self.GROUP, "month_key", self.month_key, save_data=False)
            self.statsmanager.set_status_data(
                self.GROUP, "month_peak_w", self.month_peak_w,
                save_data=False)
            if force:
                self.statsmanager.save_data(force=True)
        except Exception as e:
            self.logger.log.debug(f"griddemand persist failed: {e}")

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def feed(self, power_w, timestamp=None):
        """
        Feed one grid-import sample (W, >= 0; export reads 0). The
        caller supplies the value measured for the interval ENDING at
        `timestamp` -- like the Wh integration in powerconsumption,
        the tracker uses the PREVIOUS sample's value over dt and then
        advances. Gaps > 60 s are a restart/pause, not a measurement:
        the baseline is refreshed instead of inventing energy.
        """
        try:
            power_w = max(0.0, float(power_w))
        except (TypeError, ValueError):
            return
        if timestamp is None:
            timestamp = time.time()

        if self._last_ts is None:
            self._last_power = power_w
            self._last_ts = timestamp
            self.block_start_ts = int(
                timestamp // self.BLOCK_S) * self.BLOCK_S
            self.block_wh = 0.0
            return

        dt = timestamp - self._last_ts
        if dt <= 0.0 or dt > 60.0:
            self._last_power = power_w
            self._last_ts = timestamp
            self.block_start_ts = int(
                timestamp // self.BLOCK_S) * self.BLOCK_S
            self.block_wh = 0.0
            return

        self._accumulate(self._last_power * (dt / 3600.0), timestamp)
        self._last_power = power_w
        self._last_ts = timestamp

    def _accumulate(self, wh, ts):
        block_start = int(ts // self.BLOCK_S) * self.BLOCK_S
        if self.block_start_ts is None:
            self.block_start_ts = block_start
            self.block_wh = 0.0
        # The interval belongs to the OLD block (the sample covers the
        # time since the last feed) -- add it BEFORE closing, so a
        # sample landing exactly on the boundary counts into the block
        # it actually measures.
        self.block_wh += wh
        if block_start != self.block_start_ts:
            self._close_block(block_start)

    def _close_block(self, next_block_start):
        elapsed = next_block_start - (self.block_start_ts or 0.0)
        if elapsed > 0.0:
            avg_w = self.block_wh * 3600.0 / elapsed
            if avg_w > self.month_peak_w:
                self.month_peak_w = round(avg_w, 1)
                self._save(force=True)
                self.logger.log.info(
                    f"griddemand: new month peak {self.month_peak_w:.0f} W "
                    f"({time.strftime('%Y-%m-%d %H:%M')}) "
                    f"in the {elapsed:.0f}s 15-min block.")
        self.block_start_ts = next_block_start
        self.block_wh = 0.0

    # ------------------------------------------------------------------
    # Status (API / web layer)
    # ------------------------------------------------------------------

    def get_status(self, now=None):
        """Live read-only snapshot for the API: the running quarter
        average, seconds left in the quarter, and the monthly peak."""
        now = now or time.time()
        elapsed = 0.0
        if self.block_start_ts is not None:
            elapsed = max(0.0, now - self.block_start_ts)
        quarter_avg = 0.0
        if elapsed > 0.0:
            quarter_avg = self.block_wh * 3600.0 / elapsed
        return {
            "quarter_avg_w": round(quarter_avg, 1),
            "quarter_elapsed_s": int(elapsed),
            "quarter_remaining_s": max(0, int(self.BLOCK_S - elapsed)),
            "month_key": self.month_key,
            "month_peak_w": round(self.month_peak_w, 1),
        }