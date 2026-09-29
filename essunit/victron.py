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

import json
import os
import re
import socket
import sys
from typing import Tuple

from core.log import CustomLogger
from core.mqttclient import MqttClient, MqttResult, Subscribers, PvInverterResults, GridMetersResults
from essunit.abstract_classes.essunit import ESSUnit, ESSStatus
from core.config import Config


class Victron(ESSUnit):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.logger = CustomLogger()
        self.use_vrm = kwargs.get("use_vrm", False)
        self.unit_id = kwargs.get("unit_id", Config.find_venus_unique_id())
        self.ip_address = kwargs.get("ip_address", "venus.local")
        self.user = kwargs.get("user", "")
        self.password = kwargs.get("password", "")
        self.max_discharge_power = kwargs.get("max_discharge_power", -1)
        self.mqtt_port = 1883
        self.subsribers = Subscribers()
        self.inverters = PvInverterResults()
        self.gridmeters = GridMetersResults()

        self.config.converter_efficiency = self.get_converter_efficiency()

        current_directory = os.path.dirname(os.path.realpath(sys.argv[0]))
        certificate_path = os.path.join(current_directory, 'certificate')
        self.certificate = os.path.join(certificate_path, "venus-ca.crt")
        if self.unit_id and self.use_vrm:
            self.ip_address = self._get_vrm_broker_url()
            self._is_resolvable(self.ip_address)
            self.logger.log.info(f"ESS Unit {self._name}: Use VRM MQTT Server.")
            self.mqtt_port = 8883
        elif self.unit_id and self.ip_address and self._is_resolvable(self.ip_address):
            self.logger.log.info(f"ESS Unit {self._name}: Use local MQTT Server, valid local ipaddress found.")
        else:
            self.use_vrm = False

        self.mqtt_config = {
            "ip_adresse": self.ip_address,
            "user": self.user,
            "password": self.password,
            "certificate": self.certificate,
            "mqtt_port": self.mqtt_port,
            "unit_id": self.unit_id
        }
        # System pack voltage detection cache. Once detected, sticks
        # for the lifetime of the process so we don't relog on every
        # essunit cycle and don't flip if the pack briefly droops below
        # a band threshold under load. None = not yet detected.
        self._detected_pack_full_voltage = None

        # Control backend: "classic" (Schedule/Charge Day + MaxDischargePower
        # toggles) or "dynamic_ess" (Victron Dynamic ESS target-SOC slots).
        # Resolved via resolve_control_backend(); defaults to classic until
        # then so behaviour is unchanged for existing installs.
        self._control_backend = "classic"
        self._dess_last_slots = None
        self._dess_static_written = False
        self._get_data()

        # self.mqtt = MqttClient(self.mqtt_config)

    def handle_config_update(self, config_data):
        victron_ess_unit = next((ess for ess in config_data.get('ess_unit', []) if ess.get('name') == self._name), None)
        enabled_value = victron_ess_unit.get('enabled') if victron_ess_unit else False
        only_observation_value = victron_ess_unit.get('only_observation') if victron_ess_unit else False

        # Re-resolve the control backend on every config change so the
        # editor switch classic<->dynamic_ess takes effect without a
        # process restart.
        try:
            backend = self.resolve_control_backend(
                config_data.get("control_backend", "auto")
            )
            if backend != self._control_backend:
                self.logger.log.info(
                    f"Control backend changed: {self._control_backend} -> {backend}"
                )
                self._control_backend = backend
            if backend != "dynamic_ess":
                # Leaving the dynamic backend (or never having entered
                # it): make sure no stale Mode 4 keeps the scheduler
                # running headless without schedule updates.
                self.disable_dynamic_ess()
        except Exception as e:
            self.logger.log.warning(f"Control backend re-resolve failed: {e}")

        if not enabled_value or only_observation_value:
            self.logger.log.debug(f"ESS Unit {self._name} handle configuration change.")
            self.logger.log.info(f"ESS Unit {self._name} has been disabled or in observation mode.")
            self.logger.log.info(f"Charging mode is deactivated.")
            self.logger.log.info(f"Discharge mode is activated.")
            # Never leave the Dynamic ESS scheduler running when this
            # unit is no longer controlled (would follow a frozen plan).
            self.disable_dynamic_ess()
            self.set_charge('off')
            self.set_discharge('on')

    def get_battery_current_voltage(self):
        try:
            currentvoltage = self._process_result(self.subsribers.get('Battery', 'Voltage'))
            currentvoltage = round(float(currentvoltage), 2)
            self.logger.log.info(f"{self._name} Batterie Voltage: {currentvoltage} V")
            return currentvoltage
        except (TypeError, ValueError) as e:
            self.logger.log.warning(f"Error converting currentvoltage: {e}")
            currentvoltage = 0.0  # Setze einen Standardwert
            return currentvoltage

    def _detect_pack_full_voltage(self):
        """
        Auto-detect pack-full voltage (V) from the battery's current
        voltage. We classify into 12V / 24V / 48V LiFePO4 systems and
        return the corresponding "full" voltage (cell_count * 3.45V):

            48V (16S):  full = 55.20V   -> voltage in [35.0, ...]
            24V  (8S):  full = 27.60V   -> voltage in [17.5, 35.0)
            12V  (4S):  full =  13.80V  -> voltage in [ 8.0, 17.5)
            below 8V or no reading      -> 0.0  (don't guess)

        The Wh figures (cycles, RTE display, capacity tiles) want a
        STABLE pack voltage so they don't flip back and forth as the
        battery cycles between empty and full. We therefore detect
        once on first valid reading, log it, and cache the result for
        the lifetime of the process. If a later voltage falls into a
        different band (e.g. 48V system briefly droops to 39V under
        load -- still in "48V band" by our threshold; safe), the
        cache still wins.
        """
        if self._detected_pack_full_voltage is not None:
            return self._detected_pack_full_voltage

        v = self.get_battery_current_voltage() or 0
        if v >= 35.0:
            full = 55.20
            label = "48V"
        elif v >= 17.5:
            full = 27.60
            label = "24V"
        elif v >= 8.0:
            full = 13.80
            label = "12V"
        else:
            # No usable reading yet; return 0 but DON'T cache -- so
            # later calls retry until DBus delivers something useful.
            return 0.0

        self._detected_pack_full_voltage = full
        self.logger.log.info(
            f"{self._name} Detected {label} LiFePO4 system "
            f"(current voltage {v}V); using {full}V as pack-full "
            f"voltage for Wh calculations."
        )
        return full

    def get_battery_current_wh(self):
        soc = self.get_soc() or 0
        full_capacity = (self.get_battery_capacity() / soc) * 100 if soc > 0 else 0.0
        battery_capacity_wh = full_capacity * self._detect_pack_full_voltage()
        battery_current_wh = ((soc or 0) / 100) * battery_capacity_wh
        self.logger.log.debug(f"{self._name} Batterie Current wh: {battery_current_wh}Wh")
        return battery_current_wh

    def get_battery_full_wh(self):
        soc = self.get_soc() or 0
        full_capacity = (self.get_battery_capacity() / soc) * 100 if soc > 0 else 0.0
        battery_capacity_wh = full_capacity * self._detect_pack_full_voltage()
        self.logger.log.debug(f"{self._name} Batterie Full wh: {battery_capacity_wh}Wh")
        return battery_capacity_wh

    def get_battery_min_wh(self):
        min_soc_limit = self.get_battery_minimum_soc_limit() or 0
        battery_capacity_wh = self.get_battery_full_wh()
        return min_soc_limit / 100 * battery_capacity_wh

    def get_battery_minimum_soc_limit(self):
        minimumsoclimit = self._process_result(self.subsribers.get('Battery', 'MinimumSocLimit'))
        self.logger.log.debug(f"{self._name} Batterie MinimumSocLimit: {minimumsoclimit}%")
        return minimumsoclimit

    def get_battery_capacity(self):
        capacity = self._process_result(self.subsribers.get('Battery', 'Capacity'))

        if capacity is None:
            self.logger.log.warning(f"{self._name} Battery capacity not available")
            return 0.0  # or raise a controlled exception

        try:
            self.logger.log.debug(f"{self._name} Batterie capacity: {capacity} Ah")
            return float(capacity)
        except (TypeError, ValueError):
            self.logger.log.error(f"{self._name} Invalid battery capacity: {capacity}")
            return 0.0

    def get_battery_installed_capacity(self):
        installed_capacity = self._process_result(self.subsribers.get('Battery', 'InstalledCapacity'))
        self.logger.log.debug(f"{self._name} Batterie installed capacity: {installed_capacity} Ah")
        return installed_capacity

    def get_soc(self):
        soc = self._process_result(self.subsribers.get('Battery', 'Soc'))
        self.logger.log.debug(f"{self._name} SOC: {soc}%")
        return soc

    def get_active_soc_limit(self):
        soc = self._process_result(self.subsribers.get('Control', 'ActiveSocLimit'))
        self.logger.log.debug(f"{self._name} ActiveSocLimit: {soc}%")
        return soc

    def get_scheduler_soc(self):
        soc = self._process_result(self.subsribers.get('Schedule', 'Soc'))
        self.logger.log.info(f"{self._name} Scheduler SOC: {soc}%")
        return soc

    def set_active_soc_limit(self, value):
        try:
            current_value = self._process_result(self.subsribers.get('Control', 'ActiveSocLimit'))
            if value == current_value: return
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/MinimumSocLimit", value)
        except (TypeError, ValueError) as e:
            self.logger.log.error(f"Error: {e}")

    def set_discharge(self, status):
        try:
            if self._control_backend == "dynamic_ess":
                # Discharge enable/disable is expressed through the
                # Dynamic ESS schedule (target SOC per slot). The
                # MaxDischargePower register stays USER-OWNED as a pure
                # power limit -- SEUSS never stomps it in this backend.
                self.logger.log.debug(
                    "Dynamic ESS backend active -- set_discharge ignored "
                    "(schedule owns the discharge decision)."
                )
                return
            status_enum = ESSStatus(status.lower())
            value = self._process_result(self.subsribers.get('DisCharge', 'MaxDischargePower'))
            if status_enum == ESSStatus.ON:
                if value == self.max_discharge_power: return
                self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower", self.max_discharge_power)
            elif status_enum == ESSStatus.OFF:
                if value == 0: return
                self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower", 0)

        except (TypeError, ValueError) as e:
            self.logger.log.error(f"Error: {e}")

    def set_charge(self, status):
        try:
            if self._control_backend == "dynamic_ess":
                # In the Dynamic ESS backend the charge decision is
                # expressed through the target-SOC schedule (see
                # publish_dynamic_ess_schedule). The classic Day 7/-7
                # schedule toggle would interfere with the Dynamic ESS
                # scheduler -- Victron explicitly warns against mixing
                # scheduled charging with Dynamic ESS.
                self.logger.log.debug(
                    "Dynamic ESS backend active -- set_charge ignored "
                    "(schedule owns the charge decision)."
                )
                return
            status_enum = ESSStatus(status.lower())
            value = self._process_result(self.subsribers.get('Schedule', 'Day'))
            if status_enum == ESSStatus.ON:
                if value == 7: return
                self._set_scheduler()
                self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day", 7)
            elif status_enum == ESSStatus.OFF:
                if value == -7: return
                self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day", -7)

        except (TypeError, ValueError) as e:
            self.logger.log.error(f"Error: {e}")

    # ------------------------------------------------------------------
    # Control backend: "classic" (Schedule/Charge Day + MaxDischargePower
    # toggles via localsettings -- SD-backed) vs "dynamic_ess" (Victron
    # Dynamic ESS target-SOC schedule, Mode 4).
    #
    # Ownership rules:
    #   * classic      -- SEUSS owns the toggles; MaxDischargePower is
    #                     written per state flip (legacy behaviour).
    #   * dynamic_ess  -- SEUSS only pushes the schedule. The user keeps
    #                     MaxDischargePower as a pure POWER limit and
    #                     SEUSS never writes it; enable/disable is
    #                     expressed via the schedule's target SOC.
    # ------------------------------------------------------------------

    def set_control_backend(self, backend):
        previous = self._control_backend
        if backend not in ("classic", "dynamic_ess"):
            return
        self._control_backend = backend
        # Entering dynamic_ess: a classic cycle may have left
        # MaxDischargePower at 0 (discharge blocked). In this backend
        # SEUSS never touches the register again, so a leftover block
        # would permanently forbid discharge while the schedule assumes
        # a free battery -- restore the configured value ONCE.
        if backend == "dynamic_ess" and previous != "dynamic_ess" \
                and self.max_discharge_power != 0:
            try:
                current = self._process_result(
                    self.subsribers.get('DisCharge', 'MaxDischargePower'))
                if isinstance(current, (int, float)) and current == 0:
                    self._publish(
                        f"/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower",
                        self.max_discharge_power,
                    )
                    self.logger.log.info(
                        f"Dynamic ESS: restored MaxDischargePower -> "
                        f"{self.max_discharge_power} (classic leftover 0)."
                    )
            except Exception as e:
                self.logger.log.error(
                    f"Dynamic ESS: MaxDischargePower restore failed: {e}"
                )

    def get_control_backend(self):
        return self._control_backend

    def get_dynamic_ess_mode(self):
        """Current /Settings/DynamicEss/Mode value (None when the
        firmware does not expose the Dynamic ESS scheduler)."""
        return self._process_result(self.subsribers.get('DynamicEss', 'Mode'))

    def supports_dynamic_ess(self):
        """
        True when the GX firmware ships the Dynamic ESS scheduler and
        exposes its Mode setting. Per-slot strategy/restrictions are
        documented from 3.30~7 on; we require >= 3.60 for a safety
        margin, plus a readable /Settings/DynamicEss/Mode value.
        """
        version = self.get_version()
        try:
            digits = re.findall(r"\d+", str(version))
            major = int(digits[0]) if digits else 0
            minor = int(digits[1]) if len(digits) > 1 else 0
        except (TypeError, ValueError):
            return False
        if (major, minor) < (3, 60):
            return False
        return self.get_dynamic_ess_mode() is not None

    def resolve_control_backend(self, config):
        """
        Honour config.control_backend ("auto" | "classic" |
        "dynamic_ess"). "auto" picks dynamic_ess when the firmware
        supports it, classic otherwise. A forced dynamic_ess on an
        unsupported firmware falls back to classic WITH a warning
        instead of silently not controlling anything. Accepts either a
        config object or a raw backend string.
        """
        if isinstance(config, str):
            configured = config
        else:
            configured = getattr(config, "control_backend", "auto")
        if configured not in ("auto", "classic", "dynamic_ess"):
            configured = "auto"
        if configured == "classic":
            return "classic"
        if self.supports_dynamic_ess():
            return "dynamic_ess"
        if configured == "dynamic_ess":
            self.logger.log.warning(
                "control_backend=dynamic_ess requested but this VenusOS "
                f"(version {self.get_version()}) does not expose the Dynamic "
                "ESS scheduler -- falling back to classic."
            )
        return "classic"

    def publish_dynamic_ess_schedule(self, slots, battery_capacity_kwh=None,
                                     efficiency=None):
        """
        Push the hourly target-SOC slots into the Victron Dynamic ESS
        scheduler. Mode 4 is the mode Victron reserves for third-party
        controllers (VRM uses 1).

        * Mode=4 is written once (guarded against the current readback).
        * BatteryCapacity / SystemEfficiency are written once per
          process -- the GX-side controller needs both for its math and
          its capacity default is a bogus 2 kWh.
        * Only CHANGED slots are written: the previous schedule is kept
          in memory and diffed, so an unchanged plan costs zero
          settings writes.

        The schedule lives in localsettings (SD) like every Victron
        setting, but the diff-guard reduces this to a handful of writes
        per day -- and it replaces BOTH the Day 7/-7 toggle AND the
        MaxDischargePower 0/max toggle of the classic backend.
        """
        if not slots:
            return
        normalised = [
            {
                "start": int(s.get("start", 0)),
                "duration": int(s.get("duration", 3600)),
                "soc": round(float(s.get("soc", 0)), 1),
                "strategy": int(s.get("strategy", 0)),
                "allow_feed_in": int(s.get("allow_feed_in", 0)),
                "restrictions": int(s.get("restrictions", 0)),
            }
            for s in slots[:48]
        ]

        mode = self.get_dynamic_ess_mode()
        if mode != 4:
            self.logger.log.info(
                "Dynamic ESS: activating Mode 4 (third-party controller)."
            )
            self._publish(
                f"/{self.unit_id}/settings/0/Settings/DynamicEss/Mode", 4
            )

        writes = []
        if not self._dess_static_written:
            self._dess_static_written = True
            if battery_capacity_kwh and battery_capacity_kwh > 0:
                writes.append((
                    f"/{self.unit_id}/settings/0/Settings/DynamicEss/BatteryCapacity",
                    round(float(battery_capacity_kwh), 2),
                ))
            if efficiency and 0 < float(efficiency) <= 1:
                writes.append((
                    f"/{self.unit_id}/settings/0/Settings/DynamicEss/SystemEfficiency",
                    round(float(efficiency) * 100, 1),
                ))

        previous = self._dess_last_slots or []
        for i, slot in enumerate(normalised):
            if i < len(previous) and previous[i] == slot:
                continue
            base = f"/{self.unit_id}/settings/0/Settings/DynamicEss/Schedule/{i}"
            writes.append((f"{base}/Start", slot["start"]))
            writes.append((f"{base}/Duration", slot["duration"]))
            writes.append((f"{base}/Soc", slot["soc"]))
            writes.append((f"{base}/Strategy", slot["strategy"]))
            writes.append((f"{base}/AllowGridFeedIn", slot["allow_feed_in"]))
            writes.append((f"{base}/Restrictions", slot["restrictions"]))
        # Slots beyond the new horizon: clear so the scheduler cannot
        # follow a stale plan.
        for i in range(len(normalised), len(previous)):
            base = f"/{self.unit_id}/settings/0/Settings/DynamicEss/Schedule/{i}"
            writes.append((f"{base}/Start", 0))
            writes.append((f"{base}/Duration", 0))

        self._dess_last_slots = normalised
        if writes:
            self._publish_many(writes)
            self.logger.log.info(
                f"Dynamic ESS: published {len(normalised)} slots "
                f"({len(writes)} changed values)."
            )

    def disable_dynamic_ess(self):
        """
        Hand control back to plain ESS / the classic backend: set
        Dynamic ESS Mode to 0. Per Victron docs a stale non-zero mode
        without a matching schedule raises 'No matching schedule'
        alarms, so this MUST run when switching back to classic.
        """
        self._dess_last_slots = None
        mode = self.get_dynamic_ess_mode()
        if mode not in (None, 0):
            self.logger.log.info("Dynamic ESS: deactivating (Mode 0).")
            self._publish(
                f"/{self.unit_id}/settings/0/Settings/DynamicEss/Mode", 0
            )

    def _publish_many(self, topic_values):
        """
        Batch publish through ONE mqtt connection. _publish() opens a
        fresh MqttClient per value, which would mean one TCP+MQTT
        handshake per schedule value -- far too heavy for a full
        48-slot push.
        """
        if not topic_values:
            return
        with MqttClient(self.mqtt_config) as mqtt:
            for topic, value in topic_values:
                data = {"value": value}
                try:
                    rc = mqtt.publish(f"W{topic}", json.dumps(data))
                    self.logger.log.debug(
                        f"{self._name} DynamicEss publish rc={rc} {topic}"
                    )
                except Exception as e:
                    self.logger.log.error(
                        f"{self._name} DynamicEss publish failed {topic}: {e}"
                    )


    def get_grid_meters(self):
        meters = self.gridmeters
        return meters

    def get_solar_energy(self):
        inverters = self.inverters
        return inverters

    def get_max_charge_capability_w(self):
        """
        Charge power (W) the system can currently achieve, derived from
        live GX/BMS values: min(MaxChargeCurrent setting, BMS CCL) x
        pack voltage. Follows every setting or hardware change
        automatically (e.g. raising the charge current for a 3-phase
        retrofit) without any manual configuration. Returns None when
        nothing readable is available.
        """
        amps = []
        try:
            setting = self._process_result(
                self.subsribers.get('ChargeCap', 'MaxChargeCurrent'))
            if isinstance(setting, (int, float)) and setting > 0:
                amps.append(float(setting))
        except (TypeError, ValueError):
            pass
        try:
            ccl = self._process_result(
                self.subsribers.get('CCL', 'MaxChargeCurrent'))
            if isinstance(ccl, (int, float)) and ccl > 0:
                amps.append(float(ccl))
        except (TypeError, ValueError):
            pass
        try:
            voltage = float(self.get_battery_current_voltage() or 0)
        except (TypeError, ValueError):
            voltage = 0.0
        if not amps or voltage <= 0:
            return None
        return round(min(amps) * voltage, 1)

    def get_version(self):
        version = self._process_result(self.subsribers.get('Firmware', 'Version'))
        return version

    def _gridmeters(self, mqtt):
        base_topic = f'N/{self.unit_id}/grid'
        discovery_topic = f"{base_topic}/#"
        mqtt.subscribe(self.gridmeters, discovery_topic)

    def _inverters(self, mqtt):
        base_topic = f'N/{self.unit_id}/pvinverter'
        discovery_topic = f"{base_topic}/#"
        mqtt.subscribe(self.inverters, discovery_topic)

    def _get_battery_instance(self, mqtt):
        try:
            mqtt_result = MqttResult()
            rc = mqtt.subscribe(mqtt_result, f"N/{self.unit_id}/system/0/Batteries")
            if rc == 0:
                # Extrahieren des Werts
                batteries = self._process_result(mqtt_result.result)

                # Schleife durch die Batterien und finde die aktive Batterie
                for battery in batteries:
                    if battery.get('active_battery_service'):
                        instance = battery.get('instance')
                        return instance

                # Falls keine aktive Batterie gefunden wurde
                return None
        except (TypeError, json.JSONDecodeError) as e:
            self.logger.log.error(f"Error decoding JSON: {e}")
            return None

    def _set_scheduler(self):
        duration = self._process_result(self.subsribers.get('Schedule', 'Duration'))
        soc = self._process_result(self.subsribers.get('Schedule', 'Soc'))
        if duration != 0 and soc != 0: return
        if duration == 0:
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Duration", 86340)

        if soc == 0:
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Soc", 100)

    def _publish(self, topic, value):
        name = topic.split("/")[-1]
        data = {"value": value}
        with MqttClient(self.mqtt_config) as mqtt:
            mqtt_result = MqttResult()
            rc = mqtt.publish(f"W{topic}", json.dumps(data))
            self.logger.log.debug(f"{self._name} {name}: rc={rc}")
            if rc == 0:
                if mqtt.subscribe(mqtt_result, f"N{topic}") == 0:
                    value = self._process_result(mqtt_result.result)
                    self.logger.log.debug(f"{self._name}: {name} {value}")

    def _process_result(self, result):
        if result is None: return None
        parsed_result = json.loads(result)
        value = parsed_result.get('value')
        return value

    def _is_resolvable(self, ip_address):
        try:
            socket.gethostbyname(ip_address)
            return True
        except (socket.error, socket.gaierror) as e:
            self.logger.log.error(f"Error in name resolution: {e}")
            self.logger.log.error("Please check your network connection and Mqtt broker configuration.")
            raise ValueError("Error creating Victron instance: Unable to resolve IP address.")

    def _get_vrm_broker_url(self):
        sum = 0
        for character in self.unit_id.lower().strip():
            sum += ord(character)
        broker_index = sum % 128
        return "mqtt{}.victronenergy.com".format(broker_index)

    def _get_data(self):
        with MqttClient(
                self.mqtt_config) as mqtt:
            self._gridmeters(mqtt)
        with MqttClient(
                self.mqtt_config) as mqtt:
            self._inverters(mqtt)

        with MqttClient(
                self.mqtt_config) as mqtt:

            instance = self._get_battery_instance(mqtt)
            topics_to_subscribe = [
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day",
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Duration",
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Soc",
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Start",
                f"Battery:N/{self.unit_id}/system/0/Dc/Battery/Soc",
                f"Control:N/{self.unit_id}/system/0/Control/ActiveSocLimit",
                f"DisCharge:N/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower",
                f"DynamicEss:N/{self.unit_id}/settings/0/Settings/DynamicEss/Mode",
                f"Battery:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/MinimumSocLimit",
                f"Battery:N/{self.unit_id}/battery/{instance}/Dc/0/Voltage",
                f"Battery:N/{self.unit_id}/battery/{instance}/Capacity",
                f"Battery:N/{self.unit_id}/battery/{instance}/InstalledCapacity",
                f"ChargeCap:N/{self.unit_id}/settings/0/Settings/SystemSetup/MaxChargeCurrent",
                f"CCL:N/{self.unit_id}/battery/{instance}/Info/MaxChargeCurrent",
                f"Firmware:N/{self.unit_id}/platform/0/Firmware/Installed/Version"
            ]

            rc = mqtt.subscribe_multiple(self.subsribers, topics_to_subscribe)
            if rc == 0:
                if self.subsribers.count_topics(self.subsribers.subscribesValues) != self.subsribers.count_values(
                        self.subsribers.subscribesValues):
                    self.logger.log.error(f"Error: Not all required values were provided. Check your ESS settings.")
                    return

