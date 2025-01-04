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

# awattar.py
import json
from datetime import datetime, timezone

import socket
import requests
from requests.exceptions import ConnectionError

from spotmarket.abstract_classes.item import Item
from spotmarket.abstract_classes.marketdata import MarketData


class AwattarItem(Item):
    def __init__(self, start_timestamp, end_timestamp, price):
        starttime = datetime.fromtimestamp(start_timestamp / 1000).astimezone(timezone.utc)
        endtime = datetime.fromtimestamp(end_timestamp / 1000).astimezone(timezone.utc)
        super().__init__(starttime, endtime, price, 13)


class Awattar(MarketData):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._country = kwargs.get("country", "AT")

    def load_data(self, use_second_day):
        try:
            self._calculate_dates(use_second_day, True)
            url = self._make_url()
            response = requests.get(url)

            if response.status_code == 200:
                return self._load_data_from_json(response.text)
            else:
                self.logger.log_warning(f"Error downloading Awattar prices. Status code: {response.status_code}")
                return []

        except ConnectionError as e:
            if isinstance(e.args[0], socket.gaierror):
                self.logger.log_error(f"Error in name resolution for 'api.awattar.com'")
                self.logger.log_error("Please check your network connection and DNS configuration.")
            else:
                self.logger.log_error(f"Connection error: {e}")
                self.logger.log_error("Please check your network connection and server configuration.")

            return []

    def _load_data_from_json(self, json_data):
        try:
            data = json.loads(json_data)
            items = []
            for entry in data.get('data', []):
                awattar_item = AwattarItem(entry.get('start_timestamp'), entry.get('end_timestamp'),
                                           entry.get('marketprice'))
                items.append(awattar_item)
            return items
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.log_warning(f"Error loading Awattar prices: {e}")
            return []

    def _make_url(self) -> str:
        url = ""

        # set params
        params = "?start=" + self.getdata_start_datetime
        params = params + "&end=" + self.getdata_end_datetime

        # build url
        if self._country == "AT":
            url = "https://api.awattar.com/v1/marketdata" + params
        elif self._country == "DE":
            url = "https://api.awattar.de/v1/marketdata" + params

        return url
