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

from core.log import CustomLogger


class SmartSwitch:
    """
    Base class for all smart switches.

    Backward-compatible additions for per-IP configuration:
      - lowest_prices_per_ip / block_minutes_per_ip are pipe-separated
        lists matching the positions in `ips`. An empty entry (e.g.
        "8||4") means "use the global default for this IP".
      - get_ip_settings(ip) returns the (count, block_minutes) pair
        that should be used for a given IP, falling back to global
        config when no per-IP override is set.
      - turn_on_ip(ip) / turn_off_ip(ip) switch a single IP. The
        default implementation just calls turn_on() / turn_off()
        (which switches all IPs at once); subclasses that can address
        IPs individually should override these.
    """

    def __init__(self, **kwargs) -> None:
        self.logger = CustomLogger()
        self.name = kwargs.get("name", "")
        # Normalize ips to a list once here, in the abstract base. The
        # config delivers a pipe-separated string; subclasses used to
        # do `self.ips = self.ips.split("|")` themselves which left
        # `self.ips` as a string during the brief window between abstract
        # and subclass __init__ -- and broke any helper that ran in
        # between (e.g. get_ip_settings) when it tried to split() a list.
        # Single source of truth: self.ips is ALWAYS a list of strings.
        ips_raw = kwargs.get("ips", "")
        if isinstance(ips_raw, list):
            self.ips = [str(p).strip() for p in ips_raw]
        elif isinstance(ips_raw, str):
            self.ips = [p.strip() for p in ips_raw.split("|")] if ips_raw else []
        else:
            self.ips = []

        self.user = kwargs.get("user", "")
        self.password = kwargs.get("password", "")
        self.enabled = kwargs.get("enable", "")

        # Per-IP overrides (pipe-separated, position-aligned with `ips`).
        # Empty string for an entry means "fall back to global default".
        self.lowest_prices_per_ip_raw = kwargs.get("lowest_prices_per_ip", "")
        self.block_minutes_per_ip_raw = kwargs.get("block_minutes_per_ip", "")

        # Filter out disabled IPs (those starting with '!')
        self.active_ips = [
            ip for ip in self.ips if not ip.startswith("!")
        ]

    def turn_on(self):
        """Switch all configured IPs on. Subclasses override."""
        pass

    def turn_off(self):
        """Switch all configured IPs off. Subclasses override."""
        pass

    def turn_on_ip(self, ip):
        """
        Switch a single IP on. Default falls back to turning everything
        on -- subclasses that can address IPs individually should
        override this for finer-grained control.
        """
        self.turn_on()

    def turn_off_ip(self, ip):
        """Switch a single IP off. Default falls back to turn_off()."""
        self.turn_off()

    def get_ip_settings(self, ip, global_count, global_block_minutes,
                        global_charging_count):
        """
        Resolve the (count, block_minutes) pair that applies to a
        specific IP. Lookup order:

          1. lowest_prices_per_ip[position] / block_minutes_per_ip[position]
             where position is the index of `ip` in the active IPs list
          2. global_count / global_block_minutes (= the
             number_of_lowest_prices_for_switching / switching_block_minutes
             config keys)
          3. global_charging_count (= number_of_lowest_prices_for_charging)
             when even the global switching count is 0

        Returns a tuple (count, block_minutes) ready to feed into
        Itemlist.get_lowest_charging_blocks().
        """
        try:
            # self.ips is normalized to a list in __init__.
            ips_list = [
                p for p in self.ips if not p.startswith("!")
            ]
            position = ips_list.index(ip)
        except ValueError:
            position = -1

        per_ip_count = self._lookup_per_ip(
            self.lowest_prices_per_ip_raw, position
        )
        per_ip_minutes = self._lookup_per_ip(
            self.block_minutes_per_ip_raw, position
        )

        # Resolve count
        if per_ip_count is not None:
            count = per_ip_count
        elif global_count:
            count = global_count
        else:
            count = global_charging_count

        # Resolve block_minutes
        if per_ip_minutes is not None:
            block_minutes = per_ip_minutes
        else:
            block_minutes = global_block_minutes or 60

        # Snap block_minutes to a multiple of 15
        try:
            block_minutes = int(block_minutes)
        except (TypeError, ValueError):
            block_minutes = 60
        if block_minutes < 15:
            block_minutes = 15
        else:
            block_minutes = max(15, ((block_minutes + 7) // 15) * 15)

        return count, block_minutes

    @staticmethod
    def _lookup_per_ip(raw, position):
        """
        Pick the entry at `position` from a pipe-separated string.
        Returns None when:
          - raw is empty / not a string
          - position is out of range
          - the entry at position is empty (= "use global")
          - the entry can't be parsed as a number (treated as missing)

        Otherwise returns the parsed value as int (for count or minutes,
        both are integers in practice; decimal counts would need
        parse_int_or_float which we don't need here because the
        per-IP override is a simple integer count).
        """
        if not isinstance(raw, str) or not raw.strip():
            return None
        parts = raw.split("|")
        if position < 0 or position >= len(parts):
            return None
        entry = parts[position].strip()
        if not entry:
            return None
        # Try integer first, then float (for count thresholds like 0.85).
        try:
            return int(entry)
        except (TypeError, ValueError):
            try:
                return float(entry)
            except (TypeError, ValueError):
                return None

    def _filter_disabled_ips(self):
        """Filter disabled IPs (those starting with '!')."""
        active_ips = []

        for ip in self.ips:
            ip = ip.strip()
            if ip and not ip.startswith("!"):
                active_ips.append(ip)

        self.ips = active_ips
