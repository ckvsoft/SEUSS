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
                return round(existing_value, 2)
        else:
            cls.data['peek'][key] = {'value': value, 'timestamp': now}

        cls.save_data()

        return round(value, 2)

    @classmethod
    def update_percent_status_data(cls, group, key, new_value, max_count = 1000):
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
                    e_value =value * count
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
    def insert_hourly_status_data(cls, key, hour, value, cloudcover):
        if value is None or cloudcover is None:
            return

        if "hourly_data" not in cls.data:
            cls.data["hourly_data"] = {}

        date = datetime.now().strftime('%Y-%m-%d')
        date_hour = datetime.now().strftime('%Y-%m-%d.%H')

        if key not in cls.data["hourly_data"]:
            cls.data["hourly_data"][key] = {}

        if 'total' not in cls.data["hourly_data"][key]:
            cls.data["hourly_data"][key]['total'] = {'total_value': 0, 'count': 0,
                                                  'last_updated': None}

        key_entry = cls.data["hourly_data"][key]['total']
        if key_entry['last_updated'] != date_hour:
            key_entry['total_value'] = (key_entry['total_value'] * key_entry['count'] + value) / (
                    key_entry['count'] + 1)
            key_entry['count'] += 1
            key_entry['last_updated'] = date_hour

        if str(hour) not in cls.data["hourly_data"][key]:
            cls.data["hourly_data"][key][str(hour)] = {'total_value': 0, 'count': 0,
                                                  'last_updated': None, 'cloudcover': {}}


        data_entry = cls.data["hourly_data"][key][str(hour)]

        if data_entry['last_updated'] != date:
            data_entry['total_value'] = (data_entry['total_value'] * data_entry['count'] + value) / (
                        data_entry['count'] + 1)
            data_entry['count'] += 1
            data_entry['last_updated'] = date
            if str(cloudcover) in data_entry['cloudcover']:
                cloudcover_data = data_entry['cloudcover'][str(cloudcover)]
                cloudcover_data['value'] = (cloudcover_data['value'] * cloudcover_data['cloudcover_count'] + value) / (
                            cloudcover_data['cloudcover_count'] + 1)
                cloudcover_data['cloudcover_count'] += 1
            else:
                data_entry['cloudcover'][str(cloudcover)] = {
                    'value': value,
                    'cloudcover_count': 1
                }

            cls.save_data()

    @classmethod
    def get_hourly_data(cls, key, hour, cloudcover):
        date = datetime.now().strftime('%Y-%m-%d')
        if key in cls.data["hourly_data"] and str(hour) in cls.data["hourly_data"][key]:
            data_entry = cls.data["hourly_data"][key][str(hour)]
            if str(cloudcover) in data_entry['cloudcover']:
                return data_entry['cloudcover'][str(cloudcover)]['value']

            # Falls der spezifische Cloudcover-Wert nicht existiert, versuchen wir zu interpolieren
            cloudcover_data = data_entry['cloudcover']
            cloudcover_keys = sorted(int(k) for k in cloudcover_data.keys())

            if len(cloudcover_keys) >= 2:
                lower_key = None
                upper_key = None

                if cloudcover < cloudcover_keys[0]:
                    lower_key = cloudcover_keys[0]
                    upper_key = cloudcover_keys[1]
                else:
                    for k in cloudcover_keys:
                        if k <= cloudcover:
                            lower_key = k
                        if k >= cloudcover:
                            upper_key = k
                            break

                if lower_key is not None and upper_key is not None and lower_key != upper_key:
                    lower_value = cloudcover_data[str(lower_key)]['value']
                    upper_value = cloudcover_data[str(upper_key)]['value']

                    # Sicherstellen, dass wir keine Division durch 0 haben
                    if upper_key != lower_key:
                        # Lineare Interpolation
                        interpolated_value = lower_value + (upper_value - lower_value) * (cloudcover - lower_key) / (
                                    upper_key - lower_key)
                        return interpolated_value

            elif 'total_value' in data_entry:
                return data_entry['total_value']

        # Wenn keine spezifischen Daten vorhanden sind, geben wir den Gesamtwert zurück
        if key in cls.data["hourly_data"] and 'total' in cls.data["hourly_data"][key]:
            data_entry = cls.data["hourly_data"][key]['total']
            if 'total_value' in data_entry:
                return data_entry['total_value']

        return None

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
