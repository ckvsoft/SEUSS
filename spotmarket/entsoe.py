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

# entsoe.py
import re
from datetime import datetime, timedelta, timezone

import socket
import requests
from requests.exceptions import ConnectionError

from spotmarket.abstract_classes.item import Item
from spotmarket.abstract_classes.marketdata import MarketData


class EntsoeItem(Item):
    def __init__(self, start_datetime, end_datetime, price):
        start_time = start_datetime.replace(tzinfo=timezone.utc)  # .astimezone(timezone.utc)
        end_time = end_datetime.replace(tzinfo=timezone.utc)  # .astimezone(timezone.utc)

        super().__init__(start_time, end_time, price, 13)


class Entsoe(MarketData):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_token = kwargs.get("api_token", "")
        self.in_domain = kwargs.get("in_domain", "")
        self.out_domain = kwargs.get("out_domain", "")

    def load_data(self, use_second_day: bool):
        try:
            self.use_second_day = use_second_day
            self._calculate_dates(use_second_day)
            url = self._make_url()
            response = requests.get(url)

            if response.status_code == 200:
                # print(response.text)
                return self._load_data_from_xml(response.text)
            else:
                self.logger.log_warning(f"Error downloading ENTSO-E prices. Status code: {response.status_code}")
                self.logger.log_warning(f"URL: {url}")
                return []

        except ConnectionError as e:
            if isinstance(e.args[0], socket.gaierror):
                self.logger.log_error(f"Error in name resolution for 'api.awattar.com'")
                self.logger.log_error("Please check your network connection and DNS configuration.")
            else:
                self.logger.log_error(f"Connection error: {e}")
                self.logger.log_error("Please check your network connection and server configuration.")

            return []

    def _make_url(self) -> str:
        start_date_str = self.getdata_start_datetime.strftime('%Y%m%d%H00')
        end_date_str = self.getdata_end_datetime.strftime('%Y%m%d%H00')

        url = f"https://web-api.tp.entsoe.eu/api?securityToken={self.api_token}&documentType=A44&in_Domain={self.in_domain}&out_Domain={self.out_domain}&periodStart={start_date_str}&periodEnd={end_date_str}"
        return url

    def _load_data_from_xml(self, xml_data: str):
        error_code = 0
        error_message = ""
        items = []

        lines = xml_data.split('\n')
        capture_period = False
        valid_period = False
        capture_time = False
        in_reason = False

        start_datetime = ""
        pos = 0

        for line in lines:
            if "<Period>" in line:
                capture_period = True
            elif "</Period>" in line:
                capture_period = False
                valid_period = False
            elif capture_period and "<timeInterval>" in line:
                capture_time = True
            elif capture_period and "</timeInterval>" in line:
                capture_time = False
            elif capture_time and "<start>" in line:
                start_datetime = re.search(r'<start>(.*?)<\/start>', line).group(1)
                # start_datetime = TimeUtilities.convert_utc_to_local(start_datetime)
            elif capture_period and "<resolution>PT60M</resolution>" in line:
                valid_period = True
            elif valid_period and "<position>" in line:
                position = re.search(r'<position>(.*?)<\/position>', line)
                if position:
                    pos = int(position.group(1))
                    pos -= 1
            elif valid_period and "<price.amount>" in line:
                price = re.search(r'<price.amount>(.*?)<\/price.amount>', line)
                if price:
                    dt_start = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%MZ") + timedelta(hours=pos)
                    # dt_start = start_datetime + timedelta(hours=pos)
                    dt_end = dt_start + timedelta(hours=1)
                    entsoe_item = EntsoeItem(dt_start, dt_end,
                                             price.group(1))
                    items.append(entsoe_item)
                    if pos == 23 and not self.use_second_day:
                        break
            elif valid_period and "</Period>" in line:
                break

            elif "<Reason>" in line:
                in_reason = True
                error_message = ""
            elif in_reason and "<code>" in line:
                error_code = int(re.search(r'<code>(.*?)<\/code>', line).group(1))
            elif in_reason and "<text>" in line:
                error_message = re.search(r'<text>(.*?)<\/text>', line).group(1)
            elif "</Reason>" in line:
                in_reason = False

        if error_code == 999:
            self.logger.log_warning(f"E: Entsoe data retrieval error found in the XML data: {error_message}")
        elif items is None:
            self.logger.log_warning("E: No prices found in the XML data.")

        return items
