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

        # Initialisiere zwei Dictionaries für heute und morgen
        today_data = {}
        tomorrow_data = {}

        # Aktuelle Stunde und Tag
        current_day = datetime.today().day
        next_day = current_day + 1

        # Durchlaufe alle Items und teile sie in heute und morgen basierend auf der Stunde
        for item in sorted_items:
            start_datetime = item.get_start_datetime(localtime=True)
            day = int(start_datetime.split(' ')[0].split('-')[2])  # Extrahiere tag
            start_hour = int(start_datetime.split(' ')[1].split(':')[0])  # Extrahiere die Stunde

            price = item.get_price(convert=True)
            price = float(price)

            # Teile die Stunden auf: 0 bis 23 für heute, 24 bis 47 für morgen
            if day < next_day:
                today_data[start_hour] = price
            else:
                tomorrow_data[start_hour] = price  # Für morgen die Stunden 0 bis 23

        # Rückgabe der Daten für heute und morgen sowie der Stundenlisten
        today_hours = list(today_data.keys())
        tomorrow_hours = list(tomorrow_data.keys())

        return today_data, today_hours, tomorrow_data, tomorrow_hours

    def get_current_price(self, convert=False):
        now = datetime.utcnow().replace(tzinfo=timezone.utc)

        for item in self.item_list:
            start_datetime = item.get_start_datetime().replace(tzinfo=timezone.utc)
            end_datetime = item.get_end_datetime().replace(tzinfo=timezone.utc)

            # Überprüfen, ob das Item innerhalb der Start- und Endzeit liegt
            if start_datetime < now < end_datetime:
                return item.get_price(convert)

        self.logger.log_error("get_current_price -> Item not found.")
        return None

