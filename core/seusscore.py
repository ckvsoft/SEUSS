import time
import json
import paho.mqtt.client as mqtt

# MQTT-Konfiguration
broker = "venus.local"  # Ersetze durch deine Broker-Adresse
port = 1883
keep_alive_topic = "R/d83add7fec91/keepalive"
data_topics = {
    "P_L1": "N/d83add7fec91/grid/40/Ac/L1/Power",
    "P_L2": "N/d83add7fec91/grid/40/Ac/L2/Power",
    "P_L3": "N/d83add7fec91/grid/40/Ac/L3/Power",
    "I_L1": "N/d83add7fec91/grid/40/Ac/L1/Current",
    "I_L2": "N/d83add7fec91/grid/40/Ac/L2/Current",
    "I_L3": "N/d83add7fec91/grid/40/Ac/L3/Current",
    "P_AC_consumption_L1": "N/d83add7fec91/system/0/Ac/Consumption/L1/Power",
    "P_AC_consumption_L2": "N/d83add7fec91/system/0/Ac/Consumption/L2/Power",
    "P_AC_consumption_L3": "N/d83add7fec91/system/0/Ac/Consumption/L3/Power",
    "P_PV_L1": "N/d83add7fec91/pvinverter/34/Ac/L1/Power",  # PV-Leistung für L1
    "P_PV_L2": "N/d83add7fec91/pvinverter/34/Ac/L2/Power",  # PV-Leistung für L2
    "P_PV_L3": "N/d83add7fec91/pvinverter/34/Ac/L3/Power",  # PV-Leistung für L3
    "P_battery_DC": "N/d83add7fec91/system/0/Dc/Battery/Power",
    "I_battery_DC": "N/d83add7fec91/system/0/Dc/Battery/Current",
    "number_of_phases": "N/d83add7fec91/system/0/Ac/Consumption/NumberOfPhases"
}

# Initialisierte Variablen
P_L1 = P_L2 = P_L3 = None
I_L1 = I_L2 = I_L3 = None
P_AC_consumption_L1 = P_AC_consumption_L2 = P_AC_consumption_L3 = None
P_PV_L1 = P_PV_L2 = P_PV_L3 = None  # PV-Leistungen für die Phasen
P_battery_DC = I_battery_DC = None
V_battery_DC = 48  # Standardwert der Batteriespannung (wenn fest)
interval_duration = 5  # Dauer des Intervalls in Sekunden
number_of_phases = 3  # Standardanzahl der Phasen, anpassen nach Bedarf

# Callback für das Empfangen von Nachrichten
def on_message(client, userdata, msg):
    global P_L1, P_L2, P_L3, I_L1, I_L2, I_L3
    global P_AC_consumption_L1, P_AC_consumption_L2, P_AC_consumption_L3
    global P_PV_L1, P_PV_L2, P_PV_L3  # Hinzufügen der PV-Leistungen
    global P_battery_DC, I_battery_DC, number_of_phases

    topic = msg.topic
    payload = json.loads(msg.payload.decode())

    if topic in data_topics.values():
        if topic == data_topics["P_L1"]:
            P_L1 = payload.get("value", 0)
        elif topic == data_topics["P_L2"]:
            P_L2 = payload.get("value", 0)
        elif topic == data_topics["P_L3"]:
            P_L3 = payload.get("value", 0)
        elif topic == data_topics["I_L1"]:
            I_L1 = payload.get("value", 0)
        elif topic == data_topics["I_L2"]:
            I_L2 = payload.get("value", 0)
        elif topic == data_topics["I_L3"]:
            I_L3 = payload.get("value", 0)
        elif topic == data_topics["P_AC_consumption_L1"]:
            P_AC_consumption_L1 = payload.get("value", 0)
        elif topic == data_topics["P_AC_consumption_L2"]:
            P_AC_consumption_L2 = payload.get("value", 0)
        elif topic == data_topics["P_AC_consumption_L3"]:
            P_AC_consumption_L3 = payload.get("value", 0)
        elif topic == data_topics["P_PV_L1"]:
            P_PV_L1 = payload.get("value", 0)
        elif topic == data_topics["P_PV_L2"]:
            P_PV_L2 = payload.get("value", 0)
        elif topic == data_topics["P_PV_L3"]:
            P_PV_L3 = payload.get("value", 0)
        elif topic == data_topics["P_battery_DC"]:
            P_battery_DC = payload.get("value", 0)
        elif topic == data_topics["I_battery_DC"]:
            I_battery_DC = payload.get("value", 0)
        elif topic == data_topics["number_of_phases"]:
            number_of_phases = payload.get("value", 3)

