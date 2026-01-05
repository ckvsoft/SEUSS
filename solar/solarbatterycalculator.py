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
from core.statsmanager import StatsManager
from core.timeutilities import TimeUtilities
from core.log import CustomLogger


class SolarBatteryCalculator:
    """
    Calculates the required battery SOC to safely cover consumption
    until next solar availability, based on forecast and current state.
    """

    NOMINAL_BATTERY_VOLTAGE = 57.6     # V (should be configurable)
    SAFETY_MARGIN_PERCENT = 5.0        # %

    def __init__(self, solardata):
        self.logger = CustomLogger()
        self.solardata = solardata

        # PV peak power in W
        self.solar_peak_power = solardata.power_peak * 1000

        # Defaults
        self.average_consumption = 0.0  # W
        self.efficiency = 100.0         # %

        # Load average consumption
        consumption_data = StatsManager().get_data(
            "powerconsumption", "daily_watt_average"
        )
        if consumption_data:
            self.average_consumption = round(consumption_data[0], 2)

        # Load solar efficiency
        efficiency_data = StatsManager().get_data("solar", "efficiency")
        if efficiency_data:
            self.efficiency = round(efficiency_data[0], 2)

    # ------------------------------------------------------------------

    def calculate_full_capacity_wh(self) -> float:
        """
        Returns full battery capacity in Wh.
        """
        capacity_ah = self.solardata.battery_capacity

        if capacity_ah <= 0:
            self.logger.log.error("Battery capacity (Ah) not configured")
            return 0.0

        return capacity_ah * self.NOMINAL_BATTERY_VOLTAGE

    # ------------------------------------------------------------------

    def _get_forecast_context(self, now):
        """
        Determines whether to use today or tomorrow forecast.
        Returns: forecast_wh, daylight_hours, hours_until_target
        """
        sunset_time = datetime.strptime(
            self.solardata.sunset_current_day, "%Y-%m-%dT%H:%M"
        ).time()

        if now.time() > sunset_time:
            self.logger.log.debug("Using tomorrow forecast")
            forecast = self.solardata.total_tomorrow_day
            daylight_hours = self.solardata.sun_time_tomorrow_minutes / 60
            target_time = datetime.strptime(
                self.solardata.sunrise_tomorrow_day, "%Y-%m-%dT%H:%M"
            ).astimezone(TimeUtilities.TZ)
        else:
            self.logger.log.debug("Using today forecast")
            forecast = self.solardata.total_current_day
            daylight_hours = self.solardata.sun_time_today_minutes / 60
            target_time = datetime.strptime(
                self.solardata.sunset_current_day, "%Y-%m-%dT%H:%M"
            ).astimezone(TimeUtilities.TZ)

        hours_until_target = max(
            (target_time - now).total_seconds() / 3600, 0
        )

        return forecast, daylight_hours, hours_until_target

    # ------------------------------------------------------------------

    def calculate_battery_percentage(self) -> float:
        """
        Returns the required battery SOC (%) to safely cover consumption.
        """
        try:
            now = TimeUtilities.get_now()

            # --- Forecast context ---
            forecast, daylight_hours, hours_until_target = (
                self._get_forecast_context(now)
            )

            # --- Battery capacity ---
            full_capacity_wh = self.calculate_full_capacity_wh()
            if full_capacity_wh <= 0:
                return self.solardata.battery_minimum_soc_limit

            soc = self.solardata.soc
            if soc <= 0:
                self.logger.log.warning("SOC unavailable, using minimum SOC")
                return self.solardata.battery_minimum_soc_limit

            actual_capacity_wh = full_capacity_wh * soc / 100

            # --- Consumption until next solar event ---
            consumption_wh = self.average_consumption * hours_until_target

            self.logger.log.debug(
                f"Consumption: {consumption_wh:.2f} Wh "
                f"over {hours_until_target:.2f} h"
            )

            # --- Solar production ---
            if not forecast or daylight_hours <= 0:
                solar_wh = 0.0
            else:
                max_solar_per_hour = (
                    self.solar_peak_power * self.efficiency / 100
                )
                forecast_per_hour = (
                    forecast / daylight_hours * self.efficiency / 100
                )
                solar_wh = (
                    min(max_solar_per_hour, forecast_per_hour)
                    * daylight_hours
                )

            # --- Net battery usage ---
            net_usage_wh = consumption_wh - solar_wh

            if net_usage_wh <= 0:
                self.logger.log.debug(
                    "Solar production covers consumption"
                )
                return self.solardata.battery_minimum_soc_limit

            remaining_wh = actual_capacity_wh - net_usage_wh

            # --- Required SOC ---
            required_soc = (
                (full_capacity_wh - remaining_wh)
                / full_capacity_wh
                * 100
            )

            # --- Apply limits ---
            required_soc = max(
                required_soc,
                self.solardata.battery_minimum_soc_limit
            )
            required_soc = min(required_soc, 100.0)

            # --- Safety margin ---
            required_soc *= (1 - self.SAFETY_MARGIN_PERCENT / 100)

            self.logger.log.info(
                f"Required SOC: {required_soc:.2f}% "
                f"(Remaining: {remaining_wh:.2f} Wh)"
            )

            return round(required_soc, 2)

        except Exception:
            self.logger.log.exception(
                "Battery SOC calculation failed"
            )
            return self.solardata.battery_minimum_soc_limit