#    def get_average_price(self, convert=False):
#        total_prices = sum(float(item.get_price(convert)) for item in self.item_list)
#        count = len(self.item_list)
#        if count == 0:
#            return 0.0
#
#        return round(total_prices / len(self.item_list), 4) if self.item_list else 0.0

    def get_average_price_by_date(self, convert=False):
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1) - timedelta(seconds=1)
        tomorrow_start = today_start + timedelta(days=1)
        tomorrow_end = tomorrow_start + timedelta(days=1) - timedelta(seconds=1)

        # Filter Items
        today_items = [
            item for item in self.item_list
            if (item.get_start_datetime() <= today_end and (item.get_end_datetime() or today_end) >= today_start)
        ]
        tomorrow_items = [
            item for item in self.item_list
            if
            (item.get_start_datetime() <= tomorrow_end and (item.get_end_datetime() or tomorrow_end) >= tomorrow_start)
        ]

        def calculate_average(items):
            if not items:
                return None
            total_prices = sum(float(item.get_price(convert)) for item in items)
            return round(total_prices / len(items), 4)

        average_today = calculate_average(today_items)
        average_tomorrow = calculate_average(tomorrow_items)

        return average_today, average_tomorrow

    def get_lowest_prices(self, count, item_list=None):
        if item_list is None:
            item_list = self.item_list

        if isinstance(count, int):
            today_items, tomorrow_items = [], []
            for item in item_list:
                if self.is_today(item):
                    today_items.append(item)
                else:
                    tomorrow_items.append(item)

            # Die Anzahl von 'count' Items für heute
            today_sorted = sorted(today_items, key=lambda x: x.get_price(False))[:count]
            # Die Anzahl von 'count' Items für morgen (falls vorhanden)
            tomorrow_sorted = sorted(tomorrow_items, key=lambda x: x.get_price(False))[:count]

            # Heute und morgen zusammenführen
            total_items = today_sorted + tomorrow_sorted

            # Sortiere alle Items nach dem Startzeitpunkt
            total_items = sorted(total_items, key=lambda x: x.get_start_datetime())

            return total_items

        return self._get_prices_relative_to_average(count, item_list)

    def get_highest_prices(self, count, item_list=None):
        if item_list is None:
            item_list = self.item_list

        if isinstance(count, int):
            today_items, tomorrow_items = [], []
            for item in item_list:
                if self.is_today(item):
                    today_items.append(item)
                else:
                    tomorrow_items.append(item)

            # Die Anzahl von 'count' Items für heute (höchste Preise)
            today_sorted = sorted(today_items, key=lambda x: x.get_price(False), reverse=True)[:count]
            # Die Anzahl von 'count' Items für morgen (höchste Preise)
            tomorrow_sorted = sorted(tomorrow_items, key=lambda x: x.get_price(False), reverse=True)[:count]

            # Heute und morgen zusammenführen
            total_items = today_sorted + tomorrow_sorted

            # Sortiere alle Items nach dem Startzeitpunkt
            total_items = sorted(total_items, key=lambda x: x.get_start_datetime())

            return total_items

        return self._get_prices_relative_to_average(count, item_list)

    # Hilfsmethode für heute
    def is_today(self, item):
        # Prüft, ob das Item heute ist
        today_start = datetime.utcnow().replace(tzinfo=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)
        return item.get_start_datetime() < today_end

    def _get_prices_relative_to_average(self, percentage, item_list):
        # Durchschnittspreis für heute und morgen abrufen
        average_today, average_tomorrow = self.get_average_price_by_date()
        self.logger.log_debug(f"Average Price Today: {average_today}, Average Price Tomorrow: {average_tomorrow}")

        if not isinstance(percentage, float):
            percentage = 1.0

        # Hilfsfunktion zur Berechnung des Schwellenwerts
        def calculate_threshold(average_price, _percentage):
            if _percentage >= 1.0:
                return average_price * (1 + (_percentage - 1))
            else:
                return average_price * _percentage

        relevant_items = []

        # Aktuelles Datum berechnen (mit UTC-Zeitzone)
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1) - timedelta(seconds=1)
        tomorrow_start = today_start + timedelta(days=1)
        tomorrow_end = tomorrow_start + timedelta(days=1) - timedelta(seconds=1)

        # Über alle Items iterieren
        for item in item_list:
            start = item.get_start_datetime()  # Erwartet UTC
            end = item.get_end_datetime() or (start + timedelta(days=1))

            today_start = today_start.replace(tzinfo=timezone.utc)
            today_end = today_end.replace(tzinfo=timezone.utc)

            # Items für heute prüfen
            if start <= today_end and end >= today_start:
                threshold_price = calculate_threshold(average_today, percentage)
                item_price = float(item.get_price(False))
                # Wenn der Preis dem Schwellenwert entspricht, hinzufügen
                if (percentage >= 1.0 and item_price > threshold_price) or \
                        (percentage < 1.0 and item_price < threshold_price):
                    relevant_items.append(item)

            # Items für morgen prüfen
            elif start <= tomorrow_end and end >= tomorrow_start:
                threshold_price = calculate_threshold(average_tomorrow, percentage)
                item_price = float(item.get_price(False))
                # Wenn der Preis dem Schwellenwert entspricht, hinzufügen
                if (percentage >= 1.0 and item_price > threshold_price) or \
                        (percentage < 1.0 and item_price < threshold_price):
                    relevant_items.append(item)

        # Debug-Ausgabe für relevante Items
        self.logger.log_debug(f"Relevant Items: {len(relevant_items)}")

        return relevant_items

    #    def _get_prices_relative_to_average(self, percentage, item_list):
    #        average_price = self.get_average_price()
    #        self.logger.log_debug(f"Average Price: {average_price}")  # Debug-Ausgabe
    #
    #       if not isinstance(percentage, float):
    #            percentage = 1.0
    #
    #        if percentage >= 1.0:
    #            # Prozentwert größer als 1 bedeutet, dass es über dem Durchschnitt liegt
    #            threshold_price = average_price * (1 + (percentage - 1))
    #            self.logger.log_debug(f"Threshold Price (Over Average): {threshold_price}")  # Debug-Ausgabe
    #            relevant_items = [item for item in item_list if item.get_price(False) > threshold_price]
    #        else:
    #            # Prozentwert kleiner als 1 bedeutet, dass es unter dem Durchschnitt liegt
    #            threshold_price = average_price * percentage
    #            self.logger.log_debug(f"Threshold Price (Under Average): {threshold_price}")  # Debug-Ausgabe
    #            relevant_items = [item for item in item_list if item.get_price(False) < threshold_price]
    #
    #        self.logger.log_debug(f"Relevant Items: {len(relevant_items)}")  # Debug-Ausgabe
    #        return relevant_items

    #    def _get_prices_relative_to_average(self, percentage, item_list):
    #        average_price = self.get_average_price()

    #        if not isinstance(percentage, float):
    #            percentage = 1.0

    #        if percentage >= 1.0:
    #            # Prozentwert größer als 1 bedeutet, dass es über dem Durchschnitt liegt
    #            threshold_price = average_price * (1 + (percentage - 1))
    #            relevant_items = [item for item in item_list if item.get_price(False) >= threshold_price]
    #        else:
    #            # Prozentwert kleiner als 1 bedeutet, dass es unter dem Durchschnitt liegt
    #            threshold_price = average_price * percentage
    #            relevant_items = [item for item in item_list if item.get_price(False) < threshold_price]

    #        return relevant_items

    def remove_expired_items(self):
        self.item_list = [item for item in self.item_list if not item.is_expired()]

    def log_items(self):
        for item in self.get_current_list():
            self.logger.log_debug(
                f"Starttime: {item.get_start_datetime(True)}, Endtime: {item.get_end_datetime(True)}, "
                f"Price: {item.price} Millicents pro kWh, "
                f"Price: {item.millicent_to_cent(item.price)} Cent pro kWh."
            )

    def perform_update(self, items):
        self.current_market_name = self.primary_market_name
        items.remove_expired_items()

        if not items.get_current_list() or all(
                item.is_expired() for item in items.get_current_list()) or items.get_current_price() is None or (
                self.config.use_second_day and len(items.get_current_list()) < 25):
            self.logger.log_info(f"Price update is done with {self.primary_market_name}...")
            market_info = self.config.get_market_info(self.primary_market_name)
            loader = GenericLoaderFactory.create_loader("spotmarket", market_info)
            updated_items = Itemlist.create_item_list(loader.load_data(self.config.use_second_day))

            if not updated_items.get_current_list():
                self.logger.log_warning(f"Update with {self.primary_market_name} not possible")
                failback_market_info = self.config.get_market_info(self.failback_market_name)

                if not failback_market_info or failback_market_info == {}:
                    self.logger.log_warning(
                        "Failback market information is empty or an empty dictionary. Aborting.")
                else:
                    self.logger.log_info(f"Price update is done with {self.failback_market_name}...")
                    failback_loader = GenericLoaderFactory.create_loader("spotmarket", failback_market_info)
                    updated_items = Itemlist.create_item_list(failback_loader.load_data(self.config.use_second_day))

                    self.current_market_name = self.failback_market_name

            items = updated_items

        return items
