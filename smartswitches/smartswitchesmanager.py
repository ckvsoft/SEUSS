#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2025 Christian Kvasny chris(at)ckvsoft.at
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


class SmartSwitchesManager:
    def __init__(self):
        self.devices = []
        self.config = Config()
        self.logger = CustomLogger()
        self.load_devices(self.config.config_data.get("smart_switches", []))

    def load_devices(self, devices_config):
        for device_info in devices_config:
            if not device_info.get("enabled", True):
                continue  # skip disabled devices

            device = GenericLoaderFactory.create_loader("smartswitches", device_info)
            if device:
                self.devices.append(device)

    # --- Bulk control (used by charging/discharging triggers) -----------

    def turn_on_all(self):
        for device in self.devices:
            device.turn_on()

    def turn_off_all(self):
        for device in self.devices:
            device.turn_off()

    # --- Per-IP control (used by switching with per-IP overrides) -------

    def evaluate_per_ip(self, items, charging_count):
        """
        Walk every device and every IP, compute its effective
        (count, block_minutes) -- using per-IP overrides from the
        config when present, falling back to the global switching
        settings otherwise -- and switch the IP on or off based on
        whether the current quarter falls inside one of its lowest
        charge blocks.

        The hard cap (charging_price_hard_cap) is applied here too:
        when the CURRENT quarter price exceeds the hard cap, all IPs
        are switched off regardless of their cluster membership --
        same rule as the bulk switching path.

        Parameters
        ----------
        items : Itemlist
            The market data the conditions evaluate against. Must have
            get_lowest_charging_blocks(count, block_minutes=...) and
            get_current_price() in line with what core/conditions.py uses.
        charging_count : int
            Global number_of_lowest_prices_for_charging from config -- used
            as the final fallback when neither a per-IP nor a global
            switching count is configured.
        """
        global_count = getattr(
            self.config, "number_of_lowest_prices_for_switching", 0
        ) or 0
        global_minutes = getattr(
            self.config, "switching_block_minutes", 60
        ) or 60

        # Hard cap on the current quarter -- overrides any per-IP rule.
        cap = getattr(self.config, "charging_price_hard_cap", None)
        cur_price_cent = items.get_current_price(convert=True)
        cap_blocks_now = False
        if cap is not None and cur_price_cent is not None:
            try:
                if float(cur_price_cent) > float(cap):
                    cap_blocks_now = True
            except (TypeError, ValueError):
                pass

        for device in self.devices:
            ips = list(getattr(device, "ips", []) or [])
            if isinstance(ips, str):
                # Defensive: some subclasses keep ips as a single string
                ips = [ip.strip() for ip in ips.split("|") if not ip.startswith("!")]

            for ip in ips:
                if cap_blocks_now:
                    self.logger.log.info(
                        f"[{device.name}/{ip}] current price {cur_price_cent} "
                        f"exceeds hard cap {cap} -> off"
                    )
                    device.turn_off_ip(ip)
                    continue

                count, block_minutes = device.get_ip_settings(
                    ip, global_count, global_minutes, charging_count
                )

                if not count:
                    # No effective count -> nothing to do for this IP.
                    self.logger.log.debug(
                        f"[{device.name}/{ip}] no switching count configured, "
                        f"leaving state unchanged"
                    )
                    continue

                blocks = items.get_lowest_charging_blocks(
                    count, block_minutes=block_minutes
                )
                in_block = any(b.is_active_now() for b in blocks)

                if in_block:
                    self.logger.log.info(
                        f"[{device.name}/{ip}] in lowest-{count}x{block_minutes}min "
                        f"block -> on"
                    )
                    device.turn_on_ip(ip)
                else:
                    self.logger.log.debug(
                        f"[{device.name}/{ip}] outside lowest-{count}x{block_minutes}min "
                        f"block -> off"
                    )
                    device.turn_off_ip(ip)
