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
Setpoint-Keeper: die komplette SEUSS-Steuerung laeuft ueber den
RAM-Grid-Setpoint des hub4-Dienstes
(MQTT: W/<uid>/hub4/0/Overrides/Setpoint, {"value": <W>}).
Das MaxDischargePower-Setting wird als EINSTELLUNG behandelt
(GUI des Users), nicht als Schalter getoggelt.

Verifikation 2026-10-05 (live, v3.80):
  +W -> sofort Netzbezug W (Batterie laedt), -W -> Feed-in.
  Haltedauer nach dem letzten Write ~180 s; danach verfaellt der
  Override auf persistiertes /Settings/CGwacs/AcPowerSetPoint (10 W)
  = normaler Selbstverbrauch (fail-safe).
  Andere /Overrides/* (MaxDischargePower, ForceCharge, ...) werden
  von der Steuerlogik ignoriert (totes Vestige -- nie schreiben).

Modi (effective pro Takt):
  CHARGE  Ladefenster aktiv    -> X + max(0, Last - PV)
  FREE    Entlade-Entscheidung -> 0 (Selbstverbrauch; Batterie
                                 serviert die Lasten, kein Feed-in)
  HOLD    sonst (Sperre/Veto)  -> max(0, Last - PV) (Batterie haelt,
                                 Netz+PV servieren die Lasten)
  NONE    hands-off/Start      -> schweigen; Verfall -> neutral

Last/PV pro Takt aus dem GX-MQTT-Feed (zuletzt bekannte Werte; neue
Daten nachziehen, Stale >120 s nur WARNen und pinnen -- 0-Werte
wuerden in der Sperre den Akku aktiv leeren). Alle internen
Sicherheitsgrenzen (BMS CCL, MaxChargeCurrent, Sustain, AC-Voll-SOC)
bleiben aktiv (Hub4Mode=1).
"""

import json
import threading
import time

import paho.mqtt.client as mqtt

from core.log import CustomLogger
from core.utils import Utils

# Prozessweite Singletons: die essunit-Objekte werden pro
# Evaluationszyklus neu gebaut, der Keeper-Thread darf das NICHT.
_KEEPERS = {}
_REGISTRY_LOCK = threading.Lock()

MODE_NONE = "none"
MODE_HOLD = "hold"
MODE_FREE = "free"
MODE_CHARGE = "charge"

_FRESH_WINDOW_S = 120.0  # Frische-Fenster fuer Last/PV


def get_keeper(mqtt_config, unit_id, max_discharge_power, logger=None):
    """Prozess-Singleton fuer die unit_id; Thread startet einmal und
    lebt fuer die Prozessdauer (die essunit-Instanz stirbt pro Zyklus)."""
    key = str(unit_id)
    with _REGISTRY_LOCK:
        keeper = _KEEPERS.get(key)
        if keeper is None:
            keeper = SetpointKeeper(
                mqtt_config, unit_id, max_discharge_power, logger)
            _KEEPERS[key] = keeper
        return keeper


class SetpointKeeper:

    REFRESH_DEFAULT_S = 30

    def __init__(self, mqtt_config, unit_id, max_discharge_power,
                 logger=None):
        self.logger = logger or CustomLogger()
        self.mqtt_config = dict(mqtt_config or {})
        self.unit_id = unit_id
        self.max_discharge_power = max_discharge_power

        try:
            from core.config import Config
            refresh = float(getattr(
                Config(), "setpoint_refresh_seconds", self.REFRESH_DEFAULT_S))
        except Exception:
            refresh = float(self.REFRESH_DEFAULT_S)
        self.refresh_s = max(5.0, refresh)

        self._write_topic = f"W/{self.unit_id}/hub4/0/Overrides/Setpoint"
        self._keepalive_topic = f"R/{self.unit_id}/keepalive"

        # Reads/Writes auf die beiden SD-Settings (nur fuer die
        # einmaligen Legacy-Heals im Guard).
        self._day_reg_path = "/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day"
        self._discharge_reg_path = "/Settings/CGwacs/MaxDischargePower"

        # Live-Werte (GX pusht on change, nicht retained).
        self._consumption_topics = [
            f"N/{self.unit_id}/system/0/Ac/Consumption/L{p}/Power"
            for p in (1, 2, 3)
        ]
        self._pv_topics = [
            f"N/{self.unit_id}/system/0/Ac/PvOnOutput/L{p}/Power"
            for p in (1, 2, 3)
        ]
        self._read_reply_topic = f"N/{self.unit_id}/hub4/0/Overrides/Setpoint"

        self._client = None
        self._client_lock = threading.Lock()
        self._latest = {}  # topic -> (value, ts)
        self._latest_lock = threading.Lock()
        self._guard_done = False

        self._state_lock = threading.Lock()
        self._charge_open = False
        self._charge_power_w = 0.0
        self._discharge_wanted = False
        self._hands_off = False
        self._terminating = False
        self._wake = threading.Event()

        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f"SetpointKeeper-{self.unit_id}")
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API (set_charge / set_discharge in essunit/victron.py)
    # ------------------------------------------------------------------

    def set_charge(self, window_open, power_w=0.0):
        with self._state_lock:
            changed = window_open != self._charge_open
            self._charge_open = bool(window_open)
            if window_open and power_w and power_w > 0:
                if abs(power_w - self._charge_power_w) > 0.5:
                    changed = True
                self._charge_power_w = float(power_w)
        if changed:
            self.logger.log.info(
                f"Setpoint CHARGE {'on' if window_open else 'off'} "
                f"(target {self._charge_power_w:.0f} W).")

    def set_discharge(self, wanted):
        with self._state_lock:
            changed = wanted != self._discharge_wanted
            self._discharge_wanted = bool(wanted)
        if changed:
            self.logger.log.info(
                f"Setpoint {'FREE' if wanted else 'HOLD'} "
                f"(discharge {'on' if wanted else 'off'}).")

    def set_hands_off(self):
        """Kein Steuerrecht (disabled/observation): Schweigen dauerhaft."""
        with self._state_lock:
            was = not self._hands_off
            self._hands_off = True
            self._charge_open = False
            self._discharge_wanted = False
        if was:
            self.logger.log.info(
                "Setpoint hands-off: keeper stays silent "
                "(decay -> neutral).")

    def shutdown(self):
        """Prozess-Ende: Thread beenden, dann 0-Write, dann trennen."""
        with self._state_lock:
            self._terminating = True
            self._charge_open = False
            self._discharge_wanted = False
            self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        self._publish(self._write_topic, 0.0)
        self._disconnect()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self):
        while True:
            with self._state_lock:
                if self._terminating:
                    return
                hands_off = self._hands_off
                charge_open = self._charge_open
                power = self._charge_power_w
                discharge = self._discharge_wanted

            if hands_off:
                mode = MODE_NONE
            elif charge_open:
                mode = MODE_CHARGE
            elif discharge:
                mode = MODE_FREE
            else:
                mode = MODE_HOLD

            target = None
            if mode == MODE_CHARGE:
                house = self._sum(self._consumption_topics, "consumption")
                pv = self._sum(self._pv_topics, "pv")
                target = max(0.0, power + house - pv)
            elif mode == MODE_FREE:
                target = 0.0
            elif mode == MODE_HOLD:
                house = self._sum(self._consumption_topics, "consumption")
                pv = self._sum(self._pv_topics, "pv")
                target = max(0.0, house - pv)

            if mode != MODE_NONE:
                self._keep_alive()
                self._publish(self._write_topic, target)

            self._wake.clear()
            self._wake.wait(self.refresh_s)

    def _sum(self, topics, what):
        """Summe der zuletzt bekannten Phase-Werte. Bei Staleness die
        letzten Werte PINNEN (richtungssicher genug; 0 wuerde in der
        Sperre den Akku aktiv leeren), nur einmal pro 5 min WARNen."""
        with self._latest_lock:
            now = time.time()
            vals = [max(0.0, self._latest.get(t, (0.0, 0.0))[0])
                    for t in topics]
            stale = any(
                ts and (now - ts) > _FRESH_WINDOW_S
                for ts in (self._latest.get(t, (0.0, 0.0))[1]
                           for t in topics))
        if stale and (now - getattr(self, "_stale_warn_at", 0.0)) > 300.0:
            self._stale_warn_at = now
            self.logger.log.warning(
                f"keeper: stale {what} data >{int(_FRESH_WINDOW_S)}s -- "
                "pinning last values.")
        return sum(vals)

    def _ensure_client(self):
        with self._client_lock:
            if self._client is not None and self._client.is_connected():
                return self._client
            if self._client is not None:
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception:
                    pass
                self._client = None

            broker = self.mqtt_config.get("ip_adresse", "localhost")
            port = int(self.mqtt_config.get("mqtt_port", 1883))
            user = self.mqtt_config.get("user", "")
            client = mqtt.Client(
                client_id=f"seuss-setpoint-{Utils.generate_random_hex(8)}",
                protocol=mqtt.MQTTv5,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            if port == 8883:
                ctx = Utils.create_ssl_context(
                    self.mqtt_config.get("certificate"))
                if ctx:
                    client.tls_set_context(ctx)
            if user:
                client.username_pw_set(
                    user, Utils.decode_from_base64(
                        self.mqtt_config.get("password", "")))
            client.connect(broker, port, keepalive=60)
            client.loop_start()
            self._client = client
            return client

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        try:
            for topic in (self._consumption_topics + self._pv_topics
                          + [self._read_reply_topic]):
                client.subscribe(topic)
            self._apply_guards(client)
        except Exception as e:
            self.logger.log.error(f"keeper on_connect failed: {e}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            value = payload.get("value") if isinstance(payload, dict) else None
            if value is None:
                return
            value = float(value)
        except Exception:
            return
        with self._latest_lock:
            self._latest[msg.topic] = (value, time.time())

    def _keep_alive(self):
        try:
            client = self._ensure_client()
            info = client.publish(self._keepalive_topic, payload="1", qos=1)
            if info.rc != 0:
                self.logger.log.warning(
                    f"keeper keepalive rc={info.rc}")
        except Exception as e:
            self.logger.log.error(f"keeper keepalive failed: {e}")

    def _publish(self, topic, value):
        try:
            client = self._ensure_client()
            payload = json.dumps({"value": round(float(value), 1)})
            info = client.publish(topic, payload)
            if info.rc == 0:
                self.logger.log.debug(
                    f"keeper: {topic.split('/')[-1]} -> {float(value):.1f} W.")
            else:
                self.logger.log.warning(
                    f"keeper publish rc={info.rc} {topic}")
        except Exception as e:
            self.logger.log.error(f"keeper publish failed {topic}: {e}")

    def _apply_guards(self, client):
        """
        Einmalig pro Prozess, beim ersten Connect. Ziele:
          1. Legacy-Scheduler disarmen (Day=7 -> -7): der Scheduler ist
             mit dem Setpoint-Keeper kein Steuerkanal mehr.
          2. MaxDischargePower == 0 heilen (0 -> Config-Wert): eine
             alte, mid-flight gestorbene Sperre wuerde sonst die
             Entladung dauerhaft blocken. Danach GUI des Users.
        Danach schreibt SEUSS KEIN Setting mehr (nur den RAM-Setpoint).
        """
        if self._guard_done:
            return
        self._guard_done = True
        try:
            day = self._read_once(client, self._day_reg_path)
            if day == 7:
                self._write_sd(client, self._day_reg_path, -7)
                self.logger.log.info(
                    "Legacy scheduled charge disarmed (Day -> -7).")
        except Exception as e:
            self.logger.log.warning(f"keeper Day-guard failed: {e}")
        try:
            reg = self._read_once(client, self._discharge_reg_path)
            if reg == 0:
                self._write_sd(
                    client, self._discharge_reg_path,
                    self.max_discharge_power)
                self.logger.log.info(
                    f"MaxDischargePower heal: 0 -> "
                    f"{self.max_discharge_power} (einmalig).")
        except Exception as e:
            self.logger.log.warning(
                f"keeper MaxDischarge-guard failed: {e}")

    def _read_once(self, client, path):
        reply = {"done": False, "value": None}
        topic = f"N/{self.unit_id}{path}"

        def cb(c, u, m):
            try:
                reply["value"] = json.loads(m.payload.decode()).get("value")
            except Exception:
                reply["value"] = None
            reply["done"] = True

        client.message_callback_add(topic, cb)
        try:
            client.publish(f"R/{self.unit_id}{path}", "")
            start = time.time()
            while not reply["done"] and time.time() - start < 5.0:
                time.sleep(0.1)
        finally:
            client.message_callback_remove(topic)
        return reply.get("value")

    def _write_sd(self, client, path, value):
        client.publish(
            f"W/{self.unit_id}{path}", json.dumps({"value": value}))

    def _disconnect(self):
        with self._client_lock:
            if self._client is not None:
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception:
                    pass
                self._client = None
