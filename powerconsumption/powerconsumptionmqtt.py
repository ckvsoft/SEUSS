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
                self.logger.log.debug("The new MQTT configuration matches the current one. No changes required.")
                return

            self.logger.log.debug("MQTT configuration has changed. Reconnecting client...")
            self.client.disconnect()
            self.client = None

        # Save the new configuration
        if broker == "": return

        self.broker = broker
        self.port = port
        self.unit_id = unit_id

        # Set topics based on the new unit_id
        self.keep_alive_topic = mqtt_config.get("keep_alive_topic", "")

        self.data_topics = mqtt_config.get("topics")

        # Initialize the new MQTT client
        self.client = mqtt.Client(client_id=f"seuss-power-consumption-{Utils.generate_random_hex(8)}, protocol={mqtt.MQTTv5}")
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        if port == 8883:
            ssl_context = self._create_ssl_context(certificate)
            if ssl_context:
                self.client.tls_set_context(ssl_context)

        try:
            if user:
                plain_password = Utils.decode_from_base64(password)
                self.client.username_pw_set(user, password=plain_password)

            self.client.connect(self.broker, self.port, keepalive=60)
            self.logger.log.debug("Connected to the broker.")
        except socket.gaierror as e:
            self.logger.log.error(f"Network error: {e}. The broker hostname could not be resolved.")
        except ConnectionRefusedError as e:
            self.logger.log.error(f"Connection refused: {e}. Is the broker online?")
        except Exception as e:
            self.logger.log.error(f"An unexpected error occurred: {e}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            self.logger.log.error(f"Error decoding the payload: {msg.payload}")
            return

        if topic in self.data_topics.values():
            topic_key = next((k for k, v in self.data_topics.items() if v == topic), None)
            self.handler.update_values(topic_key, payload)

            if self.handler.all_required_data_complete() and self.handler.check_for_data():
                self.current_power = self.handler.get_power("AC_POWER")
                self.current_grid_power = self.handler.get_power("AC_GRID_POWER")
                self.P_DC_consumption_Battery = self.handler.get_power("BATTERY_POWER")
                timestamp = time.time()
                self.update(self.current_power, self.current_grid_power, self.P_DC_consumption_Battery, timestamp)

    def on_disconnect(self, client, userdata, rc):
        self.logger.log.debug(f"Disconnected from MQTT server. Code {rc}")

    def send_keep_alive(self):
        """Sends periodic keep-alive messages to the broker."""
        while self.keep_alive_running:
            time.sleep(self.interval_duration)  # Wait for the interval
            if self.client and self.keep_alive_running:
                if self.client and self.client.is_connected():
                    self.current_power = self.current_power or 0
                    #print(f"Current power: {self.current_power:.2f} W")
                    #print(f"Daily consumption: {self.get_daily_wh():.4f} Wh")
                    #print(f"Current grid power: {self.current_grid_power:.2f} W")
                    #print(f"Current DC power: {self.P_DC_consumption_Battery:.2f} W")
                    cost = self.energy_costs_by_hour.get(str(self.current_hour), 0.0)
                    # print(f"Current Hour Grid Cost: {cost:.2f} \u00A2")
                    total_cost = sum(self.energy_costs_by_hour.values())
                    # print(f"Today Grid Costs: {total_cost:.2f} \u00A2")
                    self.energy_costs_by_day[str(self.current_day)] = total_cost

                    value = self.handler.get_power("TOTAL_POWER")
                    # Abziehen des Stroms, der aus dem Netz bezogen wird
                    loss = value if value else 0
                    pv = self.handler.get_power("PV_POWER")
                    efficiency = self.handler.get_power("EFFICIENCY")

                    average_list = self.statsmanager.get_data("powerconsumption", "hourly_watt_average")
                    value = 0.0
                    if average_list:
                        value, count = average_list
                        value *= count
                        count += 1
                        value = (value + self.get_hourly_average()) / count
                        # print(f"Average Stats: {value:.4f} Wh")
                        # print(f"Forcast Day Stats: {value * 24:.4f} Wh")

                    if self.ws_server:
                        self.ws_server.emit_ws({'averageWh': value, 'averageWhD': self.get_daily_average(), 'power': self.current_power, 'grid_power': self.current_grid_power, 'battery_power': self.P_DC_consumption_Battery,'costs': cost, 'total_costs_today': total_cost, 'pv': pv, 'loss': loss, 'efficiency': efficiency, 'consumptionD': self.get_daily_wh()})

                    try:
                        self.client.publish(self.keep_alive_topic, payload="1", qos=1)
                    except Exception as e:
                        self.logger.log.error(f"Error sending the keep-alive message: {e}")
                else:
                    self.logger.log.debug("No connection to MQTT server. Attempting to reconnect.")
                    self.client = None
                    self.update_config(self.mqtt_config)

    def stop(self):
        self.keep_alive_running = False
        super().stop()

    def run(self):
        """Main thread logic"""
        for topic in self.data_topics.values():
            self.client.subscribe(topic)

        # Start the keep-alive thread
        self.keep_alive_running = True
        keep_alive_thread = threading.Thread(target=self.send_keep_alive, daemon=True)
        keep_alive_thread.start()

        # Start the MQTT loop in a non-blocking thread
        mqtt_thread = threading.Thread(target=self.mqtt_loop)
        mqtt_thread.start()

        # Wait until stop_event is set
        self.stop_event.wait()  # Blocks until the stop_event is set

        # Cleanup once the thread is stopped
        self.client.disconnect()
        self.save_data()  # Save data on exit

    def mqtt_loop(self):
        """MQTT loop to keep receiving messages."""
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("Exiting program...")

    def _create_ssl_context(self, certificate):
        """Create an SSL context for the MQTT connection."""
        context = None
        try:
            import ssl
            # Use PROTOCOL_TLS_CLIENT instead of deprecated PROTOCOL_TLS
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(certificate)
            context.check_hostname = True
        except ImportError:
            self.logger.log.error("SSL support not available.")
        return context
