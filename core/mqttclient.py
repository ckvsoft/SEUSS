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

import time
import re
import json
import paho.mqtt.client as mqtt
from datetime import datetime
from core.log import CustomLogger
from core.utils import Utils
from core.timeutilities import TimeUtilities

class MqttResult:
    def __init__(self):
        self.results = {}
        self.result = None

    def add_value(self, topic, value):
        self.result = value
        self.results[topic] = value

from core.statsmanager import StatsManager
class PvInverterResults(MqttResult):
    def __init__(self):
        super().__init__()
        self.results = {}
        self.inverters = {}
        # self.status = StatsManager()

    def add_value(self, topic, value):
        self.results[topic] = value
        self.add_pvinverter(topic, value)

    def add_pvinverter(self, topic, value):
        pattern = r'N/[^/]+/pvinverter/(\d+)/([^/]+)'

        # Verwenden Sie re.match, um den regulären Ausdruck auf die Zeichenkette anzuwenden
        match = re.match(pattern, topic)

        if match:
            device_id = int(match.group(1))  # Sie können den Wert als Integer konvertieren, wenn erforderlich
            keyword = match.group(2)

            if device_id not in self.inverters:
                self.inverters[device_id] = {}

            index = topic.find(keyword)

            if index != -1:
                result = topic[index:]
                if result == 'ProductName':
                    if result.lower() == "opentpu" or result.lower == "ahoi":
                        self.inverters[device_id]['PI'] = '{"value": 1000}'
                    else:
                        self.inverters[device_id]['PI'] = '{"value": 1000}'

                self.inverters[device_id][result] = value

    def get_forward_kwh(self, device_id):
        pi = self.get_value(device_id, 'PI')
        forward = self.get_value(device_id, 'Ac/Energy/Forward')
        if forward is None:
            return 0.0

        stats_manager_instance = StatsManager()
        stats_manager_instance.insert_new_daily_status_data("pvinverters", "forward_start", forward)
        forward_start = stats_manager_instance.get_data("pvinverters", "forward_start")
        forward = forward - forward_start
        return float(forward * pi)

    def get_value(self,device_id, key):
        if device_id in self.inverters and key in self.inverters[device_id]:
            value_str = self.inverters[device_id][key]
            return json.loads(value_str)['value']
        else:
            return None

class GridMetersResults(MqttResult):
    def __init__(self):
        super().__init__()
        self.results = {}
        self.gridmeters = {}
        # self.status = StatsManager()

    def add_value(self, topic, value):
        self.results[topic] = value
        self.add_gridmeters(topic, value)

    def add_gridmeters(self, topic, value):
        pattern = r'N/[^/]+/grid/(\d+)/([^/]+)'

        # Verwenden Sie re.match, um den regulären Ausdruck auf die Zeichenkette anzuwenden
        match = re.match(pattern, topic)

        if match:
            id = int(match.group(1))  # Sie können den Wert als Integer konvertieren, wenn erforderlich
            keyword = match.group(2)

            if id not in self.gridmeters:
                self.gridmeters[id] = {}

            index = topic.find(keyword)

            if index != -1:
                result = topic[index:]
                self.gridmeters[id][result] = value

    def get_forward_kwh(self, device_id):
        pi = 1000
        forward = self.get_value(device_id, 'Ac/Energy/Forward')
        if forward is None:
            return 0.0

        stats_manager_instance = StatsManager()
        stats_manager_instance.insert_new_daily_status_data("gridmeters", "forward_start", forward)
        forward_start = stats_manager_instance.get_data("gridmeters", "forward_start")
        if forward_start is None:
            return 0.0

        forward = forward - forward_start
        if forward < 0.0:
            stats_manager_instance.remove_data("gridmeters", "date_forward_start")
            stats_manager_instance.remove_data("gridmeters", "forward_start")
            stats_manager_instance.insert_new_daily_status_data("gridmeters", "forward_start", forward)
            return self.get_forward_kwh(device_id)

        return float(forward * pi)

    def get_hourly_kwh(self, device_id):
        forward = self.get_forward_kwh(device_id)
        now = TimeUtilities.get_now()

        midnight = datetime(now.year, now.month, now.day).astimezone(TimeUtilities.TZ)
        time_since_midnight = now - midnight

        # Umwandlung der vergangenen Zeit in Stunden
        hours_since_midnight = time_since_midnight.total_seconds() / 3600
        stats_manager_instance = StatsManager()
        return forward / hours_since_midnight

    def get_value(self,device_id, key):
        if device_id in self.gridmeters and key in self.gridmeters[device_id]:
            value_str = self.gridmeters[device_id][key]
            return json.loads(value_str)['value']
        else:
            return None

