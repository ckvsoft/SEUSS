#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024 Christian Kvasny chris(at)ckvsoft.at
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


class MarketData:
    def __init__(self, **kwargs) -> None:
        self.getdata_start_datetime = None
        self.getdata_end_datetime = None
        self.logger = CustomLogger()
        self.use_second_day = False

    def load_data(self, use_second_day: bool):
        error_message = "Error: The abstract method 'load_data(self, use_second_day)' must be implemented in your derived class."
        self.logger.log_error(error_message)
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

        self.logger.log_debug(f"use_second_day: {use_second_day}  as_timestamp: {as_timestamp}")
        self.logger.log_debug(f"starttime: {self.getdata_start_datetime}, endtime: {self.getdata_end_datetime}")

        if as_timestamp:
            self.getdata_start_datetime = str(int(self.getdata_start_datetime.timestamp())) + "000"
            self.getdata_end_datetime = str(int(self.getdata_end_datetime.timestamp())) + "000"
            self.logger.log_debug(
                f"starttime: timestamp {self.getdata_start_datetime}, endtime: timestamp {self.getdata_end_datetime}")
