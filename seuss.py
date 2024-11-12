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

from core.seusscore import SEUSS
from core.config import Config
from core.log import CustomLogger
import os, sys, subprocess

config = Config()
logger = CustomLogger()


def excepthook_handler(exc_type, exc_value, exc_traceback):
    logger.log_error(f"Unknown Exception exc_info=({exc_type}, {exc_value}, {exc_traceback})")
    main_script_path = os.path.abspath(sys.argv[0])
    main_script_directory = os.path.dirname(main_script_path)
    restart = os.path.join(main_script_directory, 'restart.sh')
    if os.path.exists('/data/rc.local'):
        subprocess.run(['bash', restart])


def main():
    sys.excepthook = excepthook_handler

    seuss_instance = SEUSS()
    seuss_instance.start()


if __name__ == "__main__":
    main()