#                # Extrahieren des Werts
#                self.logger.log.info(f"{self._name} Schedule Charge: {self._process_result(self.subsribers.get('Schedule', 'Day'))}")
#                self.logger.log.info(f"{self._name} DisCharge: {self._process_result(self.subsribers.get('DisCharge', 'MaxDischargePower'))}")
#                self.logger.log.info(f"{self._name} Battery Voltage: {self._process_result(self.subsribers.get('Battery', 'Voltage'))}")
#                self.logger.log.info(f"{self._name} Battery Capacity: {self._process_result(self.subsribers.get('Battery', 'Capacity'))}")
#                self.logger.log.info(f"{self._name} Battery/SOC: {self._process_result(self.subsribers.get('Battery', 'Soc'))}%")
#                self.logger.log.info(f"{self._name} Schedule/Duration: {self._process_result(self.subsribers.get('Schedule', 'Duration'))}")
#                self.logger.log.info(f"{self._name} Schedule/Soc: {self._process_result(self.subsribers.get('Schedule', 'Soc'))}")
#                self.logger.log.info(f"{self._name} Battery/MinimumSocLimit: {self._process_result(self.subsribers.get('Battery', 'MinimumSocLimit'))}")
    def get_converter_efficiency(self) -> Tuple[float, float]:
        return 0.84, 0.90

    def get_config(self):
        mqtt_config = self.mqtt_config
        mqtt_config["type"] = "mqtt"
        mqtt_config["interval_duration"] = 5
        mqtt_config["unit_id"] = self.unit_id
        mqtt_config["keep_alive_topic"] = f"R/{self.unit_id}/keepalive"
        mqtt_config["topics"] = {
            "P_AC_consumption_L1": f"N/{self.unit_id}/system/0/Ac/Consumption/L1/Power",
            "P_AC_consumption_L2": f"N/{self.unit_id}/system/0/Ac/Consumption/L2/Power",
            "P_AC_consumption_L3": f"N/{self.unit_id}/system/0/Ac/Consumption/L3/Power",
            "number_of_phases": f"N/{self.unit_id}/system/0/Ac/Consumption/NumberOfPhases",
            "G_AC_consumption_L1": f"N/{self.unit_id}/system/0/Ac/Grid/L1/Power",
            "G_AC_consumption_L2": f"N/{self.unit_id}/system/0/Ac/Grid/L2/Power",
            "G_AC_consumption_L3": f"N/{self.unit_id}/system/0/Ac/Grid/L3/Power",
            "number_of_grid_phases": f"N/{self.unit_id}/system/0/Ac/Grid/NumberOfPhases",
            "P_DC_consumption_Battery":f"N/{self.unit_id}/system/0/Dc/Battery/Power",
            "PV_AC_OUT_L1":f"N/{self.unit_id}/system/0/Ac/PvOnOutput/L1/Power",
            "PV_AC_OUT_L2":f"N/{self.unit_id}/system/0/Ac/PvOnOutput/L2/Power",
            "PV_AC_OUT_L3":f"N/{self.unit_id}/system/0/Ac/PvOnOutput/L3/Power",
            "PV_AC_GRID_L1": f"N/{self.unit_id}/system/0/Ac/PvOnGrid/L1/Power",
            "PV_AC_GRID_L2": f"N/{self.unit_id}/system/0/Ac/PvOnGrid/L2/Power",
            "PV_AC_GRID_L3": f"N/{self.unit_id}/system/0/Ac/PvOnGrid/L3/Power",
            "PV_AC_GENSET_L1": f"N/{self.unit_id}/system/0/Ac/PvOnGenset/L1/Power",
            "PV_AC_GENSET_L2": f"N/{self.unit_id}/system/0/Ac/PvOnGenset/L2/Power",
            "PV_AC_GENSET_L3": f"N/{self.unit_id}/system/0/Ac/PvOnGenset/L3/Power",
            "PV_DC": f"N/{self.unit_id}/system/0/Dc/Pv/Power",
            "SOC": f"N/{self.unit_id}/system/0/Dc/Battery/Soc"
        }
        return mqtt_config