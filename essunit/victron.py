#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024 Christian Kvasny chris(at)ckvsoft.at
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

from core.log import CustomLogger
from core.mqttclient import MqttClient, MqttResult, Subscribers, PvInverterResults, GridMetersResults
from essunit.abstract_classes.essunit import ESSUnit, ESSStatus, EssUnitNameResolutionError#
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
        self.forward_topics = []

        current_directory = os.path.dirname(os.path.realpath(sys.argv[0]))
        certificate_path = os.path.join(current_directory, 'certificate')
        self.certificate = os.path.join(certificate_path, "venus-ca.crt")
        if self.unit_id and self.use_vrm:
            self.ip_address = self._get_vrm_broker_url()
            self._is_resolvable(self.ip_address)
            self.logger.log_info(f"ESS Unit {self._name}: Use VRM MQTT Server.")
            self.mqtt_port = 8883
        elif self.unit_id and self.ip_address and self._is_resolvable(self.ip_address):
            self.logger.log_info(f"ESS Unit {self._name}: Use local MQTT Server, valid local ipaddress found.")
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

        # self.mqtt = MqttClient(self.mqtt_config)
    def handle_config_update(self, config_data):
        victron_ess_unit = next((ess for ess in config_data.get('ess_unit', []) if ess.get('name') == self._name), None)
        enabled_value = victron_ess_unit.get('enabled') if victron_ess_unit else None
        if not enabled_value:
            self.logger.log_debug(f"ESS Unit {self._name} handle configuration change.")
            self.logger.log_info(f"ESS Unit {self._name} has been disabled.")
            self.logger.log_info(f"Charging mode is deactivated.")
            self.logger.log_info(f"Discharge mode is activated.")
            self.set_charge('off')
            self.set_discharge('on')

        # print(f"Unit '{self._name}' is handling configuration change.")

    def get_test(self):
        subsribers = Subscribers()
        topics_to_subscribe = [f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/AllowDischarge",
                               f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day",
                               f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Duration",
                               f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Soc",
                               f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Start",
                               f"Battery:N/{self.unit_id}/system/0/Dc/Battery/Soc",
                               f"DisCharge:N/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower"]

        with MqttClient(self.mqtt_config) as mqtt:  # Hier wird die Verbindung hergestellt und im Anschluss automatisch geschlossen
            rc = mqtt.subscribe_multiple(subsribers, topics_to_subscribe)
            if rc == 0:
                if subsribers.count_topics(subsribers.subscribesValues) != subsribers.count_values(subsribers.subscribesValues):
                    self.logger.log_error(f"Error: Not all required values were provided. Check your ESS settings.")
                    return

                # Extrahieren des Werts
                self.logger.log_info(f"{self._name} MaxDischrgePower: {self._process_result(subsribers.get('DisCharge', 'MaxDischargePower'))}")
                self.logger.log_info(f"{self._name} Battery/SOC: {self._process_result(subsribers.get('Battery', 'Soc'))}%")
                self.logger.log_info(f"{self._name} Schedule/AllowDischarge: {self._process_result(subsribers.get('Schedule', 'AllowDischarge'))}")
                self.logger.log_info(f"{self._name} Schedule/Day: {self._process_result(subsribers.get('Schedule', 'Day'))}")
                self.logger.log_info(f"{self._name} Schedule/Duration: {self._process_result(subsribers.get('Schedule', 'Duration'))}")
                self.logger.log_info(f"{self._name} Schedule/Soc: {self._process_result(subsribers.get('Schedule', 'Soc'))}")
                self.logger.log_info(f"{self._name} Schedule/Start: {self._process_result(subsribers.get('Schedule', 'Start'))}")

    def get_soc(self):
        try:
            with MqttClient(self.mqtt_config) as mqtt:  # Hier wird die Verbindung hergestellt und im Anschluss automatisch geschlossen
                mqtt_result = MqttResult()
                rc = mqtt.subscribe(mqtt_result, f"N/{self.unit_id}/system/0/Dc/Battery/Soc")
                if rc == 0:
                    # Extrahieren des Werts
                    self.logger.log_info(f"{self._name} SOC: {self._process_result(mqtt_result.result)}%")
                return None
        except (TypeError, json.JSONDecodeError) as e:
            self.logger.log_error(f"Error decoding JSON: {e}")
            return None


    def set_discharge(self, status):
        try:
            status_enum = ESSStatus(status.lower())
            if status_enum == ESSStatus.ON:
                self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower", self.max_discharge_power)
            elif status_enum == ESSStatus.OFF:
                self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower", 0)

        except (TypeError, ValueError) as e:
            self.logger.log_error(f"Error: {e}")

    def set_charge(self, status):
        try:
            status_enum = ESSStatus(status.lower())
            if status_enum == ESSStatus.ON:
                self._set_scheduler()
                self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day", 7)
            elif status_enum == ESSStatus.OFF:
                self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day", -7)

        except (TypeError, ValueError) as e:
            self.logger.log_error(f"Error: {e}")

    def get_grid_meters(self):
        meters = self._gridmeters(f'N/{self.unit_id}/grid')
        return meters

    def _gridmeters(self, base_topic):
        discovery_topic = f"{base_topic}/#"
        with MqttClient(self.mqtt_config) as mqtt:
            gridmeters = GridMetersResults()
            mqtt.subscribe(gridmeters, discovery_topic)

            return gridmeters

    def get_solar_energy(self):
        inverters = self._inverters(f'N/{self.unit_id}/pvinverter')
        return inverters

    def _inverters(self, base_topic):
        discovery_topic = f"{base_topic}/#"
        with MqttClient(self.mqtt_config) as mqtt:
            inverters = PvInverterResults()
            mqtt.subscribe(inverters, discovery_topic)

            return inverters

    def _set_scheduler(self):
        subsribers = Subscribers()
        topics_to_subscribe = [f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/AllowDischarge",
                               f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day",
                               f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Duration",
                               f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Soc",
                               f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Start"]

        with MqttClient(self.mqtt_config) as mqtt:
            rc = mqtt.subscribe_multiple(subsribers, topics_to_subscribe)
            if rc == 0:
                if subsribers.get('Schedule', 'Duration') == 0:
                    self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Duration", 86340)

                if subsribers.get('Schedule', 'Soc') == 0:
                    self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Soc", 100)

    def _publish(self,topic, value):
        name = topic.split("/")[-1]
        data = {"value": value}
        with MqttClient(self.mqtt_config) as mqtt:
            mqtt_result = MqttResult()
            rc = mqtt.publish(f"W{topic}", json.dumps(data))
            self.logger.log_debug(f"{self._name} {name}: rc={rc}")
            if rc == 0:
                if mqtt.subscribe(mqtt_result, f"N{topic}") == 0:
                    value = self._process_result(mqtt_result.result)
                    self.logger.log_debug(f"{self._name}: {name} {value}")

    def _process_result(self, result):
        parsed_result = json.loads(result)
        value = parsed_result.get('value')
        return value

    def _is_resolvable(self, ip_address):
        try:
            socket.gethostbyname(ip_address)
            return True
        except (socket.error, socket.gaierror) as e:
            self.logger.log_error(f"Error in name resolution: {e}")
            self.logger.log_error("Please check your network connection and Mqtt broker configuration.")
            raise ValueError("Error creating Victron instance: Unable to resolve IP address.")

    def _get_vrm_broker_url(self):
        sum = 0
        for character in self.unit_id.lower().strip():
            sum += ord(character)
        broker_index = sum % 128
        return "mqtt{}.victronenergy.com".format(broker_index)

