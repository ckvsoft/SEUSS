
import socket
import time
import threading
import paho.mqtt.client as mqtt
import json

from core.utils import Utils
from powerconsumption.abstract_classes.powerconsumption import PowerConsumptionBase

class PowerConsumptionMQTT(PowerConsumptionBase):
    def __init__(self, interval_duration=5, mqtt_config=None):
        super().__init__(interval_duration)
        self.keep_alive_running = False

        # MQTT configuration
        self.broker = None
        self.port = None
        self.unit_id = None
        self.keep_alive_topic = None
        self.data_topics = {}
        self.mqtt_config = mqtt_config

        # MQTT client
        self.client = None

        self.update_config(mqtt_config)

    def update_config(self, mqtt_config=None):
        """Sets the MQTT configuration, reconnects the client, and updates the topics."""
        broker = mqtt_config.get("ip_adresse", "localhost")
        port = mqtt_config.get("mqtt_port", 1883)
        user = mqtt_config.get('user', "")
        password = mqtt_config.get('password', "")
        certificate = mqtt_config.get('certificate', None)
        unit_id = mqtt_config.get('unit_id', "")

        if self.client:
            # If a client exists, compare the current and new configuration
            if broker == self.broker and port == self.port and unit_id == self.unit_id:
                self.logger.log.debug("MQTT config unchanged. No reconnection needed.")
                return

            self.logger.log.debug("MQTT config changed. Reconnecting client...")
            self.client.disconnect()
            self.client = None

        # Save new configuration
        if not broker:
            return

        self.broker = broker
        self.port = port
        self.unit_id = unit_id

        # Set topics based on the new unit_id
        self.keep_alive_topic = mqtt_config.get("keep_alive_topic", "")
        self.data_topics = mqtt_config.get("topics")

        # Initialize MQTT client
        self.client = mqtt.Client(client_id=f"seuss-power-consumption-{Utils.generate_random_hex(8)}",
                                  protocol=mqtt.MQTTv5,
                                  callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        if port == 8883:
            ssl_context = Utils.create_ssl_context(certificate)
            if ssl_context:
                self.client.tls_set_context(ssl_context)

        try:
            if user:
                plain_password = Utils.decode_from_base64(password)
                self.client.username_pw_set(user, password=plain_password)

            self.client.connect(self.broker, self.port, keepalive=60)
            self.logger.log.debug("Connected to MQTT broker.")
        except socket.gaierror as e:
            self.logger.log.error(f"Network error: {e}. Broker hostname could not be resolved.")
        except ConnectionRefusedError as e:
            self.logger.log.error(f"Connection refused: {e}. Is the broker online?")
        except Exception as e:
            self.logger.log.error(f"Unexpected error: {e}")

    def on_message(self, client, userdata, msg):
        """Callback for incoming MQTT messages"""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            self.logger.log.error(f"JSON decoding error for payload: {msg.payload}")
            return

        if topic in self.data_topics.values():
            topic_key = next((k for k, v in self.data_topics.items() if v == topic), None)
            self.handler.update_values(topic_key, payload)

            if self.handler.all_required_data_complete() and self.handler.check_for_data():
                self.current_power = self.handler.get_power("AC_POWER")
                self.current_grid_power = self.handler.get_power("AC_GRID_POWER")
                self.P_DC_consumption_Battery = self.handler.get_power("BATTERY_POWER")
                self.soc = self.handler.get_power("SOC")
                timestamp = time.time()
                self.update(self.current_power, self.current_grid_power, self.P_DC_consumption_Battery, timestamp)

    def on_disconnect(self, client, userdata, *args):
        """Universal disconnect callback compatible with all Paho versions"""
        self.logger.log.debug(f"Disconnected from MQTT broker. Args: {args}")

    def send_keep_alive(self):
        """Send periodic keep-alive messages to the broker"""
        while self.keep_alive_running:
            time.sleep(self.interval_duration)
            if self.client and self.keep_alive_running:
                if self.client.is_connected():
                    cost = self.energy_costs_by_hour.get(str(self.current_hour), 0.0)
                    total_cost = sum(self.energy_costs_by_hour.values())
                    self.energy_costs_by_day[str(self.current_day)] = total_cost

                    value = self.handler.get_power("TOTAL_POWER") or 0
                    loss = value
                    pv = self.handler.get_power("PV_POWER")
                    efficiency = self.handler.get_power("EFFICIENCY")

                    average_list = self.statsmanager.get_data("powerconsumption", "hourly_watt_average")
                    value = 0.0
                    if average_list:
                        value, count = average_list
                        value *= count
                        count += 1
                        value = (value + self.get_hourly_average()) / count

                    if self.ws_server:
                        self.ws_server.emit_ws({
                            'averageWh': value,
                            'averageWhD': self.get_daily_average(),
                            'power': self.current_power,
                            'grid_power': self.current_grid_power,
                            'battery_power': self.P_DC_consumption_Battery,
                            'costs': cost,
                            'total_costs_today': total_cost,
                            'pv': pv,
                            'loss': loss,
                            'efficiency': efficiency,
                            'consumptionD': self.get_daily_wh(),
                            'soc' : self.soc
                        })

                    try:
                        self.client.publish(self.keep_alive_topic, payload="1", qos=1)
                    except Exception as e:
                        self.logger.log.error(f"Error sending keep-alive: {e}")
                else:
                    self.logger.log.debug("MQTT connection lost. Reconnecting...")
                    self.client = None
                    self.update_config(self.mqtt_config)

    def stop(self):
        self.keep_alive_running = False
        super().stop()

    def run(self):
        """Main thread logic"""
        self.client.unsubscribe("#")
        for topic in self.data_topics.values():
            self.logger.log.debug(f"Subscribing to topic: {topic}")
            self.client.subscribe(topic)

        # Start keep-alive thread
        self.keep_alive_running = True
        threading.Thread(target=self.send_keep_alive, daemon=True).start()

        # Start MQTT loop in a separate thread
        threading.Thread(target=self.mqtt_loop, daemon=True).start()

        # Wait until stop_event is set
        self.stop_event.wait()

        # Cleanup
        if self.client:
            self.client.disconnect()
        self.save_data()

    def mqtt_loop(self):
        """Non-blocking MQTT loop to handle incoming messages"""
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("Exiting MQTT loop...")
