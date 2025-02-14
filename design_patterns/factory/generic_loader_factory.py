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

# generic_loader_factory.py
from importlib import import_module
from core.log import CustomLogger


class GenericLoaderFactory:
    @staticmethod
    def create_loader(loader_type, info):
        logger = CustomLogger()
        if info is None:
            logger.log.warning(f"Received None for {loader_type} info. Returning None.")
            return None

        try:
            loader_name = info["name"].lower()
            loader_module_name = f"{loader_type}.{loader_name}"
            loader_class_name = f"{loader_name.capitalize()}"

            loader_module = import_module(loader_module_name)
            loader_class = getattr(loader_module, loader_class_name)
            return loader_class(**info)
        except (ModuleNotFoundError, AttributeError, ValueError):
            logger.log.error(f"Invalid {loader_type} Loader: {info}")
            return None
