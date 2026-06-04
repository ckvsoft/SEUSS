#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2026 Christian Kvasny chris(at)ckvsoft.at
#

"""
SolarForecastManager -- picks the right provider per evaluation cycle.

Configuration (config.solar_forecast_providers):
    [
      {"name": "OpenMeteo", "primary": true,  "enabled": true},
      {"name": "Solcast",   "primary": false, "enabled": true,
       "api_key": "...",     "resource_ids": "abcd-...",
       "min_interval_minutes": 90}
    ]

Selection logic:
  1. Primary provider goes first (the one with primary: true).
  2. If primary fails (returns None), try the next enabled non-primary.
  3. Stop at the first success.
  4. If all fail, return None and the caller keeps the previous values.

The "previous values" preservation is automatic because the base
class's forecast() method bails out WITHOUT writing zeros on
failure. So a transient open-meteo 502 with no Solcast fallback
just means "stats page keeps showing this morning's numbers" --
which is the right thing to do.

Backwards compatibility: if NO `solar_forecast_providers` config
block exists at all, fall back to OpenMeteo alone -- this matches
the old behaviour for anyone who hasn't migrated their config.
"""

from core.config import Config
from core.log import CustomLogger
from solar.openmeteo import OpenMeteo
from solar.solcast import Solcast


# Registry mapping the name string (case-insensitive) to the class.
# Adding a new provider = one new file + one entry here.
_PROVIDER_REGISTRY = {
    "openmeteo": OpenMeteo,
    "solcast": Solcast,
}


class SolarForecastManager:
    def __init__(self):
        self.config = Config()
        self.logger = CustomLogger()
        # Instantiate every known provider once -- they're cheap, and
        # we want their config-derived flags (enabled, primary, etc.)
        # ready for selection.
        self._providers = []
        for name, cls in _PROVIDER_REGISTRY.items():
            try:
                self._providers.append(cls())
            except Exception as e:
                self.logger.log.warning(
                    f"Failed to construct provider '{name}': {e}"
                )

    def _selection_order(self):
        """
        Returns the ordered list of provider instances to try, primary
        first. Providers with enabled=False are skipped entirely.
        """
        # Read the config block to see if it exists at all.
        cfg_block = getattr(self.config, "solar_forecast_providers", None)
        if cfg_block is None and hasattr(self.config, "get_solar_forecast_providers"):
            cfg_block = self.config.get_solar_forecast_providers()

        if not cfg_block:
            # Legacy: no providers configured -> OpenMeteo only.
            for p in self._providers:
                if isinstance(p, OpenMeteo):
                    return [p]
            return []

        # Normal: respect the user's enabled/primary settings.
        enabled = [p for p in self._providers if p.enabled]
        # Primary first, then the rest in registry order.
        enabled.sort(key=lambda p: (not p.primary, p.name.lower()))
        return enabled

    def forecast(self, solar_data):
        """
        Run the active provider's full forecast pipeline. Falls back
        to subsequent providers on failure. Returns the same dict
        shape as the legacy OpenMeteo.forecast() so existing callers
        in seusscore stay unchanged.
        """
        order = self._selection_order()
        if not order:
            self.logger.log.error(
                "SolarForecastManager: no enabled providers in config. "
                "Add at least one to solar_forecast_providers."
            )
            return {"current_hour": 0.0, "past_today": 0.0, "rest_today": 0.0}

        for provider in order:
            self.logger.log.debug(
                f"SolarForecastManager: trying provider '{provider.name}'"
            )
            result = provider.forecast(solar_data)
            if result is not None:
                return result
            self.logger.log.info(
                f"SolarForecastManager: '{provider.name}' returned no data, "
                f"trying next fallback if any."
            )

        # All providers failed. Don't overwrite the previous good values.
        self.logger.log.warning(
            "SolarForecastManager: all configured providers failed. "
            "Keeping previously stored forecast values."
        )
        return {"current_hour": 0.0, "past_today": 0.0, "rest_today": 0.0}
