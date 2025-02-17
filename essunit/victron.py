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
        self._get_data()

        # self.mqtt = MqttClient(self.mqtt_config)

    def handle_config_update(self, config_data):
        victron_ess_unit = next((ess for ess in config_data.get('ess_unit', []) if ess.get('name') == self._name), None)
        enabled_value = victron_ess_unit.get('enabled') if victron_ess_unit else False
        only_observation_value = victron_ess_unit.get('only_observation') if victron_ess_unit else False

        if not enabled_value or only_observation_value:
            self.logger.log.debug(f"ESS Unit {self._name} handle configuration change.")
            self.logger.log.info(f"ESS Unit {self._name} has been disabled or in observation mode.")
            self.logger.log.info(f"Charging mode is deactivated.")
            self.logger.log.info(f"Discharge mode is activated.")
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

    def get_battery_current_wh(self):
        soc = self.get_soc()
        full_capacity = (self.get_battery_capacity() / soc) * 100 if soc > 0 else 0.0
        battery_capacity_wh = full_capacity * 55.20
        battery_current_wh = ((soc or 0) / 100) * battery_capacity_wh
        self.logger.log.debug(f"{self._name} Batterie Current wh: {battery_current_wh}Wh")
        return battery_current_wh

    def get_battery_minimum_soc_limit(self):
        minimumsoclimit = self._process_result(self.subsribers.get('Battery', 'MinimumSocLimit'))
        self.logger.log.debug(f"{self._name} Batterie MinimumSocLimit: {minimumsoclimit}%")
        return minimumsoclimit

    def get_battery_capacity(self):
        capacity = self._process_result(self.subsribers.get('Battery', 'Capacity'))
        self.logger.log.debug(f"{self._name} Batterie capacity: {capacity} Ah")
        return capacity

    def get_battery_installed_capacity(self):
        installed_capacity = self._process_result(self.subsribers.get('Battery', 'InstalledCapacity'))
        self.logger.log.debug(f"{self._name} Batterie installed capacity: {installed_capacity} Ah")
        return installed_capacity

    def get_soc(self):
        soc = self._process_result(self.subsribers.get('Battery', 'Soc'))
        self.logger.log.info(f"{self._name} SOC: {soc}%")
        return soc

    def get_active_soc_limit(self):
        soc = self._process_result(self.subsribers.get('Control', 'ActiveSocLimit'))
        self.logger.log.info(f"{self._name} ActiveSocLimit: {soc}%")
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

    def get_grid_meters(self):
        meters = self.gridmeters
        return meters

    def get_solar_energy(self):
        inverters = self.inverters
        return inverters

    def get_version(self):
        version = self._process_result(self.subsribers.get('Firmware', 'Version'))
        return version

    def _gridmeters(self):
        with MqttClient(
                self.mqtt_config) as mqtt:  # Hier wird die Verbindung hergestellt und im Anschluss automatisch geschlossen
            base_topic = f'N/{self.unit_id}/grid'
            discovery_topic = f"{base_topic}/#"
            mqtt.subscribe(self.gridmeters, discovery_topic)

    def _inverters(self):
        with MqttClient(
                self.mqtt_config) as mqtt:  # Hier wird die Verbindung hergestellt und im Anschluss automatisch geschlossen
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
        self._inverters()
        self._gridmeters()
        with MqttClient(
                self.mqtt_config) as mqtt:  # Hier wird die Verbindung hergestellt und im Anschluss automatisch geschlossen
            instance = self._get_battery_instance(mqtt)
            topics_to_subscribe = [
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day",
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Duration",
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Soc",
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Start",
                f"Battery:N/{self.unit_id}/system/0/Dc/Battery/Soc",
                f"Control:N/{self.unit_id}/system/0/Control/ActiveSocLimit",
                f"DisCharge:N/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower",
                f"Battery:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/MinimumSocLimit",
                f"Battery:N/{self.unit_id}/battery/{instance}/Dc/0/Voltage",
                f"Battery:N/{self.unit_id}/battery/{instance}/Capacity",
                f"Battery:N/{self.unit_id}/battery/{instance}/InstalledCapacity",
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
            "PV_DC": f"N/{self.unit_id}/system/0/Dc/Pv/Power"
        }
        return mqtt_config