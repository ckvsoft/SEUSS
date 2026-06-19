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
from requests.exceptions import ConnectionError, RequestException

from core.utils import Utils
from spotmarket.abstract_classes.item import Item
from spotmarket.abstract_classes.marketdata import MarketData


class TibberItem(Item):
    """
    Tibber emits prices with a startsAt timestamp and no explicit endtime.
    The slot length depends on the GraphQL resolution we requested:
      - QUARTER_HOURLY -> 15 minutes
      - HOURLY         -> 60 minutes
    We pass slot_minutes from the loader so the item knows its endtime
    immediately and downstream code (Item.get_duration_minutes etc.)
    works without an extra extend_endtime() step.
    """

    def __init__(self, starts_at, price_value, fee_str, slot_minutes=15):
        start_time = datetime.strptime(
            starts_at, '%Y-%m-%dT%H:%M:%S.%f%z'
        ).astimezone(timezone.utc)
        if price_value is None:
            raise ValueError("Ungültige Tibber-Preisdaten. 'price_value' muss gesetzt sein.")
        end_time = start_time + timedelta(minutes=slot_minutes)
        super().__init__(start_time, end_time, price_value, fee_str, 15)

    def extend_endtime(self):
        """
        Kept for backward compatibility -- older code may still call this.
        With the new constructor we always have an endtime, so this is a
        no-op unless an item was somehow created without one.
        """
        if self.endtime is None:
            extended_endtime = self.starttime + timedelta(hours=1) - timedelta(seconds=1)
            self.endtime = extended_endtime


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

        # We request QUARTER_HOURLY resolution. Tibber will return either
        # 4 entries per hour (true 15min markets) or 1 entry per hour
        # (markets without sub-hourly data, padded by Tibber). We handle
        # both cases by computing the slot length from the gap between
        # consecutive timestamps.
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
        except RequestException as e:
            # Covers ReadTimeout/SSLError/etc. -- see entsoe.py for full
            # rationale (without this, a network stall kills the eval
            # thread permanently).
            self.logger.log.warning(
                f"Tibber request failed: {type(e).__name__}: {e}. "
                f"Skipping this cycle."
            )
            return []
        except Exception as e:
            self.logger.log.exception(f"Unexpected error calling Tibber: {e}")
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

        # Collect raw entries with parsed timestamps so we can determine
        # the actual resolution returned by Tibber.
        raw_entries = []
        for day in days:
            for entry in price_info.get(day, []):
                try:
                    starts_at_str = entry["startsAt"]
                    ts = datetime.strptime(
                        starts_at_str, "%Y-%m-%dT%H:%M:%S.%f%z"
                    ).astimezone(timezone.utc)
                    price = float(entry[self.price_unit])
                    raw_entries.append((ts, starts_at_str, price))
                except Exception as e:
                    self.logger.log.warning(
                        f"Tibber entry skipped: {entry} ({e})"
                    )

        if not raw_entries:
            return []

        raw_entries.sort(key=lambda x: x[0])

        # Determine slot length from the smallest gap between consecutive
        # timestamps. Tibber typically returns 15 or 60 minute slots.
        # Default to 15 if we can't tell (single entry).
        slot_minutes = 15
        if len(raw_entries) >= 2:
            gaps = []
            for i in range(1, len(raw_entries)):
                gap = (raw_entries[i][0] - raw_entries[i - 1][0]).total_seconds() / 60
                if gap > 0:
                    gaps.append(int(round(gap)))
            if gaps:
                slot_minutes = min(gaps)
                # Snap to known sensible values to absorb tiny timestamp
                # jitter (DST edges, server clock drift).
                if slot_minutes < 15:
                    slot_minutes = 15
                elif 15 < slot_minutes < 60:
                    # Anything between 15 and 60 is unusual; round to the
                    # nearest of 15 or 60.
                    slot_minutes = 15 if slot_minutes <= 30 else 60

        self.logger.log.debug(
            f"Tibber resolution detected: {slot_minutes} minutes "
            f"({len(raw_entries)} entries)"
        )

        items = []
        for ts, starts_at_str, price in raw_entries:
            try:
                if slot_minutes == 60:
                    # Tibber returned hourly data despite QUARTER_HOURLY
                    # request -- happens for markets without 15min prices.
                    # Split into 4 identical quarters so the rest of the
                    # system sees uniform 15-minute resolution.
                    for q in range(4):
                        q_start_dt = ts + timedelta(minutes=q * 15)
                        q_starts_at = q_start_dt.strftime(
                            "%Y-%m-%dT%H:%M:%S.000%z"
                        )
                        # strftime emits +0000 without colon; Tibber uses
                        # +00:00. Insert the colon to keep the format
                        # consistent with what TibberItem expects.
                        if len(q_starts_at) >= 5 and q_starts_at[-5] in "+-" and ":" not in q_starts_at[-5:]:
                            q_starts_at = q_starts_at[:-2] + ":" + q_starts_at[-2:]
                        items.append(
                            TibberItem(q_starts_at, price, self.fee, slot_minutes=15)
                        )
                else:
                    items.append(
                        TibberItem(starts_at_str, price, self.fee, slot_minutes=slot_minutes)
                    )
            except Exception as e:
                self.logger.log.warning(
                    f"Tibber item creation failed for {starts_at_str}: {e}"
                )

        return items
