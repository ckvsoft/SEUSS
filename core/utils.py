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

import base64
import binascii
from typing import Dict, List
import json
import random

class Utils:
    @staticmethod
    def encode_to_base64(input_string: str) -> str:
        try:
            bytes_to_encode = input_string.encode('utf-8')
            encoded_bytes = base64.urlsafe_b64encode(bytes_to_encode)
            encoded_string = encoded_bytes.decode('utf-8').rstrip('=')
            return encoded_string
        except (binascii.Error, UnicodeDecodeError):
            return input_string

    @staticmethod
    def decode_from_base64(encoded_string: str) -> str:
        try:
            # Füge das Padding wieder hinzu, wenn es fehlt
            missing_padding = len(encoded_string) % 4
            if missing_padding:
                encoded_string += '=' * (4 - missing_padding)

            decoded_bytes = base64.urlsafe_b64decode(encoded_string)
            decoded_string = decoded_bytes.decode('utf-8')
            return decoded_string
        except (binascii.Error, UnicodeDecodeError):
            return encoded_string

    @staticmethod
    def encode_passwords_in_base64(config: Dict) -> Dict:
        for key, value in config.items():
            if isinstance(value, dict):
                config[key] = Utils.encode_passwords_in_base64(value)
            elif isinstance(value, list):
                config[key] = [Utils.encode_passwords_in_base64(item) if isinstance(item, dict) else item for item in value]
            elif key == 'password' and isinstance(value, str) and value:
                encoded_password = Utils.encode_to_base64(value)
                config[key] = encoded_password

        return config

    @staticmethod
    def decode_passwords_from_base64(config: Dict) -> Dict:
        for key, value in config.items():
            if isinstance(value, dict):
                config[key] = Utils.decode_passwords_from_base64(value)
            elif isinstance(value, list):
                config[key] = [Utils.decode_passwords_from_base64(item) if isinstance(item, dict) else item for item in value]
            elif key == 'password' and isinstance(value, str) and value:
                decoded_password = Utils.decode_from_base64(value)
                config[key] = decoded_password

        return config

    @staticmethod
    def is_json_string(s):
        try:
            json_object = json.loads(s.strip())
            return isinstance(json_object, dict)
        except json.JSONDecodeError:
            return False

    @staticmethod
    def generate_random_hex(length):
        random_hex = ''.join(random.choices('0123456789abcdef', k=length))
        return random_hex

