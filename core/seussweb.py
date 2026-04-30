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
        self.app.route('/stats', method='GET', callback=self.stats)
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

    def stats(self):
        """
        Statistics overview page. Reads per-day history dicts that the
        PowerConsumption layer accumulates into the StatsManager and
        derives:
          * raw daily totals (consumption / grid / pv / etc.)
          * battery cycles  = charge_wh / battery_capacity_wh
          * battery RTE     = discharge_wh / charge_wh * 100
          * abort skip counters per day + lifetime totals
          * aggregated rows for the 7-day / month / year tabs

        All data prep happens server-side; the template renders.
        """
        from datetime import date, timedelta
        from core.statsmanager import StatsManager

        sm = StatsManager()

        def _get_dict(group, key):
            v = sm.get_data(group, key)
            return v if isinstance(v, dict) else {}

        consumption_by_day = _get_dict("powerconsumption", "consumption_wh_by_day")
        grid_by_day = _get_dict("powerconsumption", "grid_wh_by_day")
        grid_export_by_day = _get_dict("powerconsumption", "grid_export_wh_by_day")
        pv_by_day = _get_dict("powerconsumption", "pv_wh_by_day")
        battery_charge_by_day = _get_dict("powerconsumption", "battery_charge_wh_by_day")
        battery_discharge_by_day = _get_dict("powerconsumption", "battery_discharge_wh_by_day")
        loss_by_day = _get_dict("powerconsumption", "loss_wh_by_day")
        imbalance_by_day = _get_dict("powerconsumption", "imbalance_wh_by_day")
        # Today-only per-hour breakdown (24-element dict, keys "0".."23").
        loss_by_hour_today = _get_dict("powerconsumption", "loss_wh_by_hour_today")
        imbalance_by_hour_today = _get_dict("powerconsumption", "imbalance_wh_by_hour_today")
        costs_by_day = _get_dict("powerconsumption", "energy_costs_by_day")

        # Skip-counter dict from the abort-condition tracking.
        skip_count_by_day = _get_dict("aborts", "skip_count_by_day")
        solar_skip_by_day = skip_count_by_day.get("solar_forecast") if isinstance(skip_count_by_day.get("solar_forecast"), dict) else {}
        battery_skip_by_day = skip_count_by_day.get("battery_range") if isinstance(skip_count_by_day.get("battery_range"), dict) else {}
        battery_overnext_skip_by_day = skip_count_by_day.get("battery_overnext") if isinstance(skip_count_by_day.get("battery_overnext"), dict) else {}
        battery_expensive_phase_skip_by_day = skip_count_by_day.get("battery_expensive_phase") if isinstance(skip_count_by_day.get("battery_expensive_phase"), dict) else {}
        soc_target_skip_by_day = skip_count_by_day.get("soc_target") if isinstance(skip_count_by_day.get("soc_target"), dict) else {}

        # Lifetime skip totals.
        solar_skip_total = sm.get_data("aborts", "solar_forecast_total") or 0
        battery_skip_total = sm.get_data("aborts", "battery_range_total") or 0
        battery_overnext_skip_total = sm.get_data("aborts", "battery_overnext_total") or 0
        battery_expensive_phase_skip_total = sm.get_data("aborts", "battery_expensive_phase_total") or 0
        soc_target_skip_total = sm.get_data("aborts", "soc_target_total") or 0

        # Battery capacity for cycle calc -- read from StatsManager
        # where seusscore.run_essunit persists it. Victron reports
        # capacity in Ah (changes with state-of-charge / aging), the
        # essunit converts to Wh via the pack voltage; we pull the
        # already-converted value. Falls back to 0 if not yet written
        # (first run before the first essunit cycle); cycles then
        # render as 0 too, which is honest -- we don't fake a number.
        battery_capacity_wh = sm.get_data("ess_unit", "battery_full_wh") or 0
        try:
            battery_capacity_wh = float(battery_capacity_wh)
        except (TypeError, ValueError):
            battery_capacity_wh = 0

        today_iso = date.today().isoformat()
        yesterday_iso = (date.today() - timedelta(days=1)).isoformat()

        def _row_for(iso_date):
            charge_wh = battery_charge_by_day.get(iso_date, 0) or 0
            discharge_wh = battery_discharge_by_day.get(iso_date, 0) or 0
            cycles = (charge_wh / battery_capacity_wh) if battery_capacity_wh > 0 else 0
            # Round-trip efficiency only makes sense over completed
            # charge/discharge cycles. When discharge > charge in the
            # range (e.g. battery started high and was net-drained, or
            # the day hasn't seen a real charge yet), the ratio yields
            # nonsense like 155% -- the surplus is energy that was
            # already in the battery before the range started, not a
            # round-trip gain. Mark these as invalid (-1) so the UI
            # can render them as "--" instead of a misleading number.
            if charge_wh > 0 and discharge_wh <= charge_wh:
                rte = discharge_wh / charge_wh * 100.0
            else:
                rte = -1
            return {
                "iso": iso_date,
                "consumption_wh": consumption_by_day.get(iso_date, 0),
                "grid_wh": grid_by_day.get(iso_date, 0),
                "grid_export_wh": grid_export_by_day.get(iso_date, 0),
                "pv_wh": pv_by_day.get(iso_date, 0),
                "battery_charge_wh": charge_wh,
                "battery_discharge_wh": discharge_wh,
                "cost_eur": costs_by_day.get(iso_date, 0),
                "cycles": round(cycles, 3),
                "rte_pct": round(rte, 1),
                "loss_wh": loss_by_day.get(iso_date, 0) or 0,
                "imbalance_wh": imbalance_by_day.get(iso_date, 0) or 0,
                "solar_skips": int(solar_skip_by_day.get(iso_date, 0)),
                "battery_skips": int(battery_skip_by_day.get(iso_date, 0)),
                "battery_overnext_skips": int(battery_overnext_skip_by_day.get(iso_date, 0)),
                "battery_expensive_phase_skips": int(battery_expensive_phase_skip_by_day.get(iso_date, 0)),
                "soc_target_skips": int(soc_target_skip_by_day.get(iso_date, 0)),
            }

        # ---- Aggregation helpers for multi-day tabs ----
        def _sum_range(d, start_iso, end_iso):
            """Sum dict values for ISO keys in [start_iso, end_iso] inclusive."""
            return sum(
                (v or 0) for k, v in (d or {}).items()
                if isinstance(k, str) and start_iso <= k <= end_iso
            )

        def _aggregate_range(start, end):
            """Build a stats row for a date range (start..end inclusive)."""
            start_iso = start.isoformat()
            end_iso = end.isoformat()
            charge_wh = _sum_range(battery_charge_by_day, start_iso, end_iso)
            discharge_wh = _sum_range(battery_discharge_by_day, start_iso, end_iso)
            cycles = (charge_wh / battery_capacity_wh) if battery_capacity_wh > 0 else 0
            # Same clamp as _row_for above: discharge > charge means we
            # are draining a pre-existing battery state, not closing a
            # round-trip cycle. Mark as invalid so the UI shows "--".
            if charge_wh > 0 and discharge_wh <= charge_wh:
                rte = discharge_wh / charge_wh * 100.0
            else:
                rte = -1
            # For skip counters in a range we sum across days.
            solar_skips = sum(
                (v or 0) for k, v in (solar_skip_by_day or {}).items()
                if isinstance(k, str) and start_iso <= k <= end_iso
            )
            battery_skips = sum(
                (v or 0) for k, v in (battery_skip_by_day or {}).items()
                if isinstance(k, str) and start_iso <= k <= end_iso
            )
            battery_overnext_skips = sum(
                (v or 0) for k, v in (battery_overnext_skip_by_day or {}).items()
                if isinstance(k, str) and start_iso <= k <= end_iso
            )
            battery_expensive_phase_skips = sum(
                (v or 0) for k, v in (battery_expensive_phase_skip_by_day or {}).items()
                if isinstance(k, str) and start_iso <= k <= end_iso
            )
            soc_target_skips = sum(
                (v or 0) for k, v in (soc_target_skip_by_day or {}).items()
                if isinstance(k, str) and start_iso <= k <= end_iso
            )
            return {
                "iso": f"{start_iso} \u2192 {end_iso}",
                "consumption_wh": _sum_range(consumption_by_day, start_iso, end_iso),
                "grid_wh": _sum_range(grid_by_day, start_iso, end_iso),
                "grid_export_wh": _sum_range(grid_export_by_day, start_iso, end_iso),
                "pv_wh": _sum_range(pv_by_day, start_iso, end_iso),
                "battery_charge_wh": charge_wh,
                "battery_discharge_wh": discharge_wh,
                "cost_eur": _sum_range(costs_by_day, start_iso, end_iso),
                "cycles": round(cycles, 3),
                "rte_pct": round(rte, 1),
                "loss_wh": _sum_range(loss_by_day, start_iso, end_iso),
                "imbalance_wh": _sum_range(imbalance_by_day, start_iso, end_iso),
                "solar_skips": int(solar_skips),
                "battery_skips": int(battery_skips),
                "battery_overnext_skips": int(battery_overnext_skips),
                "battery_expensive_phase_skips": int(battery_expensive_phase_skips),
                "soc_target_skips": int(soc_target_skips),
            }

        today = date.today()
        # Last 7 days = today minus 6 .. today
        week_row = _aggregate_range(today - timedelta(days=6), today)
        # Current calendar month: month-start to today
        month_start = today.replace(day=1)
        month_row = _aggregate_range(month_start, today)
        # Current calendar year: Jan 1 to today
        year_start = today.replace(month=1, day=1)
        year_row = _aggregate_range(year_start, today)

        # ---- Chart series ----
        # Hourly arrays for the intraday chart. 24 slots in Wh; missing
        # slots default to 0.
        hourly_by_day = _get_dict("powerconsumption", "hourly_wh_by_day")
        hourly_today = hourly_by_day.get(today_iso) or [0] * 24
        if not isinstance(hourly_today, list) or len(hourly_today) != 24:
            hourly_today = [0] * 24
        hourly_yesterday = hourly_by_day.get(yesterday_iso) or [0] * 24
        if not isinstance(hourly_yesterday, list) or len(hourly_yesterday) != 24:
            hourly_yesterday = [0] * 24

        # 30-day daily history series.
        history_days = []
        for offset in range(29, -1, -1):
            d = (today - timedelta(days=offset)).isoformat()
            history_days.append({
                "iso": d,
                "consumption_wh": consumption_by_day.get(d, 0) or 0,
                "grid_wh": grid_by_day.get(d, 0) or 0,
                "pv_wh": pv_by_day.get(d, 0) or 0,
            })

        # SVG charts -- generated server-side so they work without
        # Chart.js (no internet at the VenusOS host).
        intraday_svg = self._render_intraday_svg(hourly_today, hourly_yesterday)
        history_svg = self._render_history_svg(history_days)

        stats_data = {
            "today": _row_for(today_iso),
            "yesterday": _row_for(yesterday_iso),
            "week": week_row,
            "month": month_row,
            "year": year_row,
            "history_days_available": len([
                k for k in consumption_by_day.keys()
                if isinstance(k, str) and k != today_iso
            ]),
            "battery_capacity_wh": battery_capacity_wh,
            "solar_skip_total": int(solar_skip_total),
            "battery_skip_total": int(battery_skip_total),
            "battery_overnext_skip_total": int(battery_overnext_skip_total),
            "battery_expensive_phase_skip_total": int(battery_expensive_phase_skip_total),
            "soc_target_skip_total": int(soc_target_skip_total),
            "intraday_svg": intraday_svg,
            "history_svg": history_svg,
            # Solar forecast snapshot, persisted by openmeteo.py at the
            # end of each successful forecast run. None when the
            # forecast hasn't run yet (use_solar_forecast_to_abort
            # disabled, no PV panels configured, or open-meteo
            # unreachable). The template renders "--" in that case.
            "solar_forecast": {
                "today_wh": sm.get_data("solar", "forecast_today_wh"),
                "tomorrow_wh": sm.get_data("solar", "forecast_tomorrow_wh"),
                "measured_today_wh": sm.get_data("solar", "forecast_measured_today_wh"),
                "rest_today_wh": sm.get_data("solar", "forecast_rest_today_wh"),
                "adjustment_factor": (sm.get_data("solar", "adjustment_factor") or [None])[0],
                "efficiency_pct": (sm.get_data("solar", "efficiency") or [None])[0],
            },
            # Per-hour energy balance for today: list of 24 dicts with
            # hour, loss_wh, imbalance_wh. Hour slots without data show
            # 0 so the table always has 24 rows. Lets the user spot
            # WHEN during the day the balance went negative -- a steady
            # sensor offset shows up in every hour, while a bug tied to
            # a specific event (e.g. inverter standby at night) shows
            # up only in those hours.
            "hourly_balance": [
                {
                    "hour": h,
                    "loss_wh": float(loss_by_hour_today.get(str(h), 0) or 0),
                    "imbalance_wh": float(imbalance_by_hour_today.get(str(h), 0) or 0),
                }
                for h in range(24)
            ],
        }

        return template('stats', stats=stats_data,
                        version=version.__version__, root=self.view_path)

    # ------------------------------------------------------------------
    # SVG chart helpers for the stats page. Server-side rendering keeps
    # the page working in offline LAN setups (typical VenusOS).
    # ------------------------------------------------------------------

    @staticmethod
    def _render_intraday_svg(today_arr, yesterday_arr):
        """
        24-hour bar chart, today (blue) overlaid on yesterday (grey).
        Layout matches the price chart in style: SVG, border, fixed
        width per hour.
        """
        bar_w = 30           # pixels per hour
        gap_w = 8
        chart_w = 24 * (bar_w + gap_w)
        chart_h = 200
        baseline_y = chart_h + 20  # leaves room for x-axis labels
        svg_h = baseline_y + 25

        max_v = max(max(today_arr or [0]), max(yesterday_arr or [0]), 1)
        scale = chart_h / max_v if max_v > 0 else 1.0

        parts = [
            f'<svg width="{chart_w + 50}" height="{svg_h}" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'style="border:1px solid #ccc; background:#fff;">',
            # Y-axis grid: 4 horizontal reference lines + scale labels.
        ]
        for frac, label in [(0.0, "0"), (0.25, ""), (0.5, ""), (0.75, ""),
                            (1.0, f"{int(max_v)}")]:
            y = baseline_y - chart_h * frac
            parts.append(
                f'<line x1="40" y1="{y}" x2="{chart_w + 40}" y2="{y}" '
                f'stroke="#eee" stroke-width="1"/>'
            )
            if label:
                parts.append(
                    f'<text x="38" y="{y + 4}" font-size="10" '
                    f'text-anchor="end" fill="#666">{label}</text>'
                )

        # Bars: yesterday (grey) drawn first, today (blue) drawn second
        # so today wins overlap. Each pair shares its hour slot but is
        # offset by a few pixels for readability.
        for h in range(24):
            x_base = 40 + h * (bar_w + gap_w)
            y_h = today_arr[h] or 0
            y_h_y = yesterday_arr[h] or 0

            # Yesterday: full-width grey, behind
            if y_h_y > 0:
                bar_h = y_h_y * scale
                parts.append(
                    f'<rect x="{x_base}" y="{baseline_y - bar_h}" '
                    f'width="{bar_w}" height="{bar_h}" '
                    f'fill="#bbb" opacity="0.55"/>'
                )
            # Today: same width, blue, in front
            if y_h > 0:
                bar_h = y_h * scale
                parts.append(
                    f'<rect x="{x_base}" y="{baseline_y - bar_h}" '
                    f'width="{bar_w}" height="{bar_h}" '
                    f'fill="#4285f4"/>'
                )
            # Hour label below the bar
            parts.append(
                f'<text x="{x_base + bar_w / 2}" y="{baseline_y + 14}" '
                f'font-size="10" text-anchor="middle" fill="#444">'
                f'{h:02d}</text>'
            )

        # Legend: bottom right
        legend_y = svg_h - 5
        parts.append(
            f'<rect x="{chart_w - 110}" y="{legend_y - 12}" '
            f'width="10" height="10" fill="#bbb" opacity="0.55"/>'
            f'<text x="{chart_w - 95}" y="{legend_y - 3}" font-size="10" '
            f'fill="#444">Yesterday</text>'
            f'<rect x="{chart_w - 40}" y="{legend_y - 12}" '
            f'width="10" height="10" fill="#4285f4"/>'
            f'<text x="{chart_w - 25}" y="{legend_y - 3}" font-size="10" '
            f'fill="#444">Today</text>'
        )
        # Y-axis title
        parts.append(
            f'<text x="10" y="20" font-size="11" fill="#666">Wh</text>'
        )
        parts.append('</svg>')
        return ''.join(parts)

    @staticmethod
    def _render_history_svg(history_days):
        """
        Multi-line chart over 30 days: consumption (blue), grid import
        (red), PV (green). Lines are polylines without smoothing for
        clarity.
        """
        if not history_days:
            return '<p style="color:#888;">No history data.</p>'

        chart_w = 900
        chart_h = 220
        margin_left = 50
        margin_right = 20
        margin_top = 20
        margin_bottom = 40
        plot_w = chart_w - margin_left - margin_right
        plot_h = chart_h - margin_top - margin_bottom

        consumption = [d["consumption_wh"] for d in history_days]
        grid = [d["grid_wh"] for d in history_days]
        pv = [d["pv_wh"] for d in history_days]
        max_v = max(max(consumption + grid + pv), 1)

        n = len(history_days)
        x_step = plot_w / max(n - 1, 1)

        def _polyline(values, color, dash=None):
            pts = []
            for i, v in enumerate(values):
                x = margin_left + i * x_step
                y = margin_top + plot_h - (v / max_v) * plot_h
                pts.append(f"{x:.1f},{y:.1f}")
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ''
            return (
                f'<polyline points="{" ".join(pts)}" fill="none" '
                f'stroke="{color}" stroke-width="2"{dash_attr}/>'
            )

        parts = [
            f'<svg width="{chart_w}" height="{chart_h}" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'style="border:1px solid #ccc; background:#fff;">',
        ]
        # Y-axis grid + labels (5 levels)
        for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
            y = margin_top + plot_h - frac * plot_h
            parts.append(
                f'<line x1="{margin_left}" y1="{y}" '
                f'x2="{chart_w - margin_right}" y2="{y}" '
                f'stroke="#eee" stroke-width="1"/>'
            )
            label_v = int(frac * max_v)
            parts.append(
                f'<text x="{margin_left - 5}" y="{y + 4}" font-size="10" '
                f'text-anchor="end" fill="#666">{label_v}</text>'
            )
        # X-axis labels: every 5th day (MM-DD)
        for i, d in enumerate(history_days):
            if i % 5 == 0 or i == n - 1:
                x = margin_left + i * x_step
                parts.append(
                    f'<text x="{x}" y="{chart_h - margin_bottom + 14}" '
                    f'font-size="10" text-anchor="middle" fill="#444">'
                    f'{d["iso"][5:]}</text>'  # MM-DD
                )

        parts.append(_polyline(consumption, "#4285f4"))   # blue
        parts.append(_polyline(grid, "#d04040"))          # red
        parts.append(_polyline(pv, "#2a8a2a"))            # green

        # Legend top right
        lx = chart_w - margin_right - 220
        ly = margin_top + 5
        parts.append(
            f'<rect x="{lx}" y="{ly}" width="14" height="3" fill="#4285f4"/>'
            f'<text x="{lx + 18}" y="{ly + 5}" font-size="10" fill="#444">Consumption</text>'
            f'<rect x="{lx + 90}" y="{ly}" width="14" height="3" fill="#d04040"/>'
            f'<text x="{lx + 108}" y="{ly + 5}" font-size="10" fill="#444">Grid Import</text>'
            f'<rect x="{lx + 175}" y="{ly}" width="14" height="3" fill="#2a8a2a"/>'
            f'<text x="{lx + 193}" y="{ly + 5}" font-size="10" fill="#444">PV</text>'
        )
        # Y-axis title
        parts.append(
            f'<text x="10" y="{margin_top + 5}" font-size="11" fill="#666">Wh / day</text>'
        )
        parts.append('</svg>')
        return ''.join(parts)

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

        # Pre-compute hour-level membership: if any quarter of an hour
        # is in a charge/discharge block, the WHOLE hour visually
        # belongs to that block. This kills the "white sliver" effect
        # that used to appear when fill_gaps_with_short_clusters
        # produced 3-quarter blocks (e.g. 12:00-12:45 discharge): the
        # remaining 12:45 quarter used to fall through to gainsboro;
        # now it inherits the hour's block colour.
        charge_hours = {h for (h, _q) in charge_quarters}
        discharge_hours = {h for (h, _q) in discharge_quarters}

        # Draw each hour as 4 stacked quarter-width slices.
        # Each hour bar is wrapped in a <g> element with a <title>
        # child -- browsers render this as a hover tooltip showing the
        # individual quarter prices, so the user can see what's behind
        # the hourly average.
        slice_width = (width - 3) / 4.0  # leave 3px gap between hour groups
        for hour in range(24):
            price = data.get(hour)
            # If hourly aggregation lost this hour but per-quarter prices
            # exist for it (e.g. due to upstream item-list filtering),
            # rebuild the hourly average from the quarter prices we have.
            # This was the cause of the "white bar despite known cheap
            # price" symptom: data[hour] was None, so the inner branch
            # never ran and the bar fell through to gainsboro.
            if price is None:
                hour_q_prices = [
                    quarter_prices[(hour, qi)]
                    for qi in range(4)
                    if (hour, qi) in quarter_prices
                ]
                if hour_q_prices:
                    price = sum(hour_q_prices) / len(hour_q_prices)
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

            hour_has_charge = hour in charge_hours
            hour_has_discharge = hour in discharge_hours

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
                    elif hour_has_charge and below_cap:
                        # This quarter is the leftover of a 3-quarter
                        # charge block (fill-gap result). Inherit the
                        # hour's charge colour so the bar looks solid.
                        slice_color = self._green_color(hour, current_hour, tomorrow)
                    elif hour_has_discharge:
                        # Leftover quarter inside an otherwise discharge
                        # hour. Inherit the discharge colour.
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

        # Bottle's default wsgiref-based dev server prints every HTTP
        # request to stderr ("127.0.0.1 - - [date] GET /stats 200 ..."),
        # which floods /tmp/seuss_error.log because service/run pipes
        # stderr there to capture real Python tracebacks. We patch the
        # wsgiref request handler globally to drop those access-log
        # lines. Real error output (tracebacks, sys.stderr writes,
        # bottle's log_error()) still goes through, so crashes are
        # still recorded in the error log.
        from wsgiref.simple_server import WSGIRequestHandler
        WSGIRequestHandler.log_message = lambda *a, **kw: None

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
