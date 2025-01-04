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
from decimal import Decimal, getcontext
from datetime import datetime, timedelta, timezone
from core.timeutilities import TimeUtilities
from core.log import CustomLogger


class Item:
    def __init__(self, starttime, endtime, price, potency=14):
        self.starttime = starttime
        self.endtime = endtime - timedelta(seconds=1) if endtime is not None else None
        self.price = self.convert_to_millicents(price, potency)
        self.logger = CustomLogger()

    @staticmethod
    def convert_to_millicents(euro, potency=14):
        try:
            # Ersetzen Sie Kommas durch Punkte
            euro = str(euro).replace(',', '.')

            getcontext().prec = 30

            millicents = int(Decimal(euro) * Decimal(10) ** potency)
            return int(millicents)
        except ValueError:
            print(f"Fehler beim Umrechnen des Preises: {euro}")
            return None

    @staticmethod
    def millicent_to_cent(price):
        potency = 14
        try:
            getcontext().prec = 30

            cent = Decimal(price) / Decimal(10 ** potency)
            return "{:.4f}".format(cent)
        except (TypeError, ValueError):
            print(f"Fehler beim Umrechnen des Preises: {price}")
            return None

    def is_expired(self, check_time=False):
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        now_local = TimeUtilities.convert_utc_to_local(now, False)
        item_local = TimeUtilities.convert_utc_to_local(self.starttime, False)

        if check_time:
            # Vergleiche sowohl Datum als auch Uhrzeit
            expired = item_local < now_local
            self.logger.log_debug(f"Item expired: {expired}, now: {now_local}, item: {item_local}")

        else:
            # Vergleiche nur das Datum
            expired = item_local.date() < now_local.date()
            self.logger.log_debug(f"Item expired: {expired}, now: {now_local.date()}, item: {item_local.date()}")

        return expired

    def get_price(self, convert=True):
        if convert:
            return self.millicent_to_cent(self.price)
        return self.price

    def get_start_datetime(self, localtime=False):
        if localtime:
            return TimeUtilities.convert_utc_to_local(self.starttime)
        return self.starttime

    def get_end_datetime(self, localtime=False):
        if localtime:
            return TimeUtilities.convert_utc_to_local(self.endtime)
        return self.endtime
