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
import socket
import sys
from typing import Tuple

from core.log import CustomLogger
from core.mqttclient import MqttClient, MqttResult, Subscribers, PvInverterResults, GridMetersResults
from essunit.abstract_classes.essunit import ESSUnit, ESSStatus
from essunit.setpointkeeper import get_keeper
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
        # toggles). The former "dynamic_ess" backend was removed 2026-10:
        # its leftover /Settings/DynamicEss/Mode=4 disabled the classic
        # scheduled charging on VenusOS 3.7x. Only classic remains.
        self._control_backend = "classic"
        # SetpointKeeper: prozessweites Singleton (lazily via
        # self._keeper()); start/stopp durch set_charge/set_discharge.
        self._hub4_available = None      # None = not probed yet
        self._get_data()

        # self.mqtt = MqttClient(self.mqtt_config)

    def handle_config_update(self, config_data):
        victron_ess_unit = next((ess for ess in config_data.get('ess_unit', []) if ess.get('name') == self._name), None)
        enabled_value = victron_ess_unit.get('enabled') if victron_ess_unit else False
        only_observation_value = victron_ess_unit.get('only_observation') if victron_ess_unit else False

        # Re-resolve the control backend on every config change so the
        # editor switch takes effect without a process restart.
        try:
            backend = self.resolve_control_backend(
                config_data.get("control_backend", "auto")
            )
            if backend != self._control_backend:
                self.logger.log.info(
                    f"Control backend changed: {self._control_backend} -> {backend}"
                )
                self._control_backend = backend
        except Exception as e:
            self.logger.log.warning(f"Control backend re-resolve failed: {e}")

        if not enabled_value or only_observation_value:
            self.logger.log.debug(f"ESS Unit {self._name} handle configuration change.")
            self.logger.log.info(f"ESS Unit {self._name} has been disabled or in observation mode.")
            self.logger.log.info(f"Charging mode is deactivated.")
            self.logger.log.info(f"Discharge mode is activated.")
            if self.hub4_available():
                # No control authority: setpoint streaming off
                # (decay -> neutral); the SD setting stays untouched.
                self._keeper().set_hands_off()
            else:
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

    # ------------------------------------------------------------------
    # SetpointKeeper bridge: on hub4 firmware charging AND the
    # discharge-grant run through the RAM grid setpoint; the SD
    # settings (MaxDischargePower, scheduler Day/Duration/Soc) and
    # the ForceCharge override are no control channels.
    # ------------------------------------------------------------------

    def _keeper(self):
        """Process singleton (essunit objects are rebuilt per cycle)."""
        return get_keeper(
            self.mqtt_config, self.unit_id, self.max_discharge_power,
            logger=self.logger)

    def _keeper_charge_power_w(self):
        """
        Charge COMMAND side: a deliberately HIGH target -- the ESS
        loop self-regulates at the physical ceiling; commanding more
        than possible simply caps (user-verified live 2026-10-06: a
        32000 W setpoint charged at the system's full rate, and the
        old "measured 2628 W" was never a hardware limit, just the
        stored echo of our own earlier command). No measured/
        capability resolution here: a stored measured value is
        CIRCULAR on the command side -- it can only ratchet down,
        never up. The measured value stays on the PLANNING side
        (conditions._resolve_charge_power_w), where it measures the
        self-capped reality.
        """
        return 32000.0

    def set_manual_feedin(self, watts):
        """
        Manual grid feed-in (the UI slider). hub4 setpoint path only:
        the classic register backend has no feed-in channel. Returns
        True when the command reached the keeper.
        """
        if self.hub4_available():
            self._keeper().set_manual_feedin(watts)
            return True
        self.logger.log.warning(
            "Manual feed-in needs the hub4 setpoint path "
            "(firmware without hub4 or classic backend).")
        return False

    def get_manual_feedin(self):
        """(active, watts) of the manual grid feed-in."""
        if self.hub4_available():
            try:
                return self._keeper().get_manual_feedin()
            except Exception:
                return (False, 0.0)
        return (False, 0.0)

    def update_manual_guard(self, allowed, reason=""):
        """Cycle-side guard refresh for an active manual feed-in."""
        if self.hub4_available():
            try:
                self._keeper().update_manual_guard(allowed, reason)
            except Exception:
                pass

    def set_discharge(self, status):
        try:
            status_enum = ESSStatus(status.lower())
            if self.hub4_available():
                # Discharge grant via setpoint (FREE/HOLD); the SD
                # setting gets a one-time heal in the guard, never a
                # toggle from here.
                self._keeper().set_discharge(status_enum == ESSStatus.ON)
                return
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
            status_enum = ESSStatus(status.lower())
            if status_enum == ESSStatus.ON:
                if self.hub4_available():
                    self._keeper().set_charge(True, self._keeper_charge_power_w())
                else:
                    value = self._process_result(
                        self.subsribers.get('Schedule', 'Day'))
                    if value == 7: return
                    self._set_scheduler()
                    self._publish(
                        f"/{self.unit_id}/settings/0/Settings/CGwacs/"
                        "BatteryLife/Schedule/Charge/0/Day", 7)
            elif status_enum == ESSStatus.OFF:
                if self.hub4_available():
                    self._keeper().set_charge(False)
                else:
                    value = self._process_result(
                        self.subsribers.get('Schedule', 'Day'))
                    if value == -7: return
                    self._publish(
                        f"/{self.unit_id}/settings/0/Settings/CGwacs/"
                        "BatteryLife/Schedule/Charge/0/Day", -7)

        except (TypeError, ValueError) as e:
            self.logger.log.error(f"Error: {e}")

    def set_control_backend(self, backend):
        """
        Legacy shim -- older config.json files may carry
        control_backend="dynamic_ess" (or "auto"). Only "classic"
        exists; anything else resolves to classic.
        """
        if backend != "classic":
            self.logger.log.info(
                f"Control backend {backend!r} is no longer available -- "
                "using classic."
            )
        self._control_backend = "classic"

    def get_control_backend(self):
        return self._control_backend

    def resolve_control_backend(self, config):
        """
        Resolve the configured control backend. Only "classic" exists:
        the former dynamic_ess backend was removed (2026-10) -- its
        leftover /Settings/DynamicEss/Mode=4 disabled the classic
        scheduled charging on VenusOS 3.7x. Legacy config values
        ("auto", "dynamic_ess") resolve to classic.
        """
        if isinstance(config, str):
            configured = config
        else:
            configured = getattr(config, "control_backend", "classic")
        if configured not in ("auto", "classic", "dynamic_ess"):
            configured = "classic"
        if configured == "dynamic_ess":
            self.logger.log.info(
                "control_backend=dynamic_ess is no longer available -- "
                "using classic."
            )
        return "classic"

    def hub4_available(self):
        """
        True when the hub4 ESS control service answered (RAM override
        registers /Overrides/* available). Probed via the subscribed
        ProductName item; retried until it answers either way, so slow
        brokers are not misdetected as "old firmware".
        """
        if self._hub4_available is None:
            name = self._process_result(self.subsribers.get('Hub4', 'ProductName'))
            if name is not None:
                self._hub4_available = True
        return bool(self._hub4_available)

    def _publish_many(self, topic_values):
        """
        Batch publish through ONE mqtt connection. _publish() opens a
        fresh MqttClient per value -- use this when several registers
        must be written at once.
        """
        if not topic_values:
            return
        with MqttClient(self.mqtt_config) as mqtt:
            for topic, value in topic_values:
                data = {"value": value}
                try:
                    rc = mqtt.publish(f"W{topic}", json.dumps(data))
                    self.logger.log.debug(
                        f"{self._name} publish rc={rc} {topic}"
                    )
                except Exception as e:
                    self.logger.log.error(
                        f"{self._name} publish failed {topic}: {e}"
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

    def _publish(self, topic, value, retain=False):
        name = topic.split("/")[-1]
        data = {"value": value}
        with MqttClient(self.mqtt_config) as mqtt:
            mqtt_result = MqttResult()
            rc = mqtt.publish(f"W{topic}", json.dumps(data), retain=retain)
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
                f"Hub4:N/{self.unit_id}/hub4/0/ProductName",
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