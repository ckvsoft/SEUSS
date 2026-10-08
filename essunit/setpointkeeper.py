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
SetpointKeeper: the complete SEUSS control loop runs through the
hub4 RAM grid setpoint
(MQTT: W/<uid>/hub4/0/Overrides/Setpoint, {"value": <W>}).
The MaxDischargePower register stays a SETTING (the user's GUI),
never a toggled switch.

Live verification 2026-10-05 (v3.80):
  +W -> immediate grid import W (battery charges), -W -> feed-in.
  The override decays ~180 s after the last write and falls back to
  the persisted /Settings/CGwacs/AcPowerSetPoint (10 W) = normal
  self-consumption (fail-safe).
  All other /Overrides/* (MaxDischargePower, ForceCharge, ...) are
  ignored by the ESS control (vestige -- never write them).

Modes (effective per tick):
  CHARGE  charge window active  -> X + max(0, load - pv)
  FREE    discharge granted     -> mirror the persisted setpoint
                                   (self-consumption: battery serves
                                   the loads, no will of its own)
  HOLD    otherwise (veto/gap)   -> max(0, load - pv) (battery held,
                                   grid+PV serve the loads)
  MANUAL  manual slider active   -> an ABSOLUTE grid target
                                   -W (feed W into the grid; PV first,
                                   pack second -- the loop self-
                                   regulates at the physical cap, no
                                   load compensation). W = 0 is the
                                   grid-neutral hold: the setpoint is
                                   held at exactly 0 W (no import, no
                                   export). Outranks the automatic
                                   modes while active.
  NONE    hands-off/startup     -> silent; decay -> neutral

Grid demand limiter (demand charge): when enabled by the evaluation
cycle (set_demand_control), the CHARGE target is throttled so grid
charging never adds beyond a cap, and (with shaving) the HOLD/CHARGE
target is clamped to the hard limit so the internal loop discharges an
over-limit house load. The monthly maximum 15-min average therefore
never exceeds the hard limit unless the pack has no headroom (the SOC
floor is folded in cycle-side).

Load/PV per tick from the GX MQTT feed (last known values; new data
refreshes them, stale >120 s only WARNs and pins the last values --
zeros would actively drain the pack in HOLD). All internal safety
limits (BMS CCL, MaxChargeCurrent, Sustain, full-SOC stop) stay
enforced by the internal loop (Hub4Mode stays 1).
"""

import json
import threading
import time

import paho.mqtt.client as mqtt

from core.log import CustomLogger
from core.utils import Utils

# Process-wide singletons: the essunit objects are rebuilt every
# evaluation cycle -- the keeper thread must NOT be.
_KEEPERS = {}
_REGISTRY_LOCK = threading.Lock()

MODE_NONE = "none"
MODE_HOLD = "hold"
MODE_FREE = "free"
MODE_CHARGE = "charge"
MODE_MANUAL = "manual"

# The manual overlay's wire/slider protocol: any negative value (the
# slider's -1 position) means "deactivated", 0 means "hold the grid at
# 0 W", a positive value is the feed-in wattage.
MANUAL_OFF = -1.0

_FRESH_WINDOW_S = 120.0  # freshness window for load/pv


def get_keeper(mqtt_config, unit_id, max_discharge_power, logger=None):
    """Process singleton per unit_id; the thread starts once and
    lives for the process lifetime (essunit instances die per cycle)."""
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

        # Reads/writes for the two SD settings (only for the
        # one-time legacy heals in the guard).
        self._day_reg_path = "/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day"
        self._discharge_reg_path = "/Settings/CGwacs/MaxDischargePower"

        # Live values (the GX pushes on change, not retained).
        self._consumption_topics = [
            f"N/{self.unit_id}/system/0/Ac/Consumption/L{p}/Power"
            for p in (1, 2, 3)
        ]
        self._pv_topics = [
            f"N/{self.unit_id}/system/0/Ac/PvOnOutput/L{p}/Power"
            for p in (1, 2, 3)
        ]
        self._read_reply_topic = f"N/{self.unit_id}/hub4/0/Overrides/Setpoint"
        # The persisted grid setpoint (a SETTING of the system/user):
        # FREE mirrors it instead of imposing anything of its own.
        self._neutral_topic = (
            f"N/{self.unit_id}/settings/0/Settings/CGwacs/AcPowerSetPoint")

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
        # Manual grid overlay (the UI slider): inactive by default.
        # Active with _manual_feedin_w == 0 -> grid-neutral hold,
        # > 0 -> feed that many watts into the grid.
        self._manual_active = False
        self._manual_feedin_w = 0.0
        # Grid demand limiter (demand charge). Zeroed/off by default;
        # the evaluation cycle pushes fresh values every tick via
        # set_demand_control(). hard = absolute import ceiling (W),
        # charge = soft charge cap (W, 0 = off), shaving = allow battery
        # discharge to shave an over-limit house load.
        self._demand_hard_w = 0.0
        self._demand_charge_w = 0.0
        self._demand_shaving = False
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
        """No control authority (disabled/observation): silent forever."""
        with self._state_lock:
            was = not self._hands_off
            self._hands_off = True
            self._charge_open = False
            self._discharge_wanted = False
            self._manual_active = False
            self._manual_feedin_w = 0.0
        if was:
            self.logger.log.info(
                "Setpoint hands-off: keeper stays silent "
                "(decay -> neutral).")

    def set_manual_feedin(self, watts):
        """
        Manual grid overlay (the UI slider). Three states:
          watts < 0  -> deactivated: release the setpoint back to the
                        automatic modes (the persisted system setpoint
                        applies again).
          watts == 0 -> active, GRID-NEUTRAL: hold the setpoint at
                        exactly 0 W (no import, no export; the pack/PV
                        serve the loads). Unlike "deactivated" this
                        overrides the persisted setpoint -- the loop
                        never falls back to it.
          watts > 0  -> active: feed `watts` INTO the grid (-W target).
        Overrides the automatic modes while active; a guard
        (update_manual_guard) or the process dying (the ~180 s
        override decay) ends it. hands_off still wins -- no control
        authority means no manual overlay either.
        """
        try:
            watts = float(watts)
        except (TypeError, ValueError):
            watts = MANUAL_OFF
        if watts < 0.0:
            active, watts = False, 0.0
        else:
            active = True
        with self._state_lock:
            changed = (active != self._manual_active
                       or abs(watts - self._manual_feedin_w) > 0.5)
            self._manual_active = active
            self._manual_feedin_w = watts
        if changed:
            if not active:
                self.logger.log.info(
                    "Setpoint MANUAL overlay off (automatic modes "
                    "resume).")
            elif watts > 0:
                self.logger.log.info(
                    f"Setpoint MANUAL FEEDIN on ({watts:.0f} W).")
            else:
                self.logger.log.info(
                    "Setpoint MANUAL GRID-NEUTRAL on (holding 0 W).")
        self._wake.set()

    def get_manual_feedin(self):
        """(active, watts) of the manual grid overlay: active with
        watts == 0 is the grid-neutral hold, watts > 0 the feed-in."""
        with self._state_lock:
            return (self._manual_active, self._manual_feedin_w)

    def set_demand_control(self, hard_limit_w=0.0, charge_target_w=0.0,
                           shaving=False):
        """
        Grid demand limiter (demand charge). Pushed by the evaluation
        cycle each tick (the keeper is a process singleton and does NOT
        re-read config):

          hard_limit_w    absolute grid-import ceiling in W. 0 = off.
                          Applied to CHARGE (own contribution) and, when
                          shaving is on, to HOLD (forces battery discharge
                          of the house-load excess). The monthly maximum
                          15-min average can therefore never exceed it
                          (unless the pack has no headroom).
          charge_target_w soft charge cap in W (0 = off): the CHARGE
                          target is throttled to this so grid-charging
                          plus the house load stays at/below it. Purely
                          additive-by-us; never forces discharge.
          shaving         allow the battery to discharge to keep the
                          grid import <= hard_limit_w in HOLD/CHARGE.
                          The cycle already folded the SOC floor in.
        """
        try:
            hard = max(0.0, float(hard_limit_w or 0.0))
            charge = max(0.0, float(charge_target_w or 0.0))
        except (TypeError, ValueError):
            hard, charge = 0.0, 0.0
        with self._state_lock:
            changed = (abs(hard - self._demand_hard_w) > 0.5
                       or abs(charge - self._demand_charge_w) > 0.5
                       or bool(shaving) != self._demand_shaving)
            self._demand_hard_w = hard
            self._demand_charge_w = charge
            self._demand_shaving = bool(shaving)
        if changed:
            self.logger.log.info(
                f"Grid demand control: limit {hard:.0f} W, "
                f"charge-cap {charge:.0f} W, "
                f"shaving {'on' if shaving else 'off'}.")
            self._wake.set()

    def get_demand_control(self):
        """(hard_limit_w, charge_target_w, shaving) currently applied."""
        with self._state_lock:
            return (self._demand_hard_w, self._demand_charge_w,
                    self._demand_shaving)

    def update_manual_guard(self, allowed, reason=""):
        """
        Guard refresh from the evaluation cycle (price/SOC floors).
        A REFUSED guard ends an active manual overlay (logged why);
        an allowed guard never starts one -- only the slider does.
        """
        with self._state_lock:
            active = self._manual_active
            if active and not allowed:
                self._manual_active = False
                self._manual_feedin_w = 0.0
        if active and not allowed:
            self.logger.log.info(
                f"Setpoint MANUAL overlay off (guard: {reason or 'refused'}).")
        self._wake.set()

    def shutdown(self):
        """Process end: stop the thread, then one 0-write, then disconnect."""
        with self._state_lock:
            self._terminating = True
            self._charge_open = False
            self._discharge_wanted = False
            self._manual_active = False
            self._manual_feedin_w = 0.0
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
                manual_active = self._manual_active
                manual_w = self._manual_feedin_w
                charge_open = self._charge_open
                power = self._charge_power_w
                discharge = self._discharge_wanted
                demand_hard = self._demand_hard_w
                demand_charge = self._demand_charge_w
                demand_shaving = self._demand_shaving

            if hands_off:
                mode = MODE_NONE
            elif manual_active:
                mode = MODE_MANUAL
            elif charge_open:
                mode = MODE_CHARGE
            elif discharge:
                mode = MODE_FREE
            else:
                mode = MODE_HOLD

            target = None
            if mode == MODE_MANUAL:
                # Manual overlay: an ABSOLUTE grid target, no load
                # compensation -- the loop pulls PV first and the rest
                # from the pack, self-regulating at the physical cap
                # (same evidence as the charge path: commanding more
                # than possible simply caps). w == 0 is the grid-
                # neutral hold: the setpoint is held at exactly 0 W,
                # so the loop never falls back to the persisted value.
                target = -float(manual_w)
            elif mode == MODE_CHARGE:
                house = self._sum(self._consumption_topics, "consumption")
                pv = self._sum(self._pv_topics, "pv")
                base = max(0.0, house - pv)
                # Grid demand cap (demand charge). The effective charge
                # cap is the smaller of the hard ceiling and the soft
                # charge target (0 = not set). We add AT MOST up to the
                # cap on top of the house load -- we never force discharge
                # here; that is the shaving clamp below.
                target = self._demand_charge_target(
                    base, power, demand_hard, demand_charge)
            elif mode == MODE_FREE:
                # FREE mirrors the persisted grid setpoint (a SETTING);
                # unknown -> silent (decay falls back to the same one).
                val = self._latest.get(self._neutral_topic, (None,))[0]
                if isinstance(val, (int, float)):
                    target = float(val)
                else:
                    mode = MODE_NONE
            elif mode == MODE_HOLD:
                house = self._sum(self._consumption_topics, "consumption")
                pv = self._sum(self._pv_topics, "pv")
                target = max(0.0, house - pv)

            # Peak-shaving: when the battery may shave and the load alone
            # would push the grid import over the hard limit, lower the
            # target so the internal loop discharges the excess. Only the
            # import side is touched (min), never a feed-in command.
            if (demand_shaving and demand_hard > 0
                    and target is not None
                    and mode in (MODE_CHARGE, MODE_HOLD)):
                target = min(target, demand_hard)

            if mode != MODE_NONE:
                self._keep_alive()
                self._publish(self._write_topic, target)

            self._wake.clear()
            self._wake.wait(self.refresh_s)

    @staticmethod
    def _demand_charge_target(base_w, power_w, hard_w, charge_cap_w):
        """
        Grid-import target (W) for CHARGE mode under the demand cap.

          base_w   house load minus PV (what the grid would serve idle)
          power_w  the commanded charge power (32000, self-regulating)
          hard_w   absolute import ceiling (0 = off)
          charge_cap_w soft charge cap (0 = off)

        The effective cap is min(hard, soft). We add at most (cap - base)
        of charge on top of the house load, so the target never exceeds
        the cap through our own charging and we never force discharge
        (when base > cap the target stays at base -- the shaving clamp in
        _run handles the over-limit case separately).
        """
        cap = hard_w if hard_w > 0 else float("inf")
        if charge_cap_w > 0:
            cap = min(cap, charge_cap_w)
        if cap == float("inf"):
            return base_w + power_w
        return base_w + min(power_w, max(0.0, cap - base_w))

    def _sum(self, topics, what):
        """Sum of the last known phase values. On staleness the last
        values get PINNED (direction-safe enough; zeros would
        actively drain the pack in HOLD), one WARN per 5 min."""
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
                          + [self._neutral_topic, self._read_reply_topic]):
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
        Once per process, at the first connect:
          1. Disarm a legacy scheduler (Day=7 -> -7): with the
             SetpointKeeper it is no longer a control channel.
          2. Heal MaxDischargePower == 0 (0 -> config value): a stale
             block left behind by a mid-flight death would otherwise
             block discharge forever. The register is the user's GUI
          after that.
        From then on SEUSS never writes a setting again (only the
        RAM setpoint).
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
                    f"{self.max_discharge_power} (one-time).")
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
