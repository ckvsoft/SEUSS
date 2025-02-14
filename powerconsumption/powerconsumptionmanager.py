from powerconsumption.powerconsumptionmqtt import PowerConsumptionMQTT
from core.log import CustomLogger


class PowerConsumptionManager:
    def __init__(self, initial_config=None):
        self.logger = CustomLogger()
        self.current_config = initial_config
        self.current_instance = None
        if initial_config:
            self.initialize_instance(initial_config)

        self.logger.log.debug(f"initial config is {initial_config}")

    def initialize_instance(self, config):
        """Initializes the instance based on the configuration."""
        unit_type = config.get("type")
        if unit_type == "mqtt":
            self.current_instance = PowerConsumptionMQTT(
                interval_duration=config.get("interval_duration", 5),
                mqtt_config=config
            )
        else:
            raise ValueError(f"Unknown type: {unit_type}")

        self.current_config = config
        self.current_instance.start()

    def stop_instance(self):
        if self.current_instance:
            self.current_instance.stop()
            self.current_instance = None
            self.logger.log.debug(f"{self.__class__.__name__} has stopped.")

    def update_instance(self, new_config):
        """Updates the instance when the configuration changes."""
        self.logger.log.debug(f"new config is {new_config}")
        if not self.current_instance:  # If the instance has not been initialized yet
            self.logger.log.debug("No instance available, trying to initialize...")
            self.initialize_instance(new_config)
            return  # Exit the method since the instance has now been initialized

        # Check if current_config is None
        if self.current_config is None:
            self.logger.log.debug("current_config is None, initializing instance...")
            self.initialize_instance(new_config)
            return  # Exit the method since the instance is now initialized

        # Now safe to access self.current_config["type"]
        if new_config["type"] != self.current_config["type"]:
            self.logger.log.debug(f"Type changed from {self.current_config['type']} to {new_config['type']}. Updating instance...")
            if self.current_instance:
                self.current_instance.stop()  # Stop the current instance
                self.current_instance = None
            self.initialize_instance(new_config)
            self.logger.log.debug("Instance successfully updated.")
        else:
            # The type remains the same, so only update the configuration if necessary
            self.logger.log.debug("The type remains the same. Checking if configuration update is needed...")
            if new_config != self.current_config:
                self.logger.log.debug("Updating the configuration...")
                self.current_instance.update_config(new_config)
                self.logger.log.debug("Instance successfully updated.")
            else:
                self.logger.log.debug("Configuration update not needed...")

        # Save the new configuration
        self.current_config = new_config

    def get_instance(self):
        return self.current_instance
