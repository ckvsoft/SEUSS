#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2025 Christian Kvasny chris(at)ckvsoft.at
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

        # Initial data subscription
        self._get_data()

    # ------------------------------------------------------------------
    # Configuration handling
    # ------------------------------------------------------------------
    def handle_config_update(self, config_data):
        victron_ess_unit = next((ess for ess in config_data.get('ess_unit', []) if ess.get('name') == self._name), None)
        enabled_value = victron_ess_unit.get('enabled') if victron_ess_unit else False
        only_observation_value = victron_ess_unit.get('only_observation') if victron_ess_unit else False

        if not enabled_value or only_observation_value:
            self.logger.log.info(f"ESS Unit {self._name} has been disabled or in observation mode.")
            self.set_charge('off')
            self.set_discharge('on')

    # ------------------------------------------------------------------
    # Battery values with safe fallback
    # ------------------------------------------------------------------
    def get_battery_current_voltage(self):
        return self._safe_float(self.subsribers.get('Battery', 'Voltage'))

    def get_battery_current_wh(self):
        soc = self.get_soc() or 0
        capacity = self.get_battery_capacity() or 0
        full_capacity = capacity * 55.20 if capacity > 0 else 0
        return (soc / 100.0 * full_capacity) if soc > 0 else 0.0

    def get_battery_full_wh(self):
        capacity = self.get_battery_capacity() or 0
        return capacity * 55.20

    def get_battery_min_wh(self):
        min_soc_limit = self.get_battery_minimum_soc_limit() or 0
        return min_soc_limit / 100 * self.get_battery_full_wh()

    def get_battery_minimum_soc_limit(self):
        return self._safe_float(self.subsribers.get('Battery', 'MinimumSocLimit'))

    def get_battery_capacity(self):
        return self._safe_float(self.subsribers.get('Battery', 'Capacity'))

    def get_battery_installed_capacity(self):
        return self._safe_float(self.subsribers.get('Battery', 'InstalledCapacity'))

    def get_soc(self):
        return self._safe_float(self.subsribers.get('Battery', 'Soc'))

    def get_active_soc_limit(self):
        return self._safe_float(self.subsribers.get('Control', 'ActiveSocLimit'))

    def get_scheduler_soc(self):
        return self._safe_float(self.subsribers.get('Schedule', 'Soc'))

    # ------------------------------------------------------------------
    # Control functions
    # ------------------------------------------------------------------
    def set_active_soc_limit(self, value):
        current_value = self.get_active_soc_limit()
        if value == current_value: return
        self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/MinimumSocLimit", value)

    def set_discharge(self, status):
        status_enum = ESSStatus(status.lower())
        value = self._safe_float(self.subsribers.get('DisCharge', 'MaxDischargePower'))
        if status_enum == ESSStatus.ON and value != self.max_discharge_power:
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower", self.max_discharge_power)
        elif status_enum == ESSStatus.OFF and value != 0:
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower", 0)

    def set_charge(self, status):
        status_enum = ESSStatus(status.lower())
        value = self._safe_float(self.subsribers.get('Schedule', 'Day'))
        if status_enum == ESSStatus.ON and value != 7:
            self._set_scheduler()
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day", 7)
        elif status_enum == ESSStatus.OFF and value != -7:
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day", -7)

    # ------------------------------------------------------------------
    # External data access
    # ------------------------------------------------------------------
    def get_grid_meters(self):
        return self.gridmeters

    def get_solar_energy(self):
        return self.inverters

    def get_version(self):
        return self._safe_float(self.subsribers.get('Firmware', 'Version'))

    # ------------------------------------------------------------------
    # MQTT helpers
    # ------------------------------------------------------------------
    def _gridmeters(self, mqtt):
        mqtt.subscribe(self.gridmeters, f"N/{self.unit_id}/grid/#")

    def _inverters(self, mqtt):
        mqtt.subscribe(self.inverters, f"N/{self.unit_id}/pvinverter/#")

    def _publish(self, topic, value):
        with MqttClient(self.mqtt_config) as mqtt:
            mqtt.publish(f"W{topic}", json.dumps({"value": value}))

    def _safe_float(self, raw):
        try:
            if raw is None: return 0.0
            value = json.loads(raw).get('value') if isinstance(raw, str) else raw
            return float(value)
        except Exception:
            return 0.0

    def _get_battery_instance(self, mqtt):
        try:
            mqtt_result = MqttResult()
            if mqtt.subscribe(mqtt_result, f"N/{self.unit_id}/system/0/Batteries") != 0:
                return None

            batteries = json.loads(mqtt_result.result).get('value', [])
            for battery in batteries:
                if battery.get('active_battery_service'):
                    return battery.get('instance')
        except Exception:
            pass
        return None

    def _get_data(self):
        with MqttClient(self.mqtt_config) as mqtt:
            self._gridmeters(mqtt)
            self._inverters(mqtt)
            instance = self._get_battery_instance(mqtt) or 0  # fallback auf 0

            topics_to_subscribe = [
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Day",
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Duration",
                f"Schedule:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Soc",
                f"Battery:N/{self.unit_id}/system/0/Dc/Battery/Soc",
                f"Control:N/{self.unit_id}/system/0/Control/ActiveSocLimit",
                f"DisCharge:N/{self.unit_id}/settings/0/Settings/CGwacs/MaxDischargePower",
                f"Battery:N/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/MinimumSocLimit",
                f"Battery:N/{self.unit_id}/battery/{instance}/Dc/0/Voltage",
                f"Battery:N/{self.unit_id}/battery/{instance}/Capacity",
                f"Battery:N/{self.unit_id}/battery/{instance}/InstalledCapacity",
                f"Firmware:N/{self.unit_id}/platform/0/Firmware/Installed/Version",
            ]

            mqtt.subscribe_multiple(self.subsribers, topics_to_subscribe)

    def _set_scheduler(self):
        duration = self._safe_float(self.subsribers.get('Schedule', 'Duration'))
        soc = self._safe_float(self.subsribers.get('Schedule', 'Soc'))
        if duration == 0:
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Duration", 86340)
        if soc == 0:
            self._publish(f"/{self.unit_id}/settings/0/Settings/CGwacs/BatteryLife/Schedule/Charge/0/Soc", 100)

    def _is_resolvable(self, ip_address):
        try:
            socket.gethostbyname(ip_address)
            return True
        except Exception as e:
            self.logger.log.error(f"Cannot resolve IP {ip_address}: {e}")
            return False

    def _get_vrm_broker_url(self):
        s = sum(ord(c) for c in self.unit_id.lower().strip())
        return f"mqtt{s % 128}.victronenergy.com"

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
            "P_DC_consumption_Battery": f"N/{self.unit_id}/system/0/Dc/Battery/Power",
            "PV_AC_OUT_L1": f"N/{self.unit_id}/system/0/Ac/PvOnOutput/L1/Power",
            "PV_AC_OUT_L2": f"N/{self.unit_id}/system/0/Ac/PvOnOutput/L2/Power",
            "PV_AC_OUT_L3": f"N/{self.unit_id}/system/0/Ac/PvOnOutput/L3/Power",
            "PV_AC_GRID_L1": f"N/{self.unit_id}/system/0/Ac/PvOnGrid/L1/Power",
            "PV_AC_GRID_L2": f"N/{self.unit_id}/system/0/Ac/PvOnGrid/L2/Power",
            "PV_AC_GRID_L3": f"N/{self.unit_id}/system/0/Ac/PvOnGrid/L3/Power",
            "PV_AC_GENSET_L1": f"N/{self.unit_id}/system/0/Ac/PvOnGenset/L1/Power",
            "PV_AC_GENSET_L2": f"N/{self.unit_id}/system/0/Ac/PvOnGenset/L2/Power",
            "PV_AC_GENSET_L3": f"N/{self.unit_id}/system/0/Ac/PvOnGenset/L3/Power",
            "PV_DC": f"N/{self.unit_id}/system/0/Dc/Pv/Power"
        }
        return mqtt_config
