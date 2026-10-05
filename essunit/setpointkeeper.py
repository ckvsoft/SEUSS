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
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE ARISING FROM
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#  THE SOFTWARE.
#
#  Project: [SEUSS -> Smart Ess Unit Spotmarket Switcher
#

"""
Setpoint-Keeper: haelt den hub4-RAM-Grid-Setpoint
(com.victronenergy.hub4 /Overrides/Setpoint) waehrend eines
Ladefensters im Takt frisch, damit das Laden komplett ohne
Scheduler/Day-Register laeuft.

Verifikation 2026-10-05 (live, v3.80):
  +W -> Netzbezug W (Batterie laedt), -W -> Feed-in, sofort.
  Override haelt ~180 s nach dem letzten Write, dann verfaellt er
  auf den persistierten /Settings/CGwacs/AcPowerSetPoint (interne
  ESS-Steuerung, normaler Selbstverbrauch) -- fail-safe.
  /Overrides/MaxDischargePower + ForceCharge werden dagegen von
  v3.80 ignoriert (Vestige, nicht mehr schreiben).

Setpoint pro Takt:  charge_power_w + max(0, last_w - pv_w)
  -> der Loop importiert genau das, Lasten laufen mit, die Batterie
  laedt konstant mit ~X; nie Feed-in (>= 0 geklemmt).
Fensterende: EIN 0-Write (gegen den 180-s-Nachlauf), dann Stille.
Alle internen Grenzen (BMS CCL, MaxChargeCurrent, Sustain) bleiben
aktiv.
"""

import json
import threading
import time

from core.log import CustomLogger
from core.mqttclient import MqttClient


class SetpointKeeper:
    """
    Haelt /Overrides/Setpoint im Takt nach, solange das Ladefenster
    aktiv ist (start()/stop() von set_charge()). Der Thread laeuft
    prozessweit (daemon); Last/PV liest er pro Takt aus dem
    PowerConsumption-Store, nicht aus dem 5-Min-Zyklus.
    """

    REFRESH_DEFAULT_S = 30

    def __init__(self, mqtt_config, unit_id, logger=None):
        self.logger = logger or CustomLogger()
        self.mqtt_config = mqtt_config
        self.unit_id = unit_id
        try:
            from core.config import Config
            cfg = Config()
            refresh = float(getattr(
                cfg, "setpoint_refresh_seconds", self.REFRESH_DEFAULT_S))
        except Exception:
            refresh = float(self.REFRESH_DEFAULT_S)
        self.refresh_s = max(5.0, refresh)

        self._topic = (
            f"W/{self.unit_id}/hub4/0/Overrides/Setpoint")
        self._client = None
        self._lock = threading.Lock()
        self._running = False
        self._wake = threading.Event()
        self._thread = None
        self._last_value = None
        self._stop_flag = False
        self._target_power = 0.0

    # ------------------------------------------------------------------
    # Public API (set_charge in essunit/victron.py)
    # ------------------------------------------------------------------

    def start(self, charge_power_w):
        """Fenster AN. Ruft den Refresh-Loop (einen Daemon-Thread)
        hoch und aktualisiert die Ziel-Ladeleistung."""
        if not charge_power_w or charge_power_w <= 0:
            return
        with self._lock:
            was_idle = not self._running
            self._target_power = float(charge_power_w)
            self._running = True
            self._stop_flag = False
            self._wake.set()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, daemon=True,
                    name=f"SetpointKeeper-{self.unit_id}")
                self._thread.start()
        if was_idle:
            self.logger.log.info(
                f"SetpointKeeper started: target "
                f"{charge_power_w:.0f} W, refresh {self.refresh_s:.0f} s.")
        else:
            self.logger.log.info(
                f"SetpointKeeper re-armed: target {charge_power_w:.0f} W.")

    def stop(self):
        """
        Fenster zu: einmalig 0 schreiben (kein ~180-s-Nachlauf), dann
        schweigt der Keeper bis zum naechsten start(). Wiederholte
        stop()-Aufrufe (pro Zyklus) sind ein No-op.
        """
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_flag = True
            self._wake.set()
        self.logger.log.info(
            "SetpointKeeper stopped -- releasing grid setpoint.")
        self._last_value = None

    def set_power(self, charge_power_w):
        """Ziel-Ladeleistung ohne Fensterwechsel aendern."""
        if not self._running:
            return
        self._target_power = float(charge_power_w)

    def shutdown(self):
        """Prozess-Ende: Thread beenden, 0-Write synchron absetzen."""
        with self._lock:
            self._running = False
            self._stop_flag = True
            self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        self._publish_setpoint(0.0)
        self._disconnect()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self):
        while True:
            with self._lock:
                active = self._running
                stop_requested = self._stop_flag
            if stop_requested and not active:
                # einmalig 0 schreiben, dann idle
                self._publish_setpoint(0.0)
                with self._lock:
                    self._stop_flag = False
                self._wake.clear()
                self._wake.wait()
                continue
            if not active:
                self._wake.clear()
                self._wake.wait()
                continue
            try:
                from core import statsmanager
                sm = statsmanager.StatsManager()
                lv = self._pair(sm.get_data(
                    "powerconsumption", "last_power_value"))
                pv = self._pair(sm.get_data(
                    "powerconsumption", "last_pv_power_value"))
                now = time.time()
                house = lv[0] if (now - lv[1]) <= 120.0 else 0.0
                pv_w = pv[0] if (now - pv[1]) <= 120.0 else 0.0
                house = max(0.0, float(house))
                pv_w = max(0.0, float(pv_w))
                target = max(0.0, self._target_power + house - pv_w)
                self._publish_setpoint(target)
            except Exception as e:
                self.logger.log.error(f"SetpointKeeper loop error: {e}")
            self._wake.wait(self.refresh_s)

    @staticmethod
    def _pair(val):
        """(value, ts)-Paar aus dem StatsManager-Store;
        Fallback (0, 0) bei jedem Format."""
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            try:
                return (float(val[0]), float(val[1]))
            except (TypeError, ValueError):
                pass
        try:
            return (float(val), 0.0)
        except (TypeError, ValueError):
            return (0.0, 0.0)

    def _ensure_client(self):
        if self._client is None:
            self._client = MqttClient(self.mqtt_config)
        return self._client

    def _publish_setpoint(self, watts):
        try:
            client = self._ensure_client()
            payload = json.dumps({"value": round(float(watts), 1)})
            rc = client.publish(self._topic, payload)
            if rc == 0:
                self._last_value = float(watts)
                self.logger.log.debug(
                    f"SetpointKeeper: setpoint -> {watts:.1f} W (rc=0).")
            else:
                self.logger.log.warning(
                    f"SetpointKeeper: publish rc={rc} ({self._topic}).")
        except Exception as e:
            self.logger.log.error(f"SetpointKeeper: publish failed: {e}")

    def _disconnect(self):
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
