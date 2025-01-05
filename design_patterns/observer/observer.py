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

class Observer:
    def __init__(self):
        self._observers = {}

    def add_observer(self, name, observer, allow_multiple=False):
        if not allow_multiple:
            # Wenn nur eine Instanz desselben Namens erlaubt ist,
            # überprüfen, ob bereits eine vorhanden ist und sie ersetzen
            self._observers[name] = observer
        else:
            # Wenn mehrere Instanzen desselben Namens erlaubt sind,
            # speichern Sie sie in einer Liste
            if name not in self._observers:
                self._observers[name] = [observer]
            else:
                self._observers[name].append(observer)

    def remove_observer(self, name):
        if name in self._observers:
            del self._observers[name]

    def notify_observers(self, config_data):
        pass

    def update(self, *args, **kwargs):
        pass
