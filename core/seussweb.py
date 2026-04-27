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
import re
from datetime import datetime, timedelta

from core.utils import Utils
from bottle import template, static_file, response, request, redirect
import bottle
import json
import os, sys, glob
import zipfile
import threading
import core.version as version

from core.config import Config
from core.logreader import LogReader
from core.log import CustomLogger
from spotmarket.abstract_classes.itemlist import Itemlist

class SEUSSWeb:
    def __init__(self):
        # Erstelle die Bottle-App und integriere Socket.IO
        self.app = bottle.Bottle()
        main_script_path = os.path.abspath(sys.argv[0])
        self.main_script_directory = os.path.dirname(main_script_path)
        self.view_path = os.path.join(self.main_script_directory, 'views')
        self.static_dir = os.path.join(self.main_script_directory, 'views/static')

        self.config = Config()
        self.logger = CustomLogger()
        self.market_items = Itemlist()
        self.fee = ""

        # Routen einrichten
        self.setup_routes()

    def save_config(self, config):
        config = Utils.encode_passwords_in_base64(config)
        self.logger.log.info(f"save configuration to {self.config.config_file}")
        self.config.save_config(config)
        self.config.load_config()
        self.logger.log.info(f"{self.config.config_data}")

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
        self.app.route('/get_charts', method='GET', callback=self.get_charts)

    def add_config_entry(self):
        param_name = request.json.get('param_name')

        # Check if the parameter name is valid
        if param_name in self.config.config_data:
            # Suche den vorhandenen Eintrag in der Konfiguration mit dem Parameter-Namen
            existing_entry = self.config.config_data[param_name]

            # Check if the entry was found
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
        self.fee = next(
            (entry['fee'] for entry in self.config.config_data['markets']
             if entry.get('name', '').lower() == self.market_items.current_market_name.lower()),
            ""
        )

    def get_charts(self, as_json=True):

        # Hourly price data for the chart bars (4 quarters averaged per hour).
        data, _, next_data, _ = Itemlist.get_price_hour_lists(
            self.market_items.get_current_list()
        )

        # Block-based charge/discharge selections.
        # We pass the blocks themselves to the SVG generator, which colours
        # individual quarter slices within each hourly bar based on block
        # membership -- so a 14:30-15:30 block visibly straddles the
        # boundary between the 14h and 15h bars.
        charge_blocks = self.market_items.get_lowest_charging_blocks(
            self.config.number_of_lowest_prices_for_charging,
            block_minutes=self.config.charging_block_minutes,
        )
        discharge_blocks = self.market_items.get_highest_discharging_blocks(
            self.config.number_of_highest_prices_for_discharging,
            block_minutes=self.config.discharging_block_minutes,
            exclude_blocks=charge_blocks,
            fill_gaps=getattr(self.config, "fill_gaps_with_short_clusters", True),
        )

        # Diagnostic logging: show how many items per local date and how
        # many blocks fall on which day. This makes it obvious if either
        # tomorrow's items are missing or tomorrow's blocks weren't found.
        from core.timeutilities import TimeUtilities
        logger = self.logger if hasattr(self, "logger") else None
        try:
            from core.log import CustomLogger
            log = CustomLogger().log
            items_per_day = {}
            for it in self.market_items.get_current_list():
                local = TimeUtilities.convert_utc_to_local(
                    it.get_start_datetime(), False
                )
                if local is not None:
                    items_per_day.setdefault(local.date(), 0)
                    items_per_day[local.date()] += 1
            log.debug(f"chart: items per local day: {items_per_day}")
            log.debug(f"chart: today_data hours: {sorted(data.keys())}")
            log.debug(f"chart: next_data hours: {sorted(next_data.keys())}")

            charge_per_day = {}
            for blk in charge_blocks:
                local = TimeUtilities.convert_utc_to_local(
                    blk.get_start_datetime(), False
                )
                if local is not None:
                    charge_per_day.setdefault(local.date(), 0)
                    charge_per_day[local.date()] += 1
            discharge_per_day = {}
            for blk in discharge_blocks:
                local = TimeUtilities.convert_utc_to_local(
                    blk.get_start_datetime(), False
                )
                if local is not None:
                    discharge_per_day.setdefault(local.date(), 0)
                    discharge_per_day[local.date()] += 1
            log.debug(
                f"chart: charge blocks per day: {charge_per_day}, "
                f"discharge blocks per day: {discharge_per_day}"
            )
        except Exception as exc:
            # Logging must never break the chart endpoint.
            pass

        chart_svg = self.generate_chart_svg(
            data, charge_blocks, discharge_blocks, tomorrow=False
        )
        next_chart_svg = self.generate_chart_svg(
            next_data, charge_blocks, discharge_blocks, tomorrow=True
        )

        legend_svg = self.generate_legend_svg()

        if as_json:
            response.content_type = 'application/json'
            return json.dumps({
                "today_chart": chart_svg,
                "tomorrow_chart": next_chart_svg,
                "legend_svg": legend_svg
            })

        return chart_svg, next_chart_svg, legend_svg

    def index(self):
        chart_svg, next_chart_svg, legend_svg = self.get_charts(False)

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

        # Check if directory_path is empty or None
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
                # Update the field value
                if self._is_numeric(value):
                    value = float(value) if '.' in value else int(value)

                value_mapping = {'on': True, 'off': False}
                value = value_mapping.get(value, value)
                key = split_key[1]

                entry[key] = value

            # Check if the key has enough elements
            elif len(split_key) >= 3:
                section = split_key[0]
                name = split_key[1]

                # Check if the section exists in the config
                if section not in new_config:
                    new_config[section] = []

                # Check if the name exists in the section
                entry = next((e for e in new_config[section] if e['name'] == name), None)
                if entry is None:
                    # Neuen Eintrag hinzufügen, falls nicht vorhanden
                    entry = {'name': name}
                    new_config[section].append(entry)

                # Update the field value
                if self._is_numeric(value):
                    value = float(value) if '.' in value else int(value)
                value_mapping = {'on': True, 'off': False}
                value = value_mapping.get(value, value)

                entry[split_key[2]] = value
            else:
                key = key.strip()
                if key in new_config:
                    # Update the field value
                    if self._is_numeric(value):
                        value = float(value) if '.' in value else int(value)
                    value_mapping = {'on': True, 'off': False}
                    value = value_mapping.get(value, value)

                    new_config[key] = value
                else:
                    self.logger.log.debug(f"Invalid key format - {key}")

        self.logger.log.debug(new_config)

        delay_seconds = 1
        threading.Timer(delay_seconds, self.save_config, args=(new_config,)).start()

        # Zurück zur Indexseite
        return new_config

    def generate_chart_svg(self, data, charge_blocks, discharge_blocks,
                           tomorrow=False):
        """
        Render the daily price chart. 24 hourly bars per day, but each
        bar is internally split into 4 quarter-width slices that can be
        coloured independently. This lets a 14:30-15:30 charge block
        visibly straddle the boundary between the 14h and 15h bars: the
        right half of bar 14 and the left half of bar 15 turn green.

        Bars without block membership use the standard gray ramp
        (already-passed -> dark gray, future -> light gray, tomorrow ->
        always light gray).
        """
        current_time = datetime.now()
        current_hour = current_time.hour
        width = 37
        factor = 10
        baseline_y = 380
        svg_height = 460

        # Empty fallback: draw 24 grey bars at zero height
        if not data:
            data = {hour: None for hour in range(24)}

        svg = (
            f'<svg width="{width * 24}" height="{svg_height}" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'style="border: 1px solid #ccc; margin: 25px;">'
        )

        # Average price line (magenta)
        average_price_today, average_price_tomorrow = (
            self.market_items.get_average_price_by_date(True)
        )
        avg_height = 12
        if tomorrow and average_price_tomorrow is not None:
            avg_height = (average_price_tomorrow + 1) * factor
        elif not tomorrow and average_price_today is not None:
            avg_height = (average_price_today + 1) * factor
        y_avg_line = baseline_y - avg_height
        svg += (
            f'<line x1="0" y1="{y_avg_line}" x2="{width * 24}" y2="{y_avg_line}" '
            f'stroke="magenta" stroke-width="2"/>'
        )

        # Charging-price-limit line (yellow)
        charge_limit_height = (abs(self.config.charging_price_limit) + 1) * factor
        svg += (
            f'<line x1="0" y1="{baseline_y - charge_limit_height}" '
            f'x2="{width * 24}" y2="{baseline_y - charge_limit_height}" '
            f'stroke="yellow" stroke-width="2"/>'
        )

        # Pre-compute which quarters are in charge / discharge spans, for
        # the day this chart represents. We work in localtime to match
        # the hourly bar indexing.
        target_date = self._target_date(tomorrow)
        charge_quarters = self._collect_quarter_keys(charge_blocks, target_date)
        discharge_quarters = self._collect_quarter_keys(
            discharge_blocks, target_date
        )
        # Map (hour, q) -> charge block average price. Used to check
        # the hard cap against the block average rather than the
        # individual quarter price.
        charge_block_avgs = self._collect_quarter_block_avgs(
            charge_blocks, target_date
        )
        # Map (hour, q) -> actual per-quarter price (cent/kWh). Used for
        # the hard cap check on quarters that are NOT part of any charge
        # cluster -- otherwise we'd compare against the hourly average,
        # which can be misleading when the quarters within an hour have
        # different real prices.
        quarter_prices = Itemlist.get_quarter_prices(
            self.market_items.get_current_list(), target_date
        )

        # Draw each hour as 4 stacked quarter-width slices.
        # Each hour bar is wrapped in a <g> element with a <title>
        # child -- browsers render this as a hover tooltip showing the
        # individual quarter prices, so the user can see what's behind
        # the hourly average.
        slice_width = (width - 3) / 4.0  # leave 3px gap between hour groups
        for hour in range(24):
            price = data.get(hour)
            if price is not None:
                height = (abs(price) + 1) * factor
                y = baseline_y - height if price >= 0 else baseline_y
            else:
                height = factor
                y = baseline_y - height

            # Track slice colors so we can pick a "dominant" colour for
            # the hour as a whole. The price label is rendered in that
            # colour, matching the old behaviour where the label took
            # the bar colour -- this keeps it visible on the dark theme.
            slice_colors = []
            slice_svg = ""

            for q in range(4):
                key = (hour, q)
                base_color = self._slice_base_color(
                    hour, current_hour, tomorrow
                )
                slice_color = base_color
                if price is not None:
                    in_charge = key in charge_quarters
                    in_discharge = key in discharge_quarters
                    # The per-quarter price -- falls back to the hourly
                    # average if the quarter is missing from the data.
                    q_price = quarter_prices.get(key, price)
                    # Cap and limit checks both apply to the per-quarter
                    # price. This means an expensive quarter inside an
                    # otherwise cheap charge cluster shows up as olive
                    # (would-charge-but-cap-blocks) rather than green --
                    # so the user sees that the cluster has a temporarily
                    # expensive quarter that the cap will skip.
                    below_limit = q_price < self.config.charging_price_limit
                    below_cap = q_price < self.config.charging_price_hard_cap

                    if (in_charge or below_limit) and below_cap:
                        slice_color = self._green_color(hour, current_hour, tomorrow)
                    elif in_charge and not below_cap:
                        # Algorithm picked this quarter for charging, but
                        # this individual quarter exceeds the hard cap so
                        # SEUSS won't actually charge here. Show in olive
                        # so the user can tell at a glance "would charge
                        # but cap blocks it" rather than confusing it
                        # with an unrelated grey hour.
                        slice_color = self._olive_color(hour, current_hour, tomorrow)
                    elif in_discharge and not in_charge:
                        slice_color = self._red_color(hour, current_hour, tomorrow)

                slice_colors.append(slice_color)
                slice_x = hour * width + q * slice_width
                slice_svg += (
                    f'<rect x="{slice_x}" y="{y}" '
                    f'width="{slice_width}" height="{height}" '
                    f'fill="{slice_color}" stroke="none"/>'
                )

            # Hour-bar outline (drawn over the 4 slices)
            outline_svg = (
                f'<rect x="{hour * width}" y="{y}" '
                f'width="{width - 3}" height="{height}" '
                f'fill="none" stroke="#000" stroke-width="1"/>'
            )

            # Build the hover tooltip with per-quarter prices.
            # Format: "11:00 = 16.40 | 11:15 = 16.20 | 11:30 = 16.10 | 11:45 = 15.90 ct/kWh"
            # Falls back to "no price" when the quarter is missing.
            tooltip_parts = []
            for q in range(4):
                qprice = quarter_prices.get((hour, q))
                if qprice is None:
                    label = "n/a"
                elif float(qprice).is_integer():
                    label = f"{int(qprice)}"
                else:
                    label = f"{qprice:.2f}"
                tooltip_parts.append(f"{hour:02d}:{q*15:02d} = {label}")
            tooltip_text = " | ".join(tooltip_parts) + " ct/kWh"
            # XML-escape the tooltip just in case (no expected entities,
            # but better safe).
            tooltip_text = (tooltip_text
                            .replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;"))

            # Wrap slices + outline in a group with a title for hover.
            svg += (
                f'<g><title>{tooltip_text}</title>'
                f'{slice_svg}{outline_svg}</g>'
            )

            # Hour label at baseline. Uses CSS class "chart-text" so the
            # styles.css can colour it appropriately for light vs. dark
            # mode (white on dark, dark on light).
            svg += (
                f'<text x="{hour * width + 15}" y="{baseline_y + 15}" '
                f'text-anchor="middle" font-size="10" '
                f'class="chart-text">{hour}</text>'
            )

            # Price label (inside bar if very tall, otherwise above).
            # Use the most common slice colour for the label. For grey
            # slices (unmarked / past) we fall back to the CSS class
            # "chart-text" so the colour adapts to light vs. dark mode.
            # For coloured slices (green / red / olive) the colour is
            # legible on either background, so we use it directly.
            if price is not None:
                # Format compactly: integers as int, otherwise 2 decimals.
                # Avoids "12.345678" because of float averaging.
                if float(price).is_integer():
                    label_price = f"{int(price)}"
                else:
                    label_price = f"{price:.2f}"
            else:
                label_price = ""

            dominant_color = max(set(slice_colors), key=slice_colors.count) \
                if slice_colors else None

            # Treat default/past greys as "use the theme text colour".
            grey_colors = {"gray", "gainsboro"}
            use_theme_text = dominant_color in grey_colors or dominant_color is None

            if height + 15 > baseline_y:
                # Tall bar: label inside near the top. Use chart-text so
                # the colour matches the theme (visible on both modes).
                svg += (
                    f'<text x="{hour * width + 15}" y="15" '
                    f'text-anchor="middle" font-size="10" '
                    f'class="chart-text">{label_price}</text>'
                )
            else:
                # Short bar: label above the bar.
                if use_theme_text:
                    svg += (
                        f'<text x="{hour * width + 15}" y="{y - 5}" '
                        f'text-anchor="middle" font-size="10" '
                        f'class="chart-text">{label_price}</text>'
                    )
                else:
                    svg += (
                        f'<text x="{hour * width + 15}" y="{y - 5}" '
                        f'text-anchor="middle" font-size="10" '
                        f'fill="{dominant_color}">{label_price}</text>'
                    )

        # Hard-cap line (blue)
        charge_hard_cap_height = (
            abs(self.config.charging_price_hard_cap) + 1
        ) * factor
        svg += (
            f'<line x1="0" y1="{baseline_y - charge_hard_cap_height}" '
            f'x2="{width * 24}" y2="{baseline_y - charge_hard_cap_height}" '
            f'stroke="blue" stroke-width="2"/>'
        )

        if self.fee:
            x_center = width * 12
            svg += (
                f'<text x="{x_center}" y="{svg_height - 15}" '
                f'text-anchor="middle" font-size="12" fill="yellow">'
                f'"Prices exclude tax and include fees. Formula: '
                f'Final price = Base price + {self.fee}"</text>'
            )

        svg += "</svg>"
        return svg

    # ------------------------------------------------------------------
    # Chart helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _target_date(tomorrow):
        """
        Return today's or tomorrow's date in the configured timezone.
        Using datetime.today() would silently fall back to the system
        clock, which on Venus OS is often UTC -- giving an off-by-one
        date error when the user's configured timezone differs from UTC.
        """
        from core.timeutilities import TimeUtilities
        d = TimeUtilities.get_now().date()
        if tomorrow:
            d = d + timedelta(days=1)
        return d

    @staticmethod
    def _collect_quarter_keys(blocks, target_date):
        """
        Build a set of (hour, quarter_index) keys covered by the given
        blocks for the target_date. quarter_index is 0..3 within the
        hour. Block items are quarter-resolution; we walk each block's
        items, convert their start time to local, and add (hour, q) for
        each item that falls on target_date.

        Defensive against TimeUtilities returning a string instead of
        a datetime (which can happen if the time_str argument default
        ever drifts).
        """
        from core.timeutilities import TimeUtilities
        from datetime import datetime as _dt
        from core.log import CustomLogger
        log = CustomLogger().log

        keys = set()
        skipped_wrong_date = 0
        skipped_no_local = 0
        for blk in blocks:
            for item in blk.get_items():
                local = TimeUtilities.convert_utc_to_local(
                    item.get_start_datetime(), False
                )
                if local is None:
                    skipped_no_local += 1
                    continue
                # Be tolerant about what convert_utc_to_local returns:
                # if it ever returns a "YYYY-MM-DD HH:MM" string, parse
                # it back to a datetime so .date() works either way.
                if isinstance(local, str):
                    try:
                        local = _dt.strptime(local, "%Y-%m-%d %H:%M")
                    except ValueError:
                        skipped_no_local += 1
                        continue
                if local.date() != target_date:
                    skipped_wrong_date += 1
                    continue
                hour = local.hour
                q = local.minute // 15
                keys.add((hour, q))

        log.debug(
            f"_collect_quarter_keys: target={target_date}, "
            f"blocks={len(blocks)}, kept_quarters={len(keys)}, "
            f"skipped_wrong_date={skipped_wrong_date}, "
            f"skipped_no_local={skipped_no_local}"
        )
        return keys

    @staticmethod
    def _collect_quarter_block_avgs(blocks, target_date):
        """
        Map (hour, quarter_index) -> block_avg_price (in cent/kWh as float)
        for the target_date. Used by the chart to check the hard cap
        against the BLOCK average rather than the individual quarter
        price -- so a single expensive quarter inside an otherwise cheap
        cluster doesn't get painted grey.
        """
        from core.timeutilities import TimeUtilities
        from datetime import datetime as _dt
        out = {}
        for blk in blocks:
            try:
                avg_cent = float(blk.get_avg_price(True))
            except (TypeError, ValueError):
                continue
            for item in blk.get_items():
                local = TimeUtilities.convert_utc_to_local(
                    item.get_start_datetime(), False
                )
                if local is None:
                    continue
                if isinstance(local, str):
                    try:
                        local = _dt.strptime(local, "%Y-%m-%d %H:%M")
                    except ValueError:
                        continue
                if local.date() != target_date:
                    continue
                out[(local.hour, local.minute // 15)] = avg_cent
        return out

    @staticmethod
    def _slice_base_color(hour, current_hour, tomorrow):
        if tomorrow:
            return "gainsboro"
        return "gray" if current_hour > hour else "gainsboro"

    @staticmethod
    def _green_color(hour, current_hour, tomorrow):
        if tomorrow:
            return "#32CD32"
        return "green" if current_hour > hour else "#32CD32"

    @staticmethod
    def _red_color(hour, current_hour, tomorrow):
        if tomorrow:
            return "red"
        return "darkred" if current_hour > hour else "red"

    @staticmethod
    def _olive_color(hour, current_hour, tomorrow):
        """
        Olive shade for "would-charge but blocked by hard cap".
        Past hours use the darker shade, future hours the brighter one,
        matching the green/red dimming convention.
        """
        if tomorrow:
            return "#9ACD32"        # yellowgreen, bright
        return "#556B2F" if current_hour > hour else "#9ACD32"  # darkolivegreen / yellowgreen

    def generate_legend_svg(self):
        average_price_today, average_price_tomorrow = (
            self.market_items.get_average_price_by_date(True)
        )

        # Legend dimensions: enough room for 6 entries.
        legend_svg = (
            '<svg width="280" height="225" '
            'xmlns="http://www.w3.org/2000/svg" '
            'style="border: 1px solid #ccc; margin-top: 18px;">'
        )

        # Charging block (green)
        legend_svg += (
            '<rect x="10" y="10" width="20" height="20" '
            'fill="green" stroke="#000" stroke-width="1"/>'
            '<text x="40" y="25" font-size="12" class="chart-text">'
            'Charging</text>'
        )

        # Charging blocked by hard cap (olive)
        legend_svg += (
            '<rect x="10" y="40" width="20" height="20" '
            'fill="#556B2F" stroke="#000" stroke-width="1"/>'
            '<text x="40" y="55" font-size="12" class="chart-text">'
            'Charging blocked by hard cap</text>'
        )

        # Discharging (red)
        legend_svg += (
            '<rect x="10" y="70" width="20" height="20" '
            'fill="red" stroke="#000" stroke-width="1"/>'
            '<text x="40" y="85" font-size="12" class="chart-text">'
            'Discharging</text>'
        )

        # Average today line (magenta)
        legend_svg += (
            '<rect x="10" y="105" width="20" height="4" '
            'fill="magenta" stroke="#000" stroke-width="1"/>'
            f'<text x="40" y="115" font-size="12" class="chart-text">'
            f'Average Today ({average_price_today})</text>'
        )

        # Average tomorrow line (magenta)
        legend_svg += (
            '<rect x="10" y="135" width="20" height="4" '
            'fill="magenta" stroke="#000" stroke-width="1"/>'
            f'<text x="40" y="145" font-size="12" class="chart-text">'
            f'Average Tomorrow ({average_price_tomorrow})</text>'
        )

        # Charging price limit line (yellow)
        legend_svg += (
            '<rect x="10" y="165" width="20" height="4" '
            'fill="yellow" stroke="#000" stroke-width="1"/>'
            f'<text x="40" y="175" font-size="12" class="chart-text">'
            f'Charging Price Limit ({self.config.charging_price_limit})</text>'
        )

        # Charging price hard cap line (blue)
        legend_svg += (
            '<rect x="10" y="195" width="20" height="4" '
            'fill="blue" stroke="#000" stroke-width="1"/>'
            f'<text x="40" y="205" font-size="12" class="chart-text">'
            f'Charging Price Hard Cap ({self.config.charging_price_hard_cap})</text>'
        )

        legend_svg += "</svg>"
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
        self.logger.log.info(f"start bottle host:{host}, port:{port}")
        # serve(self.app, host=host, port=port)

        self.app.run(host=host, port=port, debug=debug)

    def stop(self):
        self.logger.log.debug(f"Bottle has stopped.")
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
        splitlines = markdown_text.splitlines()
        lines = [line.strip() for line in splitlines if line.strip().startswith('|') and "Setting" not in line.split(' ', 1)[0] and "Meaning" not in line.split(' ', 1)[0] and "-------" not in line]
        for line in lines:
            # Teile die Zeile in Spalten auf
            # columns = [col.strip() for col in line.split('|') if col.strip()]
            columns = [col.strip() for col in re.split(r'(?<!\\)\|', line) if col.strip()]

            if len(columns) == 2:
                key, value = columns
                value = value.replace("<br/>", "\n")
                value = re.sub(r'\\\|', '|', value)
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
