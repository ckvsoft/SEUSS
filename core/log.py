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
        self.log_level = "DEBUG"

    def _init(self):
        if not hasattr(self, 'initialized'):
            self.config = Config()
            self.config.observer.add_observer("CustomLogger", self)
            self.log_level = self.config.log_level
            self.log = logging.getLogger('custom_logger')
            self.log.setLevel(self.log_level)
            self.handle_config_update(self.config.config_data)
            self.initialized = True

    def handle_config_update(self, config_data):
        self.config.load_config()
        self.log_level = self.config.log_level
        if self.log.hasHandlers():
            self.log.handlers.clear()  # Lösche Standard-Handler

        self.log.propagate = False

        log_file = self.config.log_file_path
        file_handler = RotatingFileHandler(log_file, mode='a', maxBytes=5 * 1024 * 1024, backupCount=3,
                                           encoding="utf-8")
        file_handler.setFormatter(FileFormatter())
        file_handler.setLevel(self.log_level)
        self.log.addHandler(file_handler)

        if not os.path.exists('/data/rc.local'):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(ConsoleFormatter())
            console_handler.setLevel(self.log_level)
            self.log.addHandler(console_handler)

        self.log.info("CustomLogger is handling configuration change.")
