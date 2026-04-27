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

# item.py
from datetime import datetime, timedelta, timezone
from core.timeutilities import TimeUtilities
from core.log import CustomLogger
from core.utils import Utils

class Item:
    def __init__(self, starttime, endtime, price, fee_str, potency=14):
        self.starttime = starttime
        self.endtime = endtime - timedelta(seconds=1) if endtime is not None else None
        self.price = Utils.convert_to_millicents(price, potency)
        fee = Utils.calculate_fee(self.price, fee_str)
        self.price += fee
        self.logger = CustomLogger()

    def is_expired(self, check_time=False):
        now = datetime.now(timezone.utc)
        now_local = TimeUtilities.convert_utc_to_local(now, False)
        item_local = TimeUtilities.convert_utc_to_local(self.starttime, False)

        if check_time:
            # Compare both date and time
            expired = item_local < now_local
            self.logger.log.debug(f"Item expired: {expired}, now: {now_local}, item: {item_local}")

        else:
            # Compare date only
            expired = item_local.date() < now_local.date()
            self.logger.log.debug(f"Item expired: {expired}, now: {now_local.date()}, item: {item_local.date()}")

        return expired

    def get_price(self, convert=True):
        if convert:
            return Utils.millicent_to_cent(self.price)
        return self.price

    def get_start_datetime(self, localtime=False):
        if localtime:
            return TimeUtilities.convert_utc_to_local(self.starttime)
        return self.starttime

    def get_end_datetime(self, localtime=False):
        if localtime:
            return TimeUtilities.convert_utc_to_local(self.endtime)
        return self.endtime

    # ------------------------------------------------------------------
    # Resolution helpers (added for 15min-resolution support)
    # ------------------------------------------------------------------
    # Item knows its own resolution implicitly via (endtime - starttime).
    # We add +1s back because __init__ subtracts 1s from endtime to get an
    # inclusive end. So a 15min slot from 14:00 to 14:15 is stored as
    # starttime=14:00:00, endtime=14:14:59 -> diff=14:59 -> +1s -> 15min.

    def get_duration_minutes(self):
        """
        Return the slot length in minutes. 15 for quarter-hour items,
        60 for hour items. Returns None if endtime is missing (e.g. an
        un-extended TibberItem before extend_endtime() was called).
        """
        if self.endtime is None or self.starttime is None:
            return None
        delta = self.endtime - self.starttime + timedelta(seconds=1)
        return int(round(delta.total_seconds() / 60))

    def get_quarter_count(self):
        """
        How many 15-minute quarters does this item span?
        15min item -> 1, 60min item -> 4.
        Returns None if duration cannot be determined.
        """
        minutes = self.get_duration_minutes()
        if minutes is None:
            return None
        return max(1, int(round(minutes / 15)))

    def is_quarter_resolution(self):
        """True if this item represents a 15-minute slot."""
        return self.get_duration_minutes() == 15

    def contains(self, when):
        """
        True if `when` (a tz-aware datetime) falls within this item's slot.
        Useful for checking whether a charging block is currently active.
        Both starttime and endtime are normalized to UTC for comparison.
        """
        if self.starttime is None or self.endtime is None:
            return False
        start = self.starttime
        end = self.endtime
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return start <= when <= end