class Subscribers(MqttResult):
    def __init__(self):
        super().__init__()
        self.subscribesValues = {}
        self.subscribesTopics = {}
        self.logger = CustomLogger()

    def add_value(self, topic, value):
        group = self.find_group_by_topic(topic)
        if not group:
            return

        if group not in self.subscribesValues:
            self.subscribesValues[group] = {}

        key = topic.split("/")[-1]

        self.subscribesValues[group][key] = {'value': value, 'topic': topic}

    def find_group_by_topic(self, target_topic):
        for group, topics in self.subscribesValues.items():
            for key, data in topics.items():
                if data['topic'] == target_topic:
                    return group
        return None

    def remove_topic(self, group, key):
        """
        Löscht ein Thema mit allen Werten aus dem Dictionary.
        """
        if group in self.subscribesValues and key in self.subscribesValues[group]:
            del self.subscribesValues[group][key]

    def update_extract_group_topic(self, full_topic):
        parts = full_topic.split(':')
        group = parts[0]
        topic = parts[1]
        key = topic.split("/")[-1]

        # Entferne vorhandenes Thema mit allen Werten
        self.remove_topic(group, key)

        # Füge das Thema zu Subscribers hinzu
        if group not in self.subscribesValues:
            self.subscribesValues[group] = {}

        self.subscribesValues[group][key] = {'topic': topic}

        return group, topic

    def get(self, group, key):
        try:
            if group in self.subscribesValues and key in self.subscribesValues[group]:
                return self.subscribesValues[group][key]['value']
        except KeyError:
            self.logger.log_error(f"KeyError: The key {key} was not found.")
        return None

    def get_topic(self, full_key):
        group, key = full_key.split('/')
        if group in self.subscribesValues and key in self.subscribesValues[group]:
            return self.subscribesValues[group][key]['topic']
        return None

    def count_topics(self, data):
        topic_count = 0

        for key, value in data.items():
            if isinstance(value, dict):
                nested_topic_count = self.count_topics(value)
                topic_count += nested_topic_count
            elif key == 'topic':
                topic_count += 1

        return topic_count

    def count_values(self, data):
        values_count = 0

        for key, value in data.items():
            if isinstance(value, dict):
                nested_values_count = self.count_values(value)
                values_count += nested_values_count
            elif key == 'value':
                values_count += 1

        return values_count


