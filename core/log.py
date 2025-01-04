#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2025 Christian Kvasny chris(at)ckvsoft.at
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

import inspect
import os

import logging
import logzero
from logzero import logger

from core.config import Config
from design_patterns.singleton import Singleton


class CustomLogger(Singleton):
    RESET = "\x1b[0m"
    BRIGHT = "\x1b[1m"
    RED = "\x1b[31m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"

    def __init__(self):
        super().__init__()

    def _init(self):
        if not hasattr(self, 'initialized'):
            self.config = Config()
            self.config.observer.add_observer("CustomLogger", self)
            self.log_level = self.config.log_level

            self.handle_config_update(self.config.config_data)
            # Setze den Log-Level für die Konsole
            # if not self.colored_console:
            #    logzero.loglevel(logzero.WARNING)

            self.initialized = True

    def handle_config_update(self, config_data):
        self.log_level = self.config.log_level
        if os.path.exists('/data/rc.local'):
            logzero.setup_default_logger(disableStderrLogger=True)
        # Setze den Log-Level für die Datei
        logzero.loglevel(self.config.log_level.upper())
        # Konfiguriere das Logfile mit maximaler Dateigröße und Anzahl der behaltenen Logdateien
        logzero.logfile(
            self.config.log_file_path,
            encoding='utf-8',
            maxBytes=1024 * 1024,
            backupCount=3,
            loglevel=logging.getLevelName(self.config.log_level.upper())
        )

        print("CustomLogger is handling configuration change.")

    def format_message(self, message, log_level):
        if self.log_level.upper() != "DEBUG" or log_level != "DEBUG":
            return message

        caller_frame = inspect.stack()[2]
        script_name = os.path.basename(caller_frame[1])
        function_name = caller_frame[3]

        #        formatted_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        #        formatted_message = f"{formatted_date} [{log_level}] {script_name}/{function_name}: {message}"
        formatted_message = f"[{script_name}/{function_name}]: {message}"
        return formatted_message

    def log_info(self, message):
        logger.info(self.format_message(message, "INFO"))

    def log_debug(self, message):
        logger.debug(self.format_message(message, "DEBUG"))

    def log_error(self, message):
        logger.error(self.format_message(message, "ERROR"))

    def log_warning(self, message):
        logger.warning(self.format_message(message, "WARNING"))
