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


# Quarter length in milliseconds (15 minutes * 60s * 1000ms).
# Awattar timestamps are in milliseconds, so we work in the same unit
# to keep the integer arithmetic obvious.
_QUARTER_MS = 15 * 60 * 1000


class AwattarItem(Item):
    def __init__(self, start_timestamp, end_timestamp, price, fee_str):
        starttime = datetime.fromtimestamp(start_timestamp / 1000).astimezone(timezone.utc)
        endtime = datetime.fromtimestamp(end_timestamp / 1000).astimezone(timezone.utc)
        super().__init__(starttime, endtime, price, fee_str, 13)


class Awattar(MarketData):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._country = kwargs.get("country", "AT")

    def load_data(self, use_second_day):
        try:
            self._calculate_dates(use_second_day, True)
            url = self._make_url()
            # 15s timeout: see entsoe.py for rationale -- without a
            # timeout, a DNS or TCP stall here hangs the main eval
            # loop indefinitely (observed: 23h freeze after the DNS
            # outage on 2026-06-11).
            response = requests.get(url, timeout=15)

            if response.status_code == 200:
                return self._load_data_from_json(response.text)
            else:
                self.logger.log.warning(f"Error downloading Awattar prices. Status code: {response.status_code}")
                return []

        except ConnectionError as e:
            if isinstance(e.args[0], socket.gaierror):
                self.logger.log.error(f"Error in name resolution for 'api.awattar.com'")
                self.logger.log.error("Please check your network connection and DNS configuration.")
            else:
                self.logger.log.error(f"Connection error: {e}")
                self.logger.log.error("Please check your network connection and server configuration.")

            return []

    def _load_data_from_json(self, json_data):
        """
        Parse Awattar JSON and emit 15-minute items.

        Awattar provides hourly prices. To keep the rest of the system
        on a uniform 15-minute resolution (matching ENTSO-E and Tibber),
        we split each hourly entry into 4 identical quarter items.
        The price is the same for all 4 quarters of an Awattar hour,
        because Awattar genuinely has no sub-hour resolution -- so
        splitting carries no information loss.
        """
        try:
            data = json.loads(json_data)
            items = []
            for entry in data.get('data', []):
                current_price = float(entry.get('marketprice'))
                hour_start = int(entry.get('start_timestamp'))
                hour_end = int(entry.get('end_timestamp'))

                # Sanity check: an Awattar entry should be exactly one hour.
                # If a future API change ever delivers something else, we
                # honour the actual span instead of assuming 60 minutes.
                span_ms = hour_end - hour_start
                if span_ms <= 0:
                    self.logger.log.warning(
                        f"Awattar entry with non-positive span skipped: {entry}"
                    )
                    continue

                quarter_count = max(1, span_ms // _QUARTER_MS)
                for q in range(quarter_count):
                    q_start = hour_start + q * _QUARTER_MS
                    q_end = q_start + _QUARTER_MS
                    # Clamp the last quarter to the original entry's end,
                    # in case the entry isn't a clean multiple of 15min.
                    if q == quarter_count - 1:
                        q_end = hour_end
                    items.append(
                        AwattarItem(q_start, q_end, current_price, self.fee)
                    )

            return items
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.log.warning(f"Error loading Awattar prices: {e}")
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
