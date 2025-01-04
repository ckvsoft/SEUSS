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
from datetime import datetime
from core.utils import Utils
from bottle import template, static_file, response, request, redirect
import bottle

import json
import os, sys, glob
import zipfile
import threading
import core.version as version
from waitress import serve
from core.config import Config
from core.logreader import LogReader
from core.log import CustomLogger
from spotmarket.abstract_classes.itemlist import Itemlist


class SEUSSWeb:
    def __init__(self):
        self.app = bottle.Bottle()
        self.server = None
        main_script_path = os.path.abspath(sys.argv[0])
        self.main_script_directory = os.path.dirname(main_script_path)
        self.view_path = os.path.join(self.main_script_directory, 'views')
        self.static_dir = os.path.join(self.main_script_directory, 'views/static')

        self.config = Config()
        self.logger = CustomLogger()
        self.market_items = Itemlist()

        # Routen einrichten
        self.setup_routes()

    def save_config(self, config):
        config = Utils.encode_passwords_in_base64(config)
        self.logger.log_info(f"save configuration to {self.config.config_file}")
        self.config.save_config(config)
        self.config.load_config()
        self.logger.log_info(f"{self.config.config_data}")

        # restart = os.path.join(self.main_script_directory, 'restart.sh')
        # if os.path.exists('/data/rc.local'):
        #    subprocess.run(['bash', restart])

    def serve_static(self, filename):
        return static_file(filename, root=self.static_dir)

    def setup_routes(self):
        self.app.route('/', method='GET', callback=self.index)
        self.app.route('/editor', method='GET', callback=self.editor)
        self.app.route('/logview', method='GET', callback=self.logview)
        self.app.route('/save_config', method='POST', callback=self.save_config_route)
        self.app.route('/static/<filename:path>', method='GET', callback=self.serve_static)
        self.app.route('/download_log', method='POST', callback=self.download_log)
        self.app.route('/update_log', method='GET', callback=self.update_log)
        self.app.route('/check_is_online', method='GET', callback=self.check_is_online)
        self.app.route('/add_config_entry', method='POST', callback=self.add_config_entry)

    def add_config_entry(self):
        param_name = request.json.get('param_name')

        # Überprüfe, ob der Parameter-Namen gültig ist
        if param_name in self.config.config_data:
            # Suche den vorhandenen Eintrag in der Konfiguration mit dem Parameter-Namen
            existing_entry = self.config.config_data[param_name]

            # Überprüfe, ob der Eintrag gefunden wurde
            if existing_entry:
                # Kopiere den vorhandenen Eintrag und aktualisiere die Daten mit den neuen Daten
                count = len(existing_entry)
                new_entry = existing_entry[0]
                new_entry["name"] = f"{param_name}{count + 1}"
                self.config.config_data[param_name].append(new_entry)

                return {'status': 'success', 'config': self.config.config_data}
            else:
                return {'status': 'error', 'message': 'Existing entry not found'}
        else:
            return {'status': 'error', 'message': 'Invalid parameter name'}

    def set_item_list(self, items):
        self.market_items = items

    def index(self):

        data, gray_hours, next_data, next_gray_hours = Itemlist.get_price_hour_lists(
            self.market_items.get_current_list())
        green_data, green_hours, next_green_data, next_green_hours = Itemlist.get_price_hour_lists(
            self.market_items.get_lowest_prices(self.config.number_of_lowest_prices_for_charging))
        red_data, red_hours, next_red_data, next_red_hours = Itemlist.get_price_hour_lists(
            self.market_items.get_highest_prices(self.config.number_of_highest_prices_for_discharging))

        chart_svg = self.generate_chart_svg(data, green_hours, red_hours)
        next_chart_svg = self.generate_chart_svg(next_data, next_green_hours, next_red_hours, True)

        legend_svg = self.generate_legend_svg()

        return template('index', chart_svg=chart_svg, legend_svg=legend_svg, next_chart_svg=next_chart_svg,
                        version=version.__version__, root=self.view_path)

    def logview(self):
        reader = LogReader()
        hide_debug = False
        if self.config.log_level == "DEBUG":
            hide_debug = True

        log_content = reader.get_log_data_for_frontend(not hide_debug)

        return template('logview', log_content=log_content, hide_debug=hide_debug)

    def update_log(self):
        reader = LogReader()

        hide_debug = False if request.query.get("hide_debug") == 'true' else True  # her we need the reverse
        log_content = reader.get_log_data_for_frontend(hide_debug)

        return log_content

    def download_log(self):
        directory_path = str(os.path.dirname(self.config.log_file_path))

        # Überprüfen, ob directory_path leer oder None ist
        if not directory_path:
            main_script_path = os.path.abspath(sys.argv[0])
            directory_path = str(os.path.dirname(main_script_path))

        file_name = os.path.basename(self.config.log_file_path)

        zip_files = glob.glob(os.path.join(directory_path, '*.zip'))

        for zip_file in zip_files:
            try:
                os.remove(zip_file)
            except Exception as e:
                pass

        # Dateien im Verzeichnis auflisten
        files = os.listdir(str(directory_path))
        logfiles = [file for file in files if file.startswith(file_name)]

        # Pfad zum temporären ZIP-Archiv
        zip_file_name = 'logfiles_' + str(int(datetime.now().timestamp() / 1000)) + '.zip'
        zip_file_path = os.path.join(directory_path, zip_file_name)

        # ZIP-Archiv erstellen und Dateien hinzufügen
        with zipfile.ZipFile(zip_file_path, 'w') as zip_file:
            for file in logfiles:
                file_path = os.path.join(directory_path, file)
                zip_file.write(file_path, file)

        # ZIP-Archiv zum Download anbieten
        response.headers['Content-Type'] = 'application/zip'
        response.headers['Content-Disposition'] = f'attachment; {zip_file_name}'
        return static_file(zip_file_name, root=directory_path, download=True)

    def editor(self):
        tooltips = {}
        try:
            with open(os.path.join(self.main_script_directory, 'README.md'), 'r', encoding='utf-8') as file:
                markdown_text = file.read()
            tooltips = self._extract_table_values(markdown_text)

        except FileNotFoundError:
            pass

        names = {
            "awattar": "aWATTar",
            "entsoe": "ENTSO-e",
            "tibber": "Tibber"
        }

        config = self.config.config_data

        unit_id = Config.get_unit_id(config)
        if not self._is_hex(unit_id):
            config['ess_unit'][0]['unit_id'] = Config.find_venus_unique_id()
        config = Utils.decode_passwords_from_base64(config)
        json_object = json.dumps(config, indent=2)
        return template('editor', config=config, json_config=json_object, tooltips=tooltips, names=names,
                        root=self.view_path)

    def check_is_online(self):
        return "OK"

    def save_config_route(self):
        # Laden der aktuellen Konfiguration
        new_config = self.config.config_data

        # Iteration durch Formulardaten
        for key, value in request.forms.items():
            # Unterteilung des Schlüssels, um Sektion, Namen und Feld zu extrahieren
            split_key = key.split(':')
            if len(split_key) == 2:
                section = split_key[0]
                if section not in new_config:
                    new_config[section] = []

                entry = next(e for e in new_config[section])
                # Aktualisieren des Feldwerts
                if self._is_numeric(value):
                    value = float(value) if '.' in value else int(value)

                value_mapping = {'on': True, 'off': False}
                value = value_mapping.get(value, value)
                key = split_key[1]

                entry[key] = value

            # Überprüfen, ob der Schlüssel genügend Elemente hat
            elif len(split_key) >= 3:
                section = split_key[0]
                name = split_key[1]

                # Überprüfen, ob die Sektion in der Konfiguration existiert
                if section not in new_config:
                    new_config[section] = []

                # Überprüfen, ob der Name in der Sektion existiert
                entry = next((e for e in new_config[section] if e['name'] == name), None)
                if entry is None:
                    # Neuen Eintrag hinzufügen, falls nicht vorhanden
                    entry = {'name': name}
                    new_config[section].append(entry)

                # Aktualisieren des Feldwerts
                if self._is_numeric(value):
                    value = float(value) if '.' in value else int(value)
                value_mapping = {'on': True, 'off': False}
                value = value_mapping.get(value, value)

                entry[split_key[2]] = value
            else:
                key = key.strip()
                if key in new_config:
                    # Aktualisieren des Feldwerts
                    if self._is_numeric(value):
                        value = float(value) if '.' in value else int(value)
                    value_mapping = {'on': True, 'off': False}
                    value = value_mapping.get(value, value)

                    new_config[key] = value
                else:
                    self.logger.log_debug(f"Invalid key format - {key}")

        self.logger.log_debug(new_config)

        delay_seconds = 1
        threading.Timer(delay_seconds, self.save_config, args=(new_config,)).start()

        # Zurück zur Indexseite
        return new_config

    def generate_chart_svg(self, data, green_hours, red_hours, tomorrow=False):
        # SVG-Code für das Balkendiagramm
        current_time = datetime.now()
        current_hour = current_time.hour
        width = 35

        svg = f"""
        <svg width="{width * 24}" height="420" xmlns="http://www.w3.org/2000/svg" style="border: 1px solid #ccc; margin: 25px;">
        """

        average_price_today, average_price_tomorow = self.market_items.get_average_price_by_date(True)
        avg_height = 15
        average_price = 0.0
        if tomorrow and average_price_tomorow is not None:
            avg_height = (average_price_tomorow + 1) * 15  # Umrechnung in Höhe (Skalierung)
            average_price = average_price_tomorow
        elif average_price_today is not None:
            avg_height = (average_price_today + 1) * 15  # Umrechnung in Höhe (Skalierung)
            average_price = average_price_today

        y_avg_line = 330 - avg_height  # Linie für den Durchschnittspreis
        svg += f"""
        <line x1="45" y1="{y_avg_line}" x2="{width * 24}" y2="{y_avg_line}" stroke="magenta" stroke-width="2"/>
        """
        svg += f"""
        <text x="20" y="{y_avg_line + 2}" text-anchor="middle" font-size="10" fill="magenta">{average_price}</text>
        """

        charge_limit_height = (abs(self.config.charging_price_limit) + 1) * 15
        svg += f"""
        <line x1="0" y1="{330 - charge_limit_height}" x2="{width * 24}" y2="{330 - charge_limit_height}" stroke="yellow" stroke-width="2"/>
        """

        # Erzeuge SVG für jeden Balken und Beschriftung basierend auf den Daten
        for hour, price in data.items():
            # Standardfarbe: Grau
            color = "gray" if current_hour > hour else "gainsboro"
            pattern = ""  # Initialisiere pattern

            if tomorrow:
                color = "gainsboro"

            # Überprüfe Überlappung mit Streifen für rote und grüne Stunden
            if price < self.config.charging_price_limit or hour in green_hours:
                color = "green" if current_hour > hour else "#32CD32"
            elif hour in red_hours and hour not in green_hours:
                color = "darkred" if current_hour > hour else "red"

            if tomorrow:
                if price < self.config.charging_price_limit or hour in green_hours:
                    color = "#32CD32"
                elif hour in red_hours and hour not in green_hours:
                    color = "red"

            # Berechne die Höhe und Ausrichtung des Balkens
            height = (abs(price) + 1) * 15
            y = 330 - height if price >= 0 else 330

            # Füge Balken hinzu
            svg += f"""
            <rect x="{hour * width}" y="{y}" width="{width - 3}" height="{height}" fill="{color}" stroke="#000" stroke-width="1" {f'fill="{pattern}"' if pattern else ""}/>
            """

            # Füge Stunden-Beschriftung hinzu innerhalb der Gruppe
            svg += f"""
            <text x="{hour * width + 15}" y="345" text-anchor="middle" font-size="10">{hour}</text>
            """

            # Füge Preis-Beschriftung hinzu innerhalb der Gruppe
            svg += f"""
            <text x="{hour * width + 15}" y="{y - 5}" text-anchor="middle" font-size="10" fill="{color}">{price}</text>
            """

        # Schließe die Gruppe und SVG-Code
        svg += """
        </svg>
        """

        return svg

    def generate_legend_svg(self):
        # SVG-Code für die Legende
        legend_svg = """
        <svg width="155" height="135" xmlns="http://www.w3.org/2000/svg" style="border: 1px solid #ccc; margin: 25px;">
        """

        # Füge Rechteck für grüne Stunde hinzu
        legend_svg += """
        <rect x="10" y="10" width="20" height="20" fill="green" stroke="#000" stroke-width="1"/>
        """

        # Füge Text für grüne Stunde hinzu
        legend_svg += """
        <text x="40" y="25" font-size="12">Charging</text>
        """

        # Füge Rechteck für rote Stunde hinzu
        legend_svg += """
        <rect x="10" y="40" width="20" height="20" fill="red" stroke="#000" stroke-width="1"/>
        """

        # Füge Text für rote Stunde hinzu
        legend_svg += """
        <text x="40" y="55" font-size="12">Discharging</text>
        """

        legend_svg += """
        <rect x="10" y="75" width="20" height="4" fill="magenta" stroke="#000" stroke-width="1"/>
        """
        legend_svg += """
        <text x="40" y="85" font-size="12">Average</text>
        """

        legend_svg += """
        <rect x="10" y="105" width="20" height="4" fill="yellow" stroke="#000" stroke-width="1"/>
        """
        legend_svg += """
        <text x="40" y="115" font-size="12">Charging Price Limit</text>
        """

        # Schließe die SVG-Code
        legend_svg += """
        </svg>
        """

        return legend_svg

    def calculate_slider_percentages(self, current_soc, solar_expectation):
        # Normalize the SOC to a value between 0 and 100
        normalized_soc = min(100, max(0, current_soc))

        # When both SOC and solar expectation are high, adjust the sliders accordingly
        if normalized_soc > 80 and solar_expectation > 500:  # Define your own threshold values
            percentage1 = normalized_soc + 20
            percentage2 = normalized_soc / 2  # Adjust as needed
        else:
            # Default behavior
            percentage1 = normalized_soc
            percentage2 = normalized_soc * 2

        # Ensure that the calculated values are within the allowed range
        percentage1 = max(0, min(99, percentage1))
        percentage2 = max(100, min(200, percentage2))

        # Invert the values to achieve the desired behavior
        percentage1 = 99 - percentage1
        percentage2 = 200 - percentage2

        return percentage1, percentage2

    def run(self, host='0.0.0.0', port=5000, debug=False):
        if self.config.log_level == "DEBUG":
            debug = True
        bottle.TEMPLATE_PATH.insert(0, self.view_path)
        bottle.DEBUG = debug
        serve(self.app, host=host, port=port)
        self.logger.log_info(f"start bottle host:{host}, port:{port}")

        # self.app.run(host=host, port=port, debug=debug)

    def stop(self):
        self.logger.log_debug(f"Bottle Stop")
        sys.stderr.close()
        self.app.close()

    def _is_numeric(self, value):
        try:
            float(value)
            return True
        except ValueError:
            return False

    def _extract_table_values(self, markdown_text):
        result_dict = {}

        # Suche nach Zeilen, die mit "|" beginnen und nicht den Überschriften entsprechen
        lines = [line.strip() for line in markdown_text.splitlines() if line.strip().startswith(
            '|') and "Setting" not in line and "Meaning" not in line and "-------" not in line]

        for line in lines:
            # Teile die Zeile in Spalten auf
            columns = [col.strip() for col in line.split('|') if col.strip()]

            if len(columns) == 2:
                key, value = columns
                value = value.replace("<br/>", "\n")
                key = key.replace("`", "")
                result_dict[key] = value

        return result_dict

    def _is_hex(self, string):
        try:
            if string == 0:
                return False
            int_value = int(str(string), 16)
            return True
        except (ValueError, TypeError):
            return False
