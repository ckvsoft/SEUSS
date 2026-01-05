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

# tibber.py
import json
from datetime import datetime, timedelta, timezone

import socket
import requests
from requests.exceptions import ConnectionError

from core.utils import Utils
from spotmarket.abstract_classes.item import Item
from spotmarket.abstract_classes.marketdata import MarketData


class TibberItem(Item):
    def __init__(self, starts_at, price_unit, fee_str):
        start_time = datetime.strptime(starts_at, '%Y-%m-%dT%H:%M:%S.%f%z').astimezone(timezone.utc)
        if price_unit is not None:
            super().__init__(start_time, None, price_unit, fee_str, 15)
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
        self.use_second_day = False

    def load_data(self, use_second_day):
        self.use_second_day = use_second_day

        url = "https://api.tibber.com/v1-beta/gql"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}"
        }

        query = {
            "query": """
            {
              viewer {
                homes {
                  currentSubscription {
                    priceInfo(resolution: QUARTER_HOURLY) {
                      today { total energy tax startsAt }
                      tomorrow { total energy tax startsAt }
                    }
                  }
                }
              }
            }
            """
        }

        try:
            response = requests.post(url, headers=headers, json=query, timeout=10)
        except ConnectionError as e:
            self.logger.log.error(f"Tibber connection error: {e}")
            return []

        if response.status_code != 200:
            self.logger.log.warning(
                f"Tibber API returned HTTP {response.status_code}: {response.text}"
            )
            return []

        try:
            data = response.json()
        except json.JSONDecodeError:
            self.logger.log.warning("Tibber API returned invalid JSON")
            return []

        homes = (
            data.get("data", {})
                .get("viewer", {})
                .get("homes", [])
        )

        if not homes:
            self.logger.log.warning("Tibber API returned no homes")
            return []

        price_info = (
            homes[0]
            .get("currentSubscription", {})
            .get("priceInfo", {})
        )

        days = ["today", "tomorrow"] if self.use_second_day else ["today"]

        hour_prices = {}
        hour_start_map = {}

        for day in days:
            for entry in price_info.get(day, []):
                try:
                    ts = datetime.strptime(
                        entry["startsAt"], "%Y-%m-%dT%H:%M:%S.%f%z"
                    ).astimezone(timezone.utc)

                    hour_ts = ts.replace(minute=0, second=0, microsecond=0)
                    price = float(entry[self.price_unit])

                    if hour_ts not in hour_prices:
                        hour_prices[hour_ts] = []
                        hour_start_map[hour_ts] = entry["startsAt"]

                    hour_prices[hour_ts].append(price)

                except Exception as e:
                    self.logger.log.warning(
                        f"Tibber entry skipped: {entry} ({e})"
                    )

        items = []

        for hour_ts in sorted(hour_prices.keys()):
            prices = hour_prices[hour_ts]
            if not prices:
                continue

            avg_price = Utils.commercial_round(sum(prices) / len(prices), 3)

            item = TibberItem(
                hour_start_map[hour_ts],
                avg_price,
                self.fee
            )
            item.extend_endtime()
            items.append(item)

        return items
