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

import pytz

from core.config import Config


class TimeUtilities:
    config = Config()
    TZ = pytz.timezone(config.time_zone)

    @staticmethod
    def convert_utc_to_local(utc_time, time_str=True):
        utc_time = TimeUtilities.check_and_convert(utc_time)

        if utc_time is not None:
            # Füge den UTC-Offset hinzu, um sicherzustellen, dass die Zeitzone korrekt behandelt wird
            utc_time = utc_time.replace(tzinfo=pytz.utc)
            local_time = utc_time.astimezone(TimeUtilities.TZ)
            if time_str:
                local_time_str = local_time.strftime('%Y-%m-%d %H:%M')
                return local_time_str
            return local_time

        return None

    @staticmethod
    def check_and_convert(utc_time):
        if isinstance(utc_time, str):
            # Wenn es ein String ist, versuche ihn in ein Datum zu konvertieren
            try:
                date_value = datetime.strptime(utc_time, '%Y-%m-%d %H:%M:%S')
                return date_value
            except ValueError:
                print(f"Der String {utc_time} entspricht nicht dem erwarteten Format.")
                return None
        elif isinstance(utc_time, datetime):
            # Wenn es bereits ein Datum ist, gebe es einfach zurück
            return utc_time
        else:
            print(f"Ungültiger Datentyp: {type(utc_time)}")
            return None

    @staticmethod
    def get_now():
        return datetime.now(TimeUtilities.TZ)
