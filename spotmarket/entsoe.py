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
        start_time = start_datetime.replace(tzinfo=timezone.utc)
        end_time = end_datetime.replace(tzinfo=timezone.utc)
        super().__init__(start_time, end_time, price, fee_str, 13)


class Entsoe(MarketData):
    def __init__(self, **kwargs):
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
                self.logger.log.warning(f"Error downloading ENTSO-E prices. Status code: {response.status_code}")
                self.logger.log.warning(f"URL: {url}")
                return []

        except ConnectionError as e:
            if isinstance(e.args[0], socket.gaierror):
                self.logger.log.error("Error in name resolution for 'api.awattar.com'")
                self.logger.log.error("Please check your network connection and DNS configuration.")
            else:
                self.logger.log.error(f"Connection error: {e}")
                self.logger.log.error("Please check your network connection and server configuration.")
            return []

    def _make_url(self) -> str:
        start_date = self.getdata_start_datetime
        start_date_str = start_date.strftime('%Y%m%d%H00')
        end_date_str = self.getdata_end_datetime.strftime('%Y%m%d%H00')
        url = f"https://web-api.tp.entsoe.eu/api?securityToken={self.api_token}&documentType=A44&in_Domain={self.in_domain}&out_Domain={self.out_domain}&periodStart={start_date_str}&periodEnd={end_date_str}"
        self.logger.log.debug(f"entsoe url: {url}")
        return url

    def _load_data_from_xml(self, xml_data: str):
        statsmanager = StatsManager()
        error_code = 0
        error_message = ""
        items = []

        lines = xml_data.split('\n')
        capture_period = False
        valid_period = False
        capture_time = False
        in_reason = False

        start_datetime = ""
        current_pos = 0
        last_pos = -1  # Letzte verarbeitete Position (PT15)
        last_price = statsmanager.get_data('market', 'last_pt15_price')  # letzter 15-min-Wert aus StatsManager
        pt15_prices = []  # sammelt 4 Viertelstundenpreise für 1 Stunde
        period_count = 0

        for line in lines:
            if "<Period>" in line:
                if period_count >= 2:
                    break
                capture_period = True
                valid_period = False
                last_pos = -1
                pt15_prices = []
            elif "</Period>" in line:
                if capture_period and valid_period:
                    # letzte fehlende Viertelstunden auffüllen
                    for missing_pos in range(last_pos + 1, 96):  # 96 Viertelstunden = 24 Stunden
                        dt_start = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%MZ") + timedelta(
                            minutes=15 * missing_pos)
                        dt_end = dt_start + timedelta(minutes=15)
                        pt15_prices.append(last_price)
                        if len(pt15_prices) == 4:
                            avg_price = sum(pt15_prices) / 4
                            items.append(
                                EntsoeItem(dt_start - timedelta(hours=0, minutes=45), dt_end, avg_price, self.fee))
                            statsmanager.set_status_data('market', 'price', avg_price)
                            pt15_prices = []
                    period_count += 1
                capture_period = False
                valid_period = False
            elif capture_period and "<timeInterval>" in line:
                capture_time = True
            elif capture_period and "</timeInterval>" in line:
                capture_time = False
            elif capture_time and "<start>" in line:
                start_datetime = re.search(r'<start>(.*?)<\/start>', line).group(1)
            elif capture_period and "<resolution>PT15M</resolution>" in line:
                valid_period = True
            elif valid_period and "<position>" in line:
                position = int(re.search(r'<position>(.*?)<\/position>', line).group(1)) - 1
                # fehlende Viertelstunden zwischen last_pos und position auffüllen
                for missing_pos in range(last_pos + 1, position):
                    pt15_prices.append(last_price)
                    if len(pt15_prices) == 4:
                        dt_start = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%MZ") + timedelta(
                            minutes=15 * (missing_pos - 3))
                        dt_end = dt_start + timedelta(hours=1)
                        avg_price = sum(pt15_prices) / 4
                        items.append(EntsoeItem(dt_start, dt_end, avg_price, self.fee))
                        statsmanager.set_status_data('market', 'price', avg_price)
                        pt15_prices = []
                last_pos = position
            elif valid_period and "<price.amount>" in line:
                current_price = float(re.search(r'<price.amount>(.*?)<\/price.amount>', line).group(1))
                pt15_prices.append(current_price)
                last_price = current_price  # für Lückenfüller merken
                if len(pt15_prices) == 4:
                    dt_start = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%MZ") + timedelta(
                        minutes=15 * (last_pos - 3))
                    dt_end = dt_start + timedelta(hours=1)
                    avg_price = sum(pt15_prices) / 4
                    items.append(EntsoeItem(dt_start, dt_end, avg_price, self.fee))
                    statsmanager.set_status_data('market', 'price', avg_price)
                    pt15_prices = []

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
            self.logger.log.warning(f"Entsoe data retrieval error found in the XML data: {error_message}")
        elif not items:
            self.logger.log.warning("No prices found in the XML data.")

        # letzte 15-min Preis im StatsManager speichern
        statsmanager.set_status_data('market', 'last_pt15_price', last_price)

        return items
