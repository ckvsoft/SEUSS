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
        self.efficiency = 0.90
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

        # Check if the received topic is in the defined topics
        if topic in self.data_topics.values():
            self.update_values(topic, payload)

            # Calculate total power (sum of phases)
            self.current_power = sum(
                phase_power if phase_power is not None else 0
                for phase_power in [
                    self.P_AC_consumption_L1,
                    self.P_AC_consumption_L2,
                    self.P_AC_consumption_L3,
                ]
            )

            # Calculate total grid power (sum of phases)
            self.current_grid_power = sum(
                phase_power if phase_power is not None else 0
                for phase_power in [
                    self.G_AC_consumption_L1,
                    self.G_AC_consumption_L2,
                    self.G_AC_consumption_L3,
                ]
            )

            # If all required data is available
            if self.check_for_data():
                timestamp = time.time()  # Current timestamp
                self.update(self.current_power, self.current_grid_power, self.P_DC_consumption_Battery, timestamp)

    def on_disconnect(self, client, userdata, rc):
        self.logger.log.debug(f"Disconnected from MQTT server. Code {rc}")

    def update_values(self, topic, payload):
        if topic == self.data_topics["P_AC_consumption_L1"]:
            self.P_AC_consumption_L1 = payload.get("value", 0)
        elif topic == self.data_topics["P_AC_consumption_L2"]:
            self.P_AC_consumption_L2 = payload.get("value", 0)
        elif topic == self.data_topics["P_AC_consumption_L3"]:
            self.P_AC_consumption_L3 = payload.get("value", 0)
        elif topic == self.data_topics["number_of_phases"]:
            self.number_of_phases = payload.get("value", 3)
        if topic == self.data_topics["G_AC_consumption_L1"]:
            self.G_AC_consumption_L1 = payload.get("value", 0)
        elif topic == self.data_topics["G_AC_consumption_L2"]:
            self.G_AC_consumption_L2 = payload.get("value", 0)
        elif topic == self.data_topics["G_AC_consumption_L3"]:
            self.G_AC_consumption_L3 = payload.get("value", 0)
        elif topic == self.data_topics["number_of_grid_phases"]:
            self.number_of_grid_phases = payload.get("value", 3)
        elif topic == self.data_topics["P_DC_consumption_Battery"]:
            self.P_DC_consumption_Battery = payload.get("value", 0)

    def send_keep_alive(self):
        """Sends periodic keep-alive messages to the broker."""
        while self.keep_alive_running:
            time.sleep(self.interval_duration)  # Wait for the interval
            if self.client and self.keep_alive_running:
                if self.client and self.client.is_connected():
                    self.current_power = self.current_power or 0
                    print(f"Current power: {self.current_power:.2f} W")
                    print(f"Daily consumption: {self.get_daily_wh():.4f} Wh")
                    print(f"Current grid power: {self.current_grid_power:.2f} W")
                    print(f"Current DC power: {self.P_DC_consumption_Battery:.2f} W")
                    cost = self.energy_costs_by_hour.get(str(self.current_hour), 0.0)
                    # print(f"Current Hour Grid Cost: {cost:.2f} \u00A2")
                    total_cost = sum(self.energy_costs_by_hour.values())
                    # print(f"Today Grid Costs: {total_cost:.2f} \u00A2")
                    self.energy_costs_by_day[str(self.current_day)] = total_cost

                    alpha = 0.05  # Glättungsfaktor für den gleitenden Durchschnitt
                    total_consumption = self.current_power

                    if self.P_DC_consumption_Battery < 0:  # Batterie entlädt
                        # Berechnung des dynamischen Wirkungsgrads (falls benötigt)
                        current_efficiency = self.current_power / abs(self.P_DC_consumption_Battery) if abs(
                            self.P_DC_consumption_Battery) > 0 else 0.9

                        # Gleitender Durchschnitt für den Wirkungsgrad
                        self.efficiency = (1 - alpha) * self.efficiency + alpha * current_efficiency

                        # Begrenzung des Wirkungsgrads zwischen 0.7 und 1.0
                        self.efficiency = max(0.7, min(self.efficiency, 1.0))

                        # Korrigierte Entladeleistung der Batterie (mit Wirkungsgrad)
                        corrected_battery_power = abs(self.P_DC_consumption_Battery) * self.efficiency
                        total_consumption -= corrected_battery_power  # Entladene Batterie wird berücksichtigt

                    elif self.P_DC_consumption_Battery > 0:  # Batterie lädt
                        # Wenn die Batterie lädt, subtrahiere die Ladeleistung (abzüglich des Grid-Stroms)
                        total_consumption -= self.P_DC_consumption_Battery  # Ladeleistung abziehen

                    # Abziehen des Stroms, der aus dem Netz bezogen wird
                    total_consumption -= self.current_grid_power  # Netzstrom wird vom Gesamtverbrauch abgezogen

                    # Debug-Ausgabe
                    self.logger.log.debug(f"🔋 Dynamic Efficiency: {self.efficiency:.3f}")
                    self.logger.log.debug(f"⚡ Corrected Consumption: {total_consumption:.2f} W")

                    # Falls die Batterie lädt, wird die Entladung nicht berücksichtigt
                    total_consumption -= self.current_grid_power  # Netzstrom wird vom Gesamtverbrauch abgezogen

                    # Debug-Ausgabe
                    self.logger.log.debug(f"🔋 Dynamic Efficiency: {self.efficiency:.3f}")
                    self.logger.log.debug(f"⚡ Corrected Consumption: {total_consumption:.2f} W")

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
                        self.ws_server.emit_ws({'averageWh': value, 'averageWhD': self.get_daily_average(), 'power': self.current_power, 'grid_power': self.current_grid_power, 'battery_power': self.P_DC_consumption_Battery,'costs': cost, 'total_costs_today': total_cost, 'test': total_consumption, 'consumptionD': self.get_daily_wh()})

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
