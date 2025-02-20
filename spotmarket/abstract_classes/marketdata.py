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
from datetime import datetime, timedelta
from core.log import CustomLogger
import re, operator


class MarketData:
    def __init__(self, **kwargs) -> None:
        self.getdata_start_datetime = None
        self.getdata_end_datetime = None
        self.logger = CustomLogger()
        self.use_second_day = False
        self.fee = kwargs.get("fee", "")

    def load_data(self, use_second_day: bool):
        error_message = "Error: The abstract method 'load_data(self, use_second_day)' must be implemented in your derived class."
        self.logger.log.error(error_message)
        raise NotImplementedError(error_message)

    def _calculate_dates(self, use_second_day=False, as_timestamp=False):
        now = datetime.now()
        if use_second_day:
            yesterday = (now - timedelta(days=1))
            tomorrow = (now + timedelta(days=2))
            self.getdata_start_datetime = yesterday.replace(hour=23, minute=0, second=0, microsecond=0)
            self.getdata_end_datetime = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            self.getdata_start_datetime = now.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = (now + timedelta(days=1))
            self.getdata_end_datetime = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

        self.logger.log.debug(f"use_second_day: {use_second_day}  as_timestamp: {as_timestamp}")
        self.logger.log.debug(f"starttime: {self.getdata_start_datetime}, endtime: {self.getdata_end_datetime}")

        if as_timestamp:
            self.getdata_start_datetime = str(int(self.getdata_start_datetime.timestamp())) + "000"
            self.getdata_end_datetime = str(int(self.getdata_end_datetime.timestamp())) + "000"
            self.logger.log.debug(
                f"starttime: timestamp {self.getdata_start_datetime}, endtime: timestamp {self.getdata_end_datetime}")

    def _calculate_fee(self, base_value):
        if self.fee == "":
            return 0.0

        expr = self.fee.strip()

        try:
            base_value = float(base_value)
        except ValueError:
            self.logger.log.warning(f"Invalid base value: {base_value}, defaulting to 0.0")
            return 0.0

        OPS = {
            "+": operator.add,
            "-": operator.sub,
            "*": operator.mul,
            "/": operator.truediv
        }

        try:
            # Wenn die Fee nur eine Zahl ist (z. B. "2.5" oder "-2.5"), direkt zurückgeben
            if re.match(r"^[+\-]?\s*\d+(\.\d+)?$", expr):
                return float(expr)

            # Prozentwert berechnen, falls vorhanden (z. B. "3% + 2.5")
            percentage_fee = 0.0
            fixed_fee = 0.0

            if "%" in expr:
                percentage_match = re.search(r"([+-]?\d+(\.\d+)?)\s*%", expr)
                if percentage_match:
                    percentage_fee = base_value * (float(percentage_match.group(1)) / 100)
                    expr = expr.replace(percentage_match.group(0), "")  # Prozent-Anteil entfernen

            # Verbleibende Fixwerte berechnen (z. B. "+ 2.5")
            matches = re.findall(r"([\+\-])\s*(\d+\.?\d*)", expr)

            for op, num in matches:
                num = float(num)
                fixed_fee = OPS[op](fixed_fee, num)

            return percentage_fee + fixed_fee

        except Exception as e:
            self.logger.log.warning(f"Warning in calculate_fee: {e}. Returning 0.0. fee: {self.fee}")
            self.logger.log.debug(f"Base Value: {base_value} (Type: {type(base_value)})")
            self.logger.log.debug(f"Fee Expression: {self.fee} (Type: {type(self.fee)})")
            return 0.0
