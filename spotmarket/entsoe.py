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
        """
        Parse ENTSO-E XML data and generate EntsoeItems.
        Optimized for PT15M (Quarter-hourly) resolution.
        """
        statsmanager = StatsManager()
        error_code = 0
        error_message = ""
        items = []

        lines = xml_data.split('\n')
        capture_period = False
        valid_period = False
        capture_time = False
        in_reason = False
        seen_periods = set()

        start_datetime = ""
        current_pos = 0
        last_pos = 0

        # 1. Load initial fallback prices from StatsManager
        last_price = str(statsmanager.get_data('market', 'price') or "0.0")
        last_q_price = float(statsmanager.get_data('market', 'q_price') or last_price)

        # Default to 15m as it's the most common now
        resolution = 15
        quarter_prices = []

        for line in lines:
            line = line.strip()

            if "<Period>" in line:
                capture_period = True
                valid_period = False
                last_pos = 0
                quarter_prices = []
                start_datetime = ""
                continue

            elif "</Period>" in line:
                if capture_period and valid_period:
                    # Padding at the end of the period (96 for 15m, 24 for 60m)
                    target_pos = 96 if resolution == 15 else 24
                    while last_pos < target_pos:
                        last_pos += 1
                        dt_start = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
                        if resolution == 15:
                            quarter_prices.append(last_q_price)
                            if len(quarter_prices) == 4:
                                dt_s = dt_start + timedelta(hours=(last_pos // 4) - 1)
                                items.append(
                                    EntsoeItem(dt_s, dt_s + timedelta(hours=1), sum(quarter_prices) / 4, self.fee))
                                quarter_prices = []
                        else:
                            dt_s = dt_start + timedelta(hours=last_pos - 1)
                            items.append(EntsoeItem(dt_s, dt_s + timedelta(hours=1), float(last_price), self.fee))

                capture_period = False
                valid_period = False
                continue

            elif capture_period and "<timeInterval>" in line:
                capture_time = True
                continue
            elif capture_period and "</timeInterval>" in line:
                capture_time = False
                continue
            elif capture_time and "<start>" in line:
                start_datetime = re.search(r'<start>(.*?)<\/start>', line).group(1)
                continue

            elif capture_period and "<resolution>" in line:
                # Check for duplicates before enabling valid_period
                if start_datetime in seen_periods:
                    self.logger.log.debug(f"Duplicate start time {start_datetime} skipped.")
                    valid_period = False
                    capture_period = False
                else:
                    seen_periods.add(start_datetime)
                    # Correctly detect resolution from XML
                    resolution = 60 if "PT60M" in line else 15
                    valid_period = True
                continue

            elif valid_period and "<position>" in line:
                pos_match = re.search(r'<position>(.*?)<\/position>', line)
                if pos_match:
                    current_pos = int(pos_match.group(1))
                    dt_start = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)

                    # Fill gaps before current position (e.g. your missing Pos 51)
                    while last_pos < current_pos - 1:
                        last_pos += 1
                        if resolution == 15:
                            quarter_prices.append(last_q_price)
                            if len(quarter_prices) == 4:
                                dt_s = dt_start + timedelta(hours=(last_pos // 4) - 1)
                                items.append(
                                    EntsoeItem(dt_s, dt_s + timedelta(hours=1), round(sum(quarter_prices) / 4, 2), self.fee))
                                quarter_prices = []
                        else:
                            dt_s = dt_start + timedelta(hours=last_pos - 1)
                            items.append(EntsoeItem(dt_s, dt_s + timedelta(hours=1), float(last_price), self.fee))

                    last_pos = current_pos
                continue

            elif valid_period and "<price.amount>" in line:
                price_match = re.search(r'<price.amount>(.*?)<\/price.amount>', line)
                if price_match:
                    # 2. Update current tracking prices
                    current_val = float(price_match.group(1))
                    last_q_price = current_val
                    dt_start = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)

                    if resolution == 15:
                        quarter_prices.append(current_val)
                        if len(quarter_prices) == 4:
                            avg_p = round(sum(quarter_prices) / 4, 2)
                            last_price = str(avg_p)
                            dt_s = dt_start + timedelta(hours=(last_pos // 4) - 1)
                            items.append(EntsoeItem(dt_s, dt_s + timedelta(hours=1), avg_p, self.fee))
                            quarter_prices = []
                    else:
                        last_price = str(current_val)
                        dt_s = dt_start + timedelta(hours=last_pos - 1)
                        items.append(EntsoeItem(dt_s, dt_s + timedelta(hours=1), current_val, self.fee))
                continue

            # Error handling blocks...
            elif "<Reason>" in line:
                in_reason = True
            elif in_reason and "<code>" in line:
                error_code = int(re.search(r'<code>(.*?)<\/code>', line).group(1))
            elif in_reason and "<text>" in line:
                error_message = re.search(r'<text>(.*?)<\/text>', line).group(1)
            elif "</Reason>" in line:
                in_reason = False

        # 3. Save final prices back to StatsManager
        if items:
            statsmanager.set_status_data('market', 'price', float(last_price))
            statsmanager.set_status_data('market', 'q_price', float(last_q_price))

        # Respect use_second_day setting
        if not self.use_second_day and len(items) > 24:
            items = items[:24]

        if error_code == 999:
            self.logger.log.warning(f"ENTSO-E API error: {error_message}")
        elif not items:
            self.logger.log.warning("No price items were parsed from the XML data.")

        return items