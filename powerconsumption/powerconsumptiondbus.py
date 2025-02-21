try:
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib
    DBUS_AVAILABLE = True
except ImportError:
    print("DBus not available. Victron integration will be disabled.")
    DBUS_AVAILABLE = False

import time
import threading
import sys
import os
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext', 'velib_python'))

from powerconsumption.abstract_classes.powerconsumption import PowerConsumptionBase


class PowerConsumptionDbus(PowerConsumptionBase):
    def __init__(self, interval_duration=5):
        super().__init__(interval_duration)
        self.keep_alive_running = False

        if not DBUS_AVAILABLE:
            print("DBus not available. PowerConsumptionDbus will not start.")
            return

        self.dbus_services = {
            "ac_power": "com.victronenergy.grid",
            "ac_grid_power": "com.victronenergy.pvinverter",
            "battery_power": "com.victronenergy.battery"
        }
        self.dbus_paths = {
            "ac_power": "/Ac/Power",
            "ac_grid_power": "/Ac/Power",
            "battery_power": "/Dc/0/Power"
        }

        # Initialize dbus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

    def read_dbus_value(self, service, path):
        """Reads a dbus value."""
        if not DBUS_AVAILABLE:
            return None

        try:
            obj = self.bus.get_object(service, path)
            interface = dbus.Interface(obj, dbus.PROPERTIES_IFACE)
            return float(interface.Get(service, path))
        except Exception as e:
            self.logger.error(f"Error reading {service}{path}: {e}")
            return None

    def update_values(self):
        """Reads current values from Victron dbus and stores them."""
        if not DBUS_AVAILABLE:
            return

        ac_power = self.read_dbus_value(self.dbus_services["ac_power"], self.dbus_paths["ac_power"])
        ac_grid_power = self.read_dbus_value(self.dbus_services["ac_grid_power"], self.dbus_paths["ac_grid_power"])
        battery_power = self.read_dbus_value(self.dbus_services["battery_power"], self.dbus_paths["battery_power"])

        timestamp = time.time()
        self.update(ac_power, ac_grid_power, battery_power, timestamp)

    def send_keep_alive(self):
        """Periodically updates values."""
        if not DBUS_AVAILABLE:
            return

        while self.keep_alive_running:
            time.sleep(self.interval_duration)
            self.update_values()

    def run(self):
        """Starts the data retrieval thread."""
        if not DBUS_AVAILABLE:
            print("DBus not available. run() will not start.")
            return

        self.keep_alive_running = True
        keep_alive_thread = threading.Thread(target=self.send_keep_alive, daemon=True)
        keep_alive_thread.start()

    def stop(self):
        """Stops data retrieval."""
        self.keep_alive_running = False
        super().stop()
