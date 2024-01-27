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

#tibber.py
import json
from datetime import datetime, timedelta, timezone

import socket
import requests
from requests.exceptions import ConnectionError

from spotmarket.abstract_classes.item import Item
from spotmarket.abstract_classes.marketdata import MarketData


class TibberItem(Item):
    def __init__(self, starts_at, price_unit):
        start_time = datetime.strptime(starts_at, '%Y-%m-%dT%H:%M:%S.%f%z').astimezone(timezone.utc)
        if price_unit is not None:
            super().__init__(start_time, None, price_unit, 15)
        else:
            raise ValueError("Ungültige Tibber-Preisdaten. 'price_unit' muss gesetzt sein.")

    def extend_endtime(self):
        # Verlängere die Endzeit um eine Stunde
        if self.endtime is None:
            extended_endtime = self.starttime + timedelta(hours=1) - timedelta(seconds=1)
            self.endtime = extended_endtime  # .strftime('%Y-%m-%dT%H:%M:%S.%f%z')


class Tibber(MarketData):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.price_unit = kwargs.get("price_unit", "energy")
        self.api_token = kwargs.get("api_token", "")

    def load_data(self, use_second_day):
        try:
            self._calculate_dates(use_second_day)
            self.use_second_day = use_second_day
            url = 'https://api.tibber.com/v1-beta/gql'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_token}'
            }

            query = '{"query":"{viewer{homes{currentSubscription{priceInfo{current{total energy tax startsAt}today{total energy tax startsAt}tomorrow{total energy tax startsAt}}}}}}"}'

            response = requests.post(url, headers=headers, json=json.loads(query))

            if response.status_code == 200:
                # data = response.json()
                return self._load_data_from_json(response.text)
            else:
                self.logger.log_error(f"Error with the API request. Status code: {response.status_code}")

        except ConnectionError as e:
            if isinstance(e.args[0], socket.gaierror):
                self.logger.log_error(f"Error in name resolution for 'api.awattar.com'")
                self.logger.log_error("Please check your network connection and DNS configuration.")
            else:
                self.logger.log_error(f"Connection error: {e}")
                self.logger.log_error("Please check your network connection and server configuration.")

            return []

    def _load_data_from_json(self, json_data):
        items = []
        try:
            data = json.loads(json_data)
            for entry in data.get('data', {}).get('viewer', {}).get('homes', [])[0].get('currentSubscription', {}).get(
                    'priceInfo', {}).get('today', []):
                tibber_item = TibberItem(entry.get('startsAt'), entry.get(self.price_unit))
                tibber_item.extend_endtime()
                items.append(tibber_item)

            if self.use_second_day:
                for entry in data.get('data', {}).get('viewer', {}).get('homes', [])[0].get('currentSubscription',
                                                                                            {}).get(
                    'priceInfo', {}).get('tomorrow', []):
                    tibber_item = TibberItem(entry.get('startsAt'), entry.get(self.price_unit))
                    tibber_item.extend_endtime()
                    items.append(tibber_item)

                if len(items) < 25:
                    self.logger.log_warning("Error: Tibber prices for tomorrow could not be loaded.")

            return items
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.log_warning(f"Error loading all Tibber prices: {e}")

            return items
