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

from datetime import datetime
import json
import os, sys

from design_patterns.singleton import Singleton


class StatsManager(Singleton):
    max_entries = 24 * 3
    download_times = []
    power_events = {'on': [], 'off': []}
    main_script_path = os.path.abspath(sys.argv[0])
    main_script_directory = os.path.dirname(main_script_path)
    file_path = os.path.join(main_script_directory, 'status.json')

    data = {}

    def __new__(cls):
        return super().__new__(cls)

    def __init__(self):
        super().__init__()
        self.load_data()

    @classmethod
    def load_data(cls):
        try:
            with open(cls.file_path, 'r') as file:
                cls.data = json.load(file)
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            cls.data = {}

    @classmethod
    def save_data(cls):
        with open(cls.file_path, 'w') as file:
            json.dump(cls.data, file, indent=4)

    @classmethod
    def insert_new_daily_status_data(cls, group, key, value):
        # cls.cleanup_old_entries(group)  # Clean up old entries before inserting new data

        date_key = f"date_{key}"
        today = datetime.now().strftime('%Y-%m-%d')

        if group not in StatsManager.data:
            cls.data[group] = {}

        if date_key not in cls.data[group] or cls.data[group][date_key] != today:
            # If the date key doesn't exist or is not today, update the entry
            current_value = cls.data[group].get(key)
            if current_value is not None:
                if value > current_value:
                    current_value = value - current_value
                    cls.update_percent_status_data(group, 'average', current_value, 30)

            cls.data[group][date_key] = today
            cls.data[group][key] = value
            cls.save_data()

    @classmethod
    def insert_new_status_data(cls, group, key, value):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return

        date_key = f"date_{key}"
        today = datetime.now().strftime('%Y-%m-%d')

        if group not in StatsManager.data:
            cls.data[group] = {}

        if date_key not in cls.data[group]:
            # If the date key doesn't exist or is not today, update the entry
            cls.data[group][date_key] = today
            cls.data[group][key] = value
            cls.save_data()

    @classmethod
    def set_status_data(cls, group, key, value):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return

        date_key = f"date_{key}"
        today = datetime.now().strftime('%Y-%m-%d')

        if group not in StatsManager.data:
            cls.data[group] = {}

        cls.data[group][date_key] = today
        cls.data[group][key] = value
        cls.save_data()

    @classmethod
    def insert_peek_data(cls, key, value):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if 'peek' not in cls.data:
            cls.data['peek'] = {}

        if key in cls.data['peek']:
            existing_value = cls.data['peek'][key]['value']
            if existing_value < value:
                cls.data['peek'][key] = {'value': value, 'timestamp': now}
            else:
                return round(existing_value, 2), cls.data['peek'][key]['timestamp']
        else:
            cls.data['peek'][key] = {'value': value, 'timestamp': now}

        cls.save_data()

        return round(value, 2), now

    @classmethod
    def update_percent_status_data(cls, group, key, new_value, max_count=1000):
        if not isinstance(new_value, (int, float)) or isinstance(new_value, bool):
            return None

        date_key = f"date_{key}"
        today = datetime.now().strftime('%Y-%m-%d')

        if group not in cls.data:
            cls.insert_new_status_data(group, key, new_value)

        cls.data[group][date_key] = today
        value = new_value

        if key in cls.data[group]:
            if isinstance(cls.data[group][key], list):
                value, count = cls.data[group][key]
                if count >= max_count:
                    e_value = value * count
                    e_value = (e_value - value)
                    count -= 1
                    value = e_value / count
            else:
                count = 1

            value = (count * value + new_value) / (count + 1)
            count += 1
            cls.data[group][key] = (value, count)
        else:
            cls.data[group][key] = (new_value, 1)

        cls.save_data()

        return round(value, 2)

    @classmethod
    def calculate_factor(cls, value1, value2):
        if value1 == 0:
            return None
        return value2 / value1

    @classmethod
    def cleanup_old_entries(cls, group_to_cleanup):
        today = datetime.now().strftime('%Y-%m-%d')

        if group_to_cleanup in cls.data:
            entries_to_delete = []

            for key, entry in cls.data[group_to_cleanup].items():
                if key.startswith('date_'):
                    entry_date = entry
                    if entry_date != today:
                        entries_to_delete.append(key.replace('date_', ''))
                        entries_to_delete.append(key)

            for entry_key in entries_to_delete:
                del cls.data[group_to_cleanup][entry_key]

            cls.save_data()

    @classmethod
    def remove_data(cls, group, key):
        if group in cls.data and key in cls.data[group]:
            del cls.data[group][key]
            cls.save_data()

    @classmethod
    def get_data(cls, group, key):
        group_data = cls.data.get(group, {})
        return group_data.get(key, None)

    @classmethod
    def track_download_time(cls, download_time):
        if len(cls.download_times) >= cls.max_entries:
            oldest_key = next(iter(cls.download_times))
            del cls.download_times[oldest_key]
        cls.download_times.append({'timestamp': datetime.now(), 'time': download_time})

    @classmethod
    def track_power_event(cls, event_type, price):
        if event_type in cls.power_events:
            if len(cls.power_events[event_type]) >= cls.max_entries:
                cls.power_events[event_type].pop(0)
            cls.power_events[event_type].append({'timestamp': datetime.now(), 'price': price})

    @classmethod
    def get_total_download_time(cls):
        return sum(entry['time'] for entry in cls.download_times)

    @classmethod
    def get_power_events(cls, event_type):
        return cls.power_events.get(event_type, [])
