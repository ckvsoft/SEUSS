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
from enum import Enum
from typing import Tuple, Union

class EssUnitNameResolutionError(Exception):
    pass

class ESSStatus(Enum):
    ON = 'on'
    OFF = 'off'

class ESSUnit:
    def __init__(self, **kwargs) -> None:
        self._name = kwargs.get("name", "")
        self.config = Config()
        self.config.observer.add_observer("essunit", self)

    def handle_config_update(self, config_data):
        pass

    def get_name(self):
        return self._name

    def get_version(self):
        pass

    def get_battery_current_voltage(self):
        pass

    def get_battery_current_wh(self):
        pass

    def get_battery_minimum_soc_limit(self):
        pass

    def get_battery_capacity(self):
        pass

    def get_battery_installed_capacity(self):
        pass

    def get_soc(self):
        pass

    def get_scheduler_soc(self):
        pass

    def set_discharge(self, status):
        pass

    def set_charge(self, status):
        pass

    def get_grid_meters(self):
        pass

    def get_solar_energy(self):
        pass

    def get_converter_efficiency(self) -> Tuple[float, float]:
        pass

    def get_config(self):
        raise NotImplementedError("This method must be implemented in the derived class.")
