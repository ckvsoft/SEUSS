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

import base64
import binascii
from typing import Dict, List
import random
import re
import operator
from decimal import Decimal, getcontext

from core.log import CustomLogger


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
                config[key] = [Utils.encode_passwords_in_base64(item) if isinstance(item, dict) else item for item in
                               value]
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
                config[key] = [Utils.decode_passwords_from_base64(item) if isinstance(item, dict) else item for item in
                               value]
            elif key == 'password' and isinstance(value, str) and value:
                decoded_password = Utils.decode_from_base64(value)
                config[key] = decoded_password

        return config

    @staticmethod
    def generate_random_hex(length):
        random_hex = ''.join(random.choices('0123456789abcdef', k=length))
        return random_hex

    @staticmethod
    def create_ssl_context(certificate):
        """Create an SSL context for the MQTT connection."""
        try:
            import ssl
        except ImportError:
            CustomLogger().log.error("SSL support not available.")
            return None

        try:
            # Use PROTOCOL_TLS_CLIENT instead of deprecated PROTOCOL_TLS
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(certificate)
            context.check_hostname = True
            return context
        except Exception as e:
            CustomLogger().log.error(f"Failed to create SSL context: {e}")
            return None

    @staticmethod
    def calculate_fee(base_value, fee_str):
        # Fees arrive as ct/kWh and have to land at potency 14 to add
        # correctly to a price stored at potency 13 (the unit chain
        # absorbs the /1000 between EUR/MWh and ct/kWh). See the
        # operator-path comment below for the full reasoning.
        if isinstance(fee_str, (int, float)):
            return float(Utils.convert_to_millicents(float(fee_str), 14))
        if fee_str is None or fee_str == "":
            return 0.0
        if not isinstance(fee_str, str):
            CustomLogger().log.warning(
                f"Unexpected fee type {type(fee_str).__name__}: {fee_str!r}; treating as 0."
            )
            return 0.0

        expr = fee_str.strip()

        try:
            base_value = int(base_value)
        except ValueError:
            CustomLogger().log.warning(f"Invalid base value: {base_value}, defaulting to 0.0")
            return 0.0

        OPS = {
            "+": operator.add,
            "-": operator.sub,
            "*": operator.mul,
            "/": operator.truediv
        }

        try:
            # Bare number string (e.g. "2.5", "-2.5", "+ 13.5"). The
            # regex tolerates a sign followed by optional whitespace,
            # but float() does NOT — "+ 13.5" would throw. Strip the
            # interior whitespace so all sign+number variants parse.
            if re.match(r"^[+\-]?\s*\d+(\.\d+)?$", expr):
                return float(
                    Utils.convert_to_millicents(float(expr.replace(" ", "")), 14)
                )

            # Prozentwert berechnen, falls vorhanden (z. B. "3% + 2.5")
            percentage_fee = 0.0
            fixed_fee = 0.0

            if "%" in expr:
                percentage_match = re.search(r"([+-]?\d+(\.\d+)?)\s*%", expr)
                if percentage_match:
                    percentage_fee = base_value * (float(percentage_match.group(1)) / 100)
                    expr = expr.replace(percentage_match.group(0), "")  # Prozent-Anteil entfernen

            # Verbleibende Fixwerte berechnen (z. B. "+ 2.5"). Implicit
            # leading "+" if the first non-whitespace character is a
            # digit -- otherwise "1.5 + 13.5" would only match the
            # second term and silently drop the first.
            expr_for_match = expr.lstrip()
            if expr_for_match[:1].isdigit():
                expr_for_match = "+ " + expr_for_match
            matches = re.findall(r"([+\-])\s*(\d+\.?\d*)", expr_for_match)

            for op, num in matches:
                # Note: potency 14 here, not 13. Prices arrive as
                # EUR/MWh (Awattar) or EUR/MWh-equivalent (Entsoe)
                # and are stored at potency 13; millicent_to_cent
                # divides by 10^14 to get back to ct/kWh. So a fee
                # given in ct/kWh has to land at potency 14 to add
                # correctly. Don't "fix" this without understanding
                # the unit chain.
                num = Utils.convert_to_millicents(float(num), 14)
                fixed_fee = OPS[op](fixed_fee, num)

            return percentage_fee + fixed_fee

        except Exception as e:
            CustomLogger().log.warning(f"Warning in calculate_fee: {e}. Returning 0.0. fee: {fee_str}")
            CustomLogger().log.debug(f"Base Value: {base_value} (Type: {type(base_value)})")
            CustomLogger().log.debug(f"Fee Expression: {fee_str} (Type: {type(fee_str)})")
            return 0.0

    @staticmethod
    def convert_to_millicents(euro, potency=14):
        try:
            # Replace commas with dots
            euro = str(euro).replace(',', '.')

            getcontext().prec = 30

            millicents = int(Decimal(euro) * Decimal(10) ** potency)
            return int(millicents)
        except ValueError:
            CustomLogger().log.error(f"Error converting price: {euro}")
            return None

    @staticmethod
    def millicent_to_cent(price):
        potency = 14
        try:
            getcontext().prec = 30

            cent = Decimal(price) / Decimal(10 ** potency)
            return "{:.4f}".format(cent)
        except (TypeError, ValueError):
            CustomLogger().log.error(f"Error converting price: {price}")
            return None