class MqttClient:
    def __init__(self, mqtt_config):
        self.logger = CustomLogger()
        self.client = mqtt.Client(client_id=f"seuss-{Utils.generate_random_hex(8)}, protocol={mqtt.MQTTv5}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        self.client.on_log = self.on_log
        self.client.on_disconnect = self.on_disconnect
        self.flag_connected = False
        self.timeout = 30

        self.mqtt_broker = mqtt_config.get('ip_adresse', "")
        self.mqtt_port = mqtt_config.get('mqtt_port', 1883)
        self.user = mqtt_config.get('user', "")
        self.password = mqtt_config.get('password', "")
        self.certificate = mqtt_config.get('certificate', None)
        self.unit_id = mqtt_config.get('unit_id', "")

        self.response_topic = None
        self.response_payload = None
        self.subscribers_instance = Subscribers()

        if self.mqtt_port == 8883:
            self.ssl_context = None
            if self.mqtt_port == 8883:
                self.ssl_context = self._create_ssl_context()

            if self.ssl_context:
                self.client.tls_set_context(self.ssl_context)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.disconnect()

    def _create_ssl_context(self):
        """Create an SSL context for the MQTT connection."""
        context = None
        try:
            import ssl
            # Use PROTOCOL_TLS_CLIENT instead of deprecated PROTOCOL_TLS
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(self.certificate)
            context.check_hostname = True
        except ImportError:
            self.logger.log_error("SSL support not available.")
        return context

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.logger.log_debug(f"Connected with result code {rc}")
            query_message = ""
            query_topic = f"R/{self.unit_id}/system/0/Serial"
            self.client.publish(query_topic, query_message)
            self.logger.log_debug(f"on_connect query: {query_topic}")
            self.flag_connected = True
            self.subscribers_instance.flag_connected = True
        else:
            self.logger.log_error(f"Connection failed with code {rc}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        self.logger.log_debug(f"Received message on topic {topic}: {payload}")
        self.subscribers_instance.add_value(topic, payload)
        self.response_payload = payload


    def on_publish(self, client, userdata, mid):
        self.logger.log_debug(f"Message published {mid}")

    def on_log(self, client, userdata, level, buf):
        self.logger.log_debug(buf)

    def on_disconnect(self, client, userdata, rc):
        self.logger.log_debug("Client disconnected")
        self.flag_connected = False

    def subscribe_multiple(self, subscribers_instance, query_topics):
        self.subscribers_instance = subscribers_instance
        self.subscribers_instance.flag_connected = False

        try:
            if self.user:
                self.logger.log_debug(f"user: {self.user}, password: {self.password}")
                plain_password = Utils.decode_from_base64(self.password)
                self.client.username_pw_set(self.user, password=plain_password)

            if not self.connect():
                return 1

            self.client.loop_start()

            for query_topic in query_topics:
                group, actual_topic = subscribers_instance.update_extract_group_topic(query_topic)
                self.logger.log_debug(f"subscribe: {actual_topic}")
                self.client.subscribe(f"{actual_topic}")
                self.client.publish(f"R/{self.unit_id}/keepalive", "")

            start_time = time.time()

            while (
                    subscribers_instance.count_topics(subscribers_instance.subscribesValues)
                    > subscribers_instance.count_values(subscribers_instance.subscribesValues)
            ):
                if time.time() - start_time > self.timeout:
                    raise TimeoutError

                time.sleep(1)

            result = 0

        except TimeoutError:
            self.logger.log_warning("Timeout during the MQTT subscription process.")
            self.logger.log_debug(f"Timeout MQTT Topics: {query_topics}.")
            result = 1

        finally:
            self.client.loop_stop()
            self.disconnect()

        return result

    def subscribe(self, mqtt_result, query_topic):
        self.subscribers_instance = mqtt_result
        self.subscribers_instance.flag_connected = False
        self.logger.log_debug(f"query_topic: {query_topic}")
        try:
            if self.user:
                self.logger.log_debug(f"user: {self.user}, password: {self.password}")
                plain_password = Utils.decode_from_base64(self.password)
                self.client.username_pw_set(self.user, password=plain_password)

            if not self.connect():
                return 1

            self.client.loop_start()

            start_time = time.time()
            while not self.flag_connected:
                time.sleep(1)

                if time.time() - start_time > self.timeout:
                    self.logger.log_error("Timeout: Connection could not be established.")
                    raise TimeoutError

            self.logger.log_debug(f"subscribe: {query_topic}")
            self.client.subscribe(f"{query_topic}")
            self.client.publish(f"R/{self.unit_id}/keepalive", "")

            # Warten auf den Payload
            start_time = time.time()
            while self.response_payload is None:
                if time.time() - start_time > self.timeout:
                    raise TimeoutError
                time.sleep(1)

            time.sleep(1)
            payload = self.response_payload
            mqtt_result.result = payload
            self.logger.log_debug(f"result {payload}")
            result = 0

        except TimeoutError:
            self.logger.log_warning("Timeout during the MQTT subscription process.")
            self.logger.log_debug(f"Timeout MQTT Topic: {query_topic}.")
            result = 1

        finally:
            self.client.loop_stop()
            self.disconnect()

        return result

    def publish(self, query_topic, query_message):
        self.logger.log_debug(f"query_topic: {query_topic} {query_message}")
        try:
            if self.user:
                self.logger.log_debug(f"user: {self.user}, password: {self.password}")
                plain_password = Utils.decode_from_base64(self.password)
                self.client.username_pw_set(self.user, password=plain_password)

            if not self.connect():
                return 1

            self.client.loop_start()

            start_time = time.time()

            while not self.flag_connected:
                time.sleep(1)

                if time.time() - start_time > self.timeout:
                    self.logger.log_error("Timeout: Connection could not be established.")
                    raise TimeoutError

            self.logger.log_debug(f"publish: {query_topic} message: {query_message}")
            result = self.client.publish(query_topic, query_message)
            self.logger.log_debug(f"result rc: {result.rc}")
            result = result.rc

        except TimeoutError:
            self.logger.log_warning("Timeout during the MQTT publish process.")
            self.logger.log_debug(f"Timeout MQTT Topic: {query_topic}.")
            result = 1

        finally:
            self.client.loop_stop()
            self.disconnect()

        return result

    def connect(self):
        try:
            self.logger.log_debug(f"connect to: {self.mqtt_broker}:{self.mqtt_port}")
            self.client.connect(self.mqtt_broker, self.mqtt_port, 60)
            return True
        except ConnectionRefusedError:
            self.logger.log_error("Error: The connection to the MQTT broker was denied. Check the broker configuration.")
        except Exception as e:
            self.logger.log_error(f"Error: {e}")

        return False

    def disconnect(self):
        if self.client:
            self.client.disconnect()