def send_keep_alive(client):
    client.publish(keep_alive_topic, payload="1", qos=1)

def calculate_efficiency():
    if None in (P_L1, P_L2, P_L3, I_L1, I_L2, I_L3,
                P_AC_consumption_L1, P_AC_consumption_L2, P_AC_consumption_L3,
                P_PV_L1, P_PV_L2, P_PV_L3,  # Prüfen der PV-Werte
                P_battery_DC, I_battery_DC):
        print("Warten auf alle Daten...")
        return None, None

    # Gesamte Leistung und Strom aus den drei Phasen berechnen
    P_grid = P_L1 + P_L2 + P_L3
    I_grid = I_L1 + I_L2 + I_L3

    # Gesamte AC-Verbrauchsleistung berechnen
    P_AC_consumption = P_AC_consumption_L1 + P_AC_consumption_L2 + P_AC_consumption_L3

    # Gesamte PV-Leistung berechnen
    P_PV = P_PV_L1 + P_PV_L2 + P_PV_L3

    # Berechnung der Ladeleistung zur Batterie
    P_charge = max(P_grid + P_PV - P_AC_consumption, 0)  # Leistung zur Batterie
    P_battery_stored = V_battery_DC * I_battery_DC if I_battery_DC > 0 else 0  # Leistung beim Laden
    P_battery_consumed = P_battery_DC if I_battery_DC < 0 else 0  # Leistung beim Entladen

    # Energieübertragung berechnen
    energy_grid = P_grid * interval_duration / 3600  # Energie in kWh
    energy_battery_stored = P_battery_stored * interval_duration / 3600  # Energie in kWh
    energy_battery_consumed = P_battery_consumed * interval_duration / 3600  # Energie in kWh

    # Wirkungsgrad für das Laden
    eta_charge = P_battery_stored / P_charge if P_charge > 0 else 0

    # Wirkungsgrad für das Entladen
    eta_discharge = P_AC_consumption / P_battery_DC if P_battery_DC > 0 else 0

    # Berechnung des tatsächlichen Verbrauchs aus der Batterie unter Berücksichtigung des Wirkungsgrads
    actual_battery_consumed = P_battery_consumed * eta_discharge  # Tatsächlicher Verbrauch aus der Batterie

    # Eigenverbrauch und Differenzen berechnen
    net_consumption = P_grid + P_PV - P_AC_consumption - actual_battery_consumed

    # Ausgabe
    print(f"Direktverbrauch vom Netz: {P_AC_consumption:.2f} W")
    print(f"PV-Leistung: {P_PV:.2f} W")  # Ausgabe der PV-Leistung
    print(f"Zur Batterie geladene Leistung: {P_charge:.2f} W")
    print(f"Von der Batterie verbrauchte Leistung: {actual_battery_consumed:.2f} W")
    print(f"Energie vom Netz: {energy_grid:.2f} kWh")
    print(f"Energie in der Batterie gespeichert: {energy_battery_stored:.2f} kWh")
    print(f"Energie aus der Batterie verbraucht: {energy_battery_consumed:.2f} kWh")
    print(f"Wirkungsgrad Laden: {eta_charge * 100:.2f}%")
    print(f"Wirkungsgrad Entladen: {eta_discharge * 100:.2f}%")
    print(f"Netzverbrauch nach Berücksichtigung der Batterie: {net_consumption:.2f} W")

# MQTT-Client initialisieren
client = mqtt.Client()
client.on_message = on_message

# MQTT-Verbindung herstellen
client.connect(broker, port, keepalive=60)
client.loop_start()

# Abonnieren der Themen
for topic in data_topics.values():
    client.subscribe(topic)

try:
    while True:
        send_keep_alive(client)
        calculate_efficiency()  # Berechnung aufrufen
        time.sleep(interval_duration)  # Pause zwischen den Berechnungen
except KeyboardInterrupt:
    print("Programm beendet.")
finally:
    client.loop_stop()
    client.disconnect()
