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
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import socket
import requests
from requests.exceptions import ConnectionError

from spotmarket.abstract_classes.item import Item
from spotmarket.abstract_classes.marketdata import MarketData
from core.statsmanager import StatsManager


class EntsoeItem(Item):
    def __init__(self, start_datetime, end_datetime, price, fee_str):
        start_time = start_datetime.replace(tzinfo=timezone.utc)
        end_time = end_datetime.replace(tzinfo=timezone.utc)
        super().__init__(start_time, end_time, price, fee_str, 13)


class Entsoe(MarketData):

    # Map ENTSO-E resolution strings to "how many 15-minute quarters one
    # <Point> covers". A PT60M point spans 4 quarters, etc.
    _RESOLUTION_TO_QUARTERS = {
        "PT15M": 1,
        "PT30M": 2,
        "PT60M": 4,
        "PT1H": 4,
    }

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
                return self._load_data_from_xml(response.text)
            else:
                self.logger.log.warning(
                    f"Error downloading ENTSO-E prices. Status code: {response.status_code}"
                )
                self.logger.log.warning(f"URL: {url}")
                return []

        except ConnectionError as e:
            if isinstance(e.args[0], socket.gaierror):
                self.logger.log.error("Error in name resolution for 'web-api.tp.entsoe.eu'")
                self.logger.log.error("Please check your network connection and DNS configuration.")
            else:
                self.logger.log.error(f"Connection error: {e}")
                self.logger.log.error("Please check your network connection and server configuration.")
            return []

    def _make_url(self) -> str:
        start_date_str = self.getdata_start_datetime.strftime('%Y%m%d%H00')
        end_date_str = self.getdata_end_datetime.strftime('%Y%m%d%H00')

        url = (
            f"https://web-api.tp.entsoe.eu/api?"
            f"securityToken={self.api_token}"
            f"&documentType=A44"
            f"&in_Domain={self.in_domain}"
            f"&out_Domain={self.out_domain}"
            f"&periodStart={start_date_str}"
            f"&periodEnd={end_date_str}"
        )
        self.logger.log.debug(f"entsoe url: {url}")
        return url

    # ---------------------------------------------------------------------
    # XML parser
    # ---------------------------------------------------------------------
    # ENTSO-E delivers price time series like this (simplified):
    #
    #   <Publication_MarketDocument xmlns="urn:iec62325...">
    #     <TimeSeries>
    #       <Period>
    #         <timeInterval>
    #           <start>2026-01-15T23:00Z</start>
    #           <end>2026-01-16T23:00Z</end>
    #         </timeInterval>
    #         <resolution>PT15M</resolution>      (or PT60M / PT30M)
    #         <Point>
    #           <position>1</position>
    #           <price.amount>42.5</price.amount>
    #         </Point>
    #         ...
    #       </Period>
    #     </TimeSeries>
    #   </Publication_MarketDocument>
    #
    # We always emit 15-minute items, regardless of source resolution:
    #   PT15M -> 1 quarter per point (native)
    #   PT60M -> 4 identical quarters per point  (split, like Awattar)
    #   PT30M -> 2 identical quarters per point
    #
    # ENTSO-E uses sparse encoding: if a price repeats across consecutive
    # positions, only the first position is emitted, and missing positions
    # inherit the previous price ("carry forward"). Gaps in position
    # numbers are NOT errors -- they're compression.
    # ---------------------------------------------------------------------

    def _load_data_from_xml(self, xml_data: str):
        statsmanager = StatsManager()
        items = []

        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as e:
            self.logger.log.warning(f"ENTSO-E XML parse error: {e}")
            return []

        # ENTSO-E XML is namespaced. Strip namespaces from tag names so we
        # can match by local name (.find('Period') etc.) without dealing
        # with the namespace URL prefix.
        for elem in root.iter():
            if isinstance(elem.tag, str) and '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]

        # Last known price across periods. Used as fallback for leading
        # gaps in the very first period if the first <Point> isn't at
        # position 1.
        last_known_price = float(statsmanager.get_data('market', 'q_price') or 0.0)

        # Track which period start times we've seen, to skip duplicates.
        seen_periods = set()

        for period in root.iter('Period'):
            # The start can be either nested inside <timeInterval> or
            # directly inside <Period>, depending on ENTSO-E schema variant.
            start_elem = period.find('timeInterval/start')
            if start_elem is None:
                start_elem = period.find('start')
            resolution_elem = period.find('resolution')

            if start_elem is None or resolution_elem is None:
                self.logger.log.warning(
                    "ENTSO-E period missing start or resolution, skipped"
                )
                continue

            start_text = (start_elem.text or "").strip()
            resolution = (resolution_elem.text or "").strip()

            if not start_text:
                continue
            if start_text in seen_periods:
                self.logger.log.info(
                    f"Duplicate ENTSO-E period {start_text} skipped"
                )
                continue
            seen_periods.add(start_text)

            quarters_per_point = self._RESOLUTION_TO_QUARTERS.get(resolution)
            if quarters_per_point is None:
                self.logger.log.warning(
                    f"Unknown ENTSO-E resolution '{resolution}' "
                    f"for period {start_text}, skipped"
                )
                continue

            # ENTSO-E moved to native PT15M for the markets SEUSS supports.
            # If a legacy PT60M / PT30M / PT1H period still appears, we
            # accept it (split into identical quarters) but log a warning
            # so the operator notices the anomaly.
            if resolution != "PT15M":
                self.logger.log.warning(
                    f"ENTSO-E period {start_text} uses legacy resolution "
                    f"{resolution} -- expected PT15M. Splitting each point "
                    f"into {quarters_per_point} identical quarters."
                )

            try:
                period_start_dt = self._parse_period_start(start_text)
            except ValueError as e:
                self.logger.log.warning(
                    f"Cannot parse ENTSO-E period start '{start_text}': {e}"
                )
                continue

            self.logger.log.info(
                f"Processing ENTSO-E period {start_text} "
                f"(resolution {resolution} -> {quarters_per_point} quarter(s)/point)"
            )

            # Period nominally covers 96 quarters (one day). The number of
            # <Point> positions expected = 96 / quarters_per_point.
            expected_positions = 96 // quarters_per_point

            last_position = 0
            last_price = None

            for point in period.findall('Point'):
                pos_elem = point.find('position')
                price_elem = point.find('price.amount')
                if pos_elem is None or price_elem is None:
                    continue
                try:
                    position = int((pos_elem.text or "").strip())
                    price = float((price_elem.text or "").strip())
                except (ValueError, TypeError) as e:
                    self.logger.log.warning(
                        f"Cannot parse ENTSO-E point in period {start_text}: {e}"
                    )
                    continue

                # Fill any gap (carry-forward). For the very first point
                # use the persisted last_known_price as fallback.
                fill_price = last_price if last_price is not None else last_known_price
                for missing_pos in range(last_position + 1, position):
                    self._emit_quarters_for_point(
                        items, period_start_dt, missing_pos,
                        fill_price, quarters_per_point
                    )
                    self.logger.log.debug(
                        f"Carry-forward at position {missing_pos} "
                        f"with price {fill_price}"
                    )

                self._emit_quarters_for_point(
                    items, period_start_dt, position,
                    price, quarters_per_point
                )
                last_position = position
                last_price = price
                last_known_price = price

            # Trailing carry-forward up to the period's expected length.
            if last_price is not None and last_position < expected_positions:
                for missing_pos in range(last_position + 1, expected_positions + 1):
                    self._emit_quarters_for_point(
                        items, period_start_dt, missing_pos,
                        last_price, quarters_per_point
                    )
                    self.logger.log.debug(
                        f"Trailing carry-forward at position {missing_pos} "
                        f"with price {last_price}"
                    )

        # Persist the last known price so the next fetch has a fallback
        # for any leading gap.
        if last_known_price:
            statsmanager.set_status_data('market', 'q_price', float(last_known_price))
            statsmanager.set_status_data('market', 'price', float(last_known_price))

        # Cap to one or two days at quarter resolution.
        max_quarters = 192 if self.use_second_day else 96
        if len(items) > max_quarters:
            items = items[:max_quarters]

        return items

    @staticmethod
    def _parse_period_start(start_text: str) -> datetime:
        """
        Parse the ENTSO-E period start string into a tz-aware UTC datetime.
        Accepts '2026-01-15T23:00Z' and '2026-01-15T23:00:00Z' forms.
        """
        text = start_text.strip()
        if text.endswith('Z'):
            text = text[:-1]
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        raise ValueError(f"unrecognised ENTSO-E datetime format: {start_text!r}")

    def _emit_quarters_for_point(self, items, period_start_dt, position,
                                 price, quarters_per_point):
        """
        For a <Point> at the given 1-based position, emit
        `quarters_per_point` consecutive 15-minute items starting at the
        appropriate time, all carrying the same price.
        """
        if position < 1 or price is None:
            return
        point_length_minutes = quarters_per_point * 15
        offset_minutes = (position - 1) * point_length_minutes
        for q in range(quarters_per_point):
            quarter_start = period_start_dt + timedelta(
                minutes=offset_minutes + q * 15
            )
            quarter_end = quarter_start + timedelta(minutes=15)
            items.append(
                EntsoeItem(quarter_start, quarter_end, price, self.fee)
            )
