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

# entsoe.py
import re
from datetime import datetime, timedelta, timezone

import socket
import requests
from requests.exceptions import ConnectionError

from spotmarket.abstract_classes.item import Item
from spotmarket.abstract_classes.marketdata import MarketData
from core.statsmanager import StatsManager


class EntsoeItem(Item):
    def __init__(self, start_datetime, end_datetime, price, fee_str):
        start_time = start_datetime.replace(tzinfo=timezone.utc)  # .astimezone(timezone.utc)
        end_time = end_datetime.replace(tzinfo=timezone.utc)  # .astimezone(timezone.utc)

        super().__init__(start_time, end_time, price, fee_str, 13)


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
                self.logger.log.warning(f"Error downloading ENTSO-E prices. Status code: {response.status_code}")
                self.logger.log.warning(f"URL: {url}")
                return []

        except ConnectionError as e:
            if isinstance(e.args[0], socket.gaierror):
                self.logger.log.error(f"Error in name resolution for 'web-api.tp.entsoe.eu'")
                self.logger.log.error("Please check your network connection and DNS configuration.")
            else:
                self.logger.log.error(f"Connection error: {e}")
                self.logger.log.error("Please check your network connection and server configuration.")

            return []

    def _make_url(self) -> str:
        start_date = self.getdata_start_datetime  # - timedelta(hours=1)
        start_date_str = start_date.strftime('%Y%m%d%H00')
        end_date_str = self.getdata_end_datetime.strftime('%Y%m%d%H00')

        url = f"https://web-api.tp.entsoe.eu/api?securityToken={self.api_token}&documentType=A44&in_Domain={self.in_domain}&out_Domain={self.out_domain}&periodStart={start_date_str}&periodEnd={end_date_str}"
        self.logger.log.debug(f"entsoe url: {url}")
        return url

    def _load_data_from_xml(self, xml_data: str):
        statsmanager = StatsManager()

        items = []
        lines = xml_data.splitlines()

        # Last known quarter-hour price (persisted across restarts)
        last_q_price = statsmanager.get_data('market', 'q_price')
        last_q_price = float(last_q_price) if last_q_price is not None else None

        processed_period_starts = set()

        capture_period = False
        valid_period = False
        capture_time = False

        start_datetime = None
        start_dt = None

        last_pos = 0
        quarter_buffer = []

        for line in lines:

            # ------------------------------------------------------------
            # Period start
            # ------------------------------------------------------------
            if "<Period>" in line:
                capture_period = True
                valid_period = False
                last_pos = 0
                quarter_buffer = []
                continue

            # ------------------------------------------------------------
            # Period end
            # ------------------------------------------------------------
            if "</Period>" in line:
                capture_period = False
                valid_period = False
                continue

            # ------------------------------------------------------------
            # Capture time interval
            # ------------------------------------------------------------
            if capture_period and "<timeInterval>" in line:
                capture_time = True
                continue

            if capture_time and "<start>" in line:
                start_datetime = re.search(r'<start>(.*?)</start>', line).group(1)
                start_dt = datetime.strptime(
                    start_datetime, "%Y-%m-%dT%H:%MZ"
                ).replace(tzinfo=timezone.utc)

                # Skip duplicate periods (ENTSO-E sends them twice)
                if start_dt in processed_period_starts:
                    self.logger.log.debug(
                        f"Duplicate Period detected for {start_dt}, skipping."
                    )
                    valid_period = False
                else:
                    processed_period_starts.add(start_dt)
                    valid_period = True

                continue

            if capture_period and "</timeInterval>" in line:
                capture_time = False
                continue

            # ------------------------------------------------------------
            # Resolution (we only accept PT15)
            # ------------------------------------------------------------
            if capture_period and "<resolution>" in line:
                if "PT15M" in line:
                    valid_period = True
                else:
                    valid_period = False
                continue

            # ------------------------------------------------------------
            # Position handling
            # ------------------------------------------------------------
            if valid_period and "<position>" in line:
                current_pos = int(re.search(r'<position>(.*?)</position>', line).group(1))

                # Fill missing quarter-hour positions immediately
                while last_pos + 1 < current_pos:
                    last_pos += 1

                    if last_q_price is None:
                        self.logger.log.warning(
                            "First quarter price missing, using stored q_price (None)."
                        )
                        break

                    self.logger.log.warning(
                        f"Missing quarter position {last_pos}, "
                        f"using last known price ({last_q_price})."
                    )

                    quarter_buffer.append(last_q_price)

                    # Create hourly item once 4 quarters are collected
                    if len(quarter_buffer) == 4:
                        hour_index = (last_pos // 4) - 1
                        hour_start = start_dt + timedelta(hours=hour_index)

                        items.append(
                            EntsoeItem(
                                hour_start,
                                hour_start + timedelta(hours=1),
                                sum(quarter_buffer) / 4,
                                self.fee
                            )
                        )
                        quarter_buffer = []

                last_pos = current_pos
                continue

            # ------------------------------------------------------------
            # Price handling
            # ------------------------------------------------------------
            if valid_period and "<price.amount>" in line:
                price = float(re.search(r'<price.amount>(.*?)</price.amount>', line).group(1))

                # Update last known quarter price
                last_q_price = price
                statsmanager.set_status_data('market', 'q_price', price)

                quarter_buffer.append(price)

                # Create hourly item once 4 quarters are collected
                if len(quarter_buffer) == 4:
                    hour_index = (last_pos - 1) // 4
                    hour_start = start_dt + timedelta(hours=hour_index)

                    items.append(
                        EntsoeItem(
                            hour_start,
                            hour_start + timedelta(hours=1),
                            sum(quarter_buffer) / 4,
                            self.fee
                        )
                    )
                    quarter_buffer = []

                continue

        if not items:
            self.logger.log.warning("No prices found in the XML data.")

        return items
