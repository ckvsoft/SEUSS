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

from core.config import Config
from core.log import CustomLogger
from design_patterns.factory.generic_loader_factory import GenericLoaderFactory

from datetime import datetime, timedelta, timezone


class Itemlist:
    def __init__(self, items=None):
        self.item_list = items if items is not None else []
        self.config = Config()
        self.logger = CustomLogger()

        self.primary_market_name = next(
            (market['name'] for market in self.config.markets if
             market.get('primary', False) and market.get('enabled', False)),
            "DefaultMarket"
        )
        self.failback_market_name = next(
            (market['name'] for market in self.config.markets if
             not market.get('primary', False) and market.get('enabled', False)),
            "DefaultFailbackMarket"
        )
        self.current_market_name = self.primary_market_name

    def add_item(self, item):
        self.item_list.append(item)

    @staticmethod
    def create_item_list(items=None):
        return Itemlist(items)

    def get_current_list(self):
        return self.item_list

    def get_item_count(self):
        return len(self.item_list)

    def get_valid_items_count_until_midnight(self, price_list):
        # Aktuelle Zeit in UTC
        local_now = datetime.now()

        # Berechne Mitternacht für heute (lokale Zeit) und konvertiere sie nach UTC
        local_midnight = datetime.combine(local_now.date() + timedelta(days=1), datetime.min.time())
        now = local_now.astimezone(timezone.utc)
        midnight = local_midnight.astimezone(timezone.utc)

        valid_items = [item for item in price_list if self.is_valid_item(item, now, midnight)]

        return len(valid_items)

    #    def get_valid_items_count_until_midnight(self, price_list):
    #        now = datetime.now(timezone.utc)
    #        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)

    #        valid_items = [item for item in price_list if self.is_valid_item(item, now, midnight)]

    #        return len(valid_items)

    def is_valid_item(self, item, now, midnight):
        end_datetime = item.get_end_datetime()

        if end_datetime is None:
            return False

        return now < end_datetime.replace(tzinfo=timezone.utc) < midnight

    def get_valid_items_count_until_next_midnight(self, price_list):
        now = datetime.now()
        next_midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).replace(
            tzinfo=timezone.utc)

        valid_items = [item for item in price_list if self.is_valid_item(item, now, next_midnight)]

        return len(valid_items)

    def get_items_count_until_midnight(self):
        now = datetime.now()
        midnight = datetime.combine(now.date(), datetime.min.time()) + timedelta(days=1)

        items_until_midnight = [item for item in self.item_list if item.get_start_datetime() < midnight]

        return len(items_until_midnight)

    @staticmethod
    def get_price_hour_lists(item_list):
        sorted_items = sorted(item_list, key=lambda x: x.get_start_datetime())
        data = {}
        for item in sorted_items:
            start_hour = int(item.get_start_datetime(localtime=True).split(' ')[1].split(':')[0])
            price = item.get_price(convert=True)
            data[start_hour] = float(price)

        hours_list = list(data.keys())
        return data, hours_list

    def get_current_price(self, convert=False):
        now = datetime.utcnow().replace(tzinfo=timezone.utc)

        for item in self.item_list:
            start_datetime = item.get_start_datetime().replace(tzinfo=timezone.utc)
            end_datetime = item.get_end_datetime().replace(tzinfo=timezone.utc)

            # Überprüfen, ob das Item innerhalb der Start- und Endzeit liegt
            if start_datetime < now < end_datetime:
                return item.get_price(convert)

        self.logger.log_error("Kein passendes Item gefunden.")
        return None

    def get_average_price(self, convert=False):
        total_prices = sum(float(item.get_price(convert)) for item in self.item_list)
        count = len(self.item_list)
        if count == 0:
            return 0.0

        return round(total_prices / len(self.item_list), 4) if self.item_list else 0.0

    def get_lowest_prices(self, count):
        if isinstance(count, int):
            sorted_items = sorted(self.item_list, key=lambda x: x.get_price(False))
            sorted_items = sorted_items[:count]
            sorted_items = sorted(sorted_items, key=lambda x: x.get_start_datetime())

            return sorted_items

        return self.get_prices_relative_to_average(count)

    def get_highest_prices(self, count):
        if isinstance(count, int):
            sorted_items = sorted(self.item_list, key=lambda x: x.get_price(False), reverse=True)
            sorted_items = sorted_items[:count]
            sorted_items = sorted(sorted_items, key=lambda x: x.get_start_datetime())

            return sorted_items

        return self.get_prices_relative_to_average(count)

    def get_prices_relative_to_average(self, percentage):
        average_price = self.get_average_price()

        if not isinstance(percentage, float):
            percentage = 1.0

        if percentage >= 1.0:
            # Prozentwert größer als 1 bedeutet, dass es über dem Durchschnitt liegt
            threshold_price = average_price * (1 + (percentage - 1))
            relevant_items = [item for item in self.item_list if item.get_price(False) >= threshold_price]
        else:
            # Prozentwert kleiner als 1 bedeutet, dass es unter dem Durchschnitt liegt
            threshold_price = average_price * percentage
            relevant_items = [item for item in self.item_list if item.get_price(False) < threshold_price]

        return relevant_items

    def remove_expired_items(self):
        self.item_list = [item for item in self.item_list if not item.is_expired()]

    def log_items(self):
        for item in self.get_current_list():
            self.logger.log_debug(
                f"Starttime: {item.get_start_datetime(True)}, Endzeit: {item.get_end_datetime(True)}, "
                f"Price: {item.price} Millicents pro kWh, "
                f"Price: {item.millicent_to_cent(item.price)} Cent pro kWh."
            )

    def perform_update(self, items):
        self.current_market_name = self.primary_market_name
        items.remove_expired_items()

        if not items.get_current_list() or all(
                item.is_expired() for item in items.get_current_list()) or items.get_current_price() is None:
            self.logger.log_info(f"Price update is done with {self.primary_market_name}...")
            market_info = self.config.get_market_info(self.primary_market_name)
            loader = GenericLoaderFactory.create_loader("spotmarket", market_info)
            updated_items = Itemlist.create_item_list(loader.load_data(self.config.use_second_day))

            if not updated_items.get_current_list():
                self.logger.log_warning(f"Update mit {self.primary_market_name} nicht möglich")
                failback_market_info = self.config.get_market_info(self.failback_market_name)

                if not failback_market_info or failback_market_info == {}:
                    self.logger.log_warning(
                        "Failback-Markt-Informationen sind leer oder ein leeres Dictionary. Abbruch.")
                else:
                    self.logger.log_info(f"Price update is done with {self.failback_market_name}...")
                    failback_loader = GenericLoaderFactory.create_loader("spotmarket", failback_market_info)
                    updated_items = Itemlist.create_item_list(failback_loader.load_data(self.config.use_second_day))

                    self.current_market_name = self.failback_market_name

            items = updated_items

        return items
