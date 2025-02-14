import logging
from logging.handlers import RotatingFileHandler
import sys
import os
import inspect
from datetime import datetime

from core.config import Config
from design_patterns.singleton import Singleton


class ConsoleFormatter(logging.Formatter):
    LEVEL_MAP = {
        "DEBUG": '\033[94m',  # Blau
        "INFO": '\033[92m',  # Grün
        "WARNING": '\033[93m',  # Gelb
        "ERROR": '\033[91m',  # Rot
        "CRITICAL": '\033[95m',  # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        level = record.levelname[0]
        timestamp = datetime.now().strftime('%y%m%d %H:%M:%S')
        color = self.LEVEL_MAP.get(record.levelname, '')
        return f"{color}[{level} {timestamp} log:{record.lineno}]{self.RESET} {record.getMessage()}"


class FileFormatter(logging.Formatter):
    def format(self, record):
        level = record.levelname[0]
        timestamp = datetime.now().strftime("%y%m%d %H:%M:%S")
        filename = os.path.basename(record.pathname)
        location = f"[{filename}/{record.funcName}]: " if record.levelname == "DEBUG" else ""
        return f"[{level} {timestamp} log:{record.lineno}] {location}{record.getMessage()}"


class CustomLogger(Singleton):
    def __init__(self):
        super().__init__()
#        self._init()

    def _init(self):
        if not hasattr(self, 'initialized'):
            self.config = Config()
            self.config.observer.add_observer("CustomLogger", self)
            self.log_level = self.config.log_level
            self.logger = logging.getLogger('custom_logger')
            self.logger.setLevel(self.log_level)

            if self.logger.hasHandlers():
                self.logger.handlers.clear()  # Lösche Standard-Handler

            self.logger.propagate = False

            log_file = self.config.log_file_path
            file_handler = RotatingFileHandler(log_file, mode='a', maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            file_handler.setFormatter(FileFormatter())
            file_handler.setLevel(self.log_level)
            self.logger.addHandler(file_handler)

            if not os.path.exists('/data/rc.local'):
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setFormatter(ConsoleFormatter())
                console_handler.setLevel(self.log_level)
                self.logger.addHandler(console_handler)

            self.initialized = True

    def handle_config_update(self, config_data):
        self.log_level = self.config.log_level
        self.logger.setLevel(self.log_level)

    def format_message(self, message, log_level):
        if self.log_level.upper() != "DEBUG" or log_level != "DEBUG":
            return message
        caller = inspect.stack()[2]
        script_name = os.path.basename(caller.filename)
        function_name = caller.function
        return f"[{script_name}/{function_name}]: {message}"

    def log_info(self, message):
        self.logger.info(self.format_message(message, "INFO"))

    def log_debug(self, message):
        self.logger.debug(self.format_message(message, "DEBUG"))

    def log_error(self, message):
        self.logger.error(self.format_message(message, "ERROR"))

    def log_warning(self, message):
        self.logger.warning(self.format_message(message, "WARNING"))
