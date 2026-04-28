<!-- stats.tpl -->
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Statistics</title>
    <link rel="stylesheet" type="text/css" href="/static/styles.css">
    <link rel="shortcut icon" href="/static/favicon.ico" />
    <style>
        /*
         * Stats page layout. The global body uses
         * `display: flex; align-items: center` which makes flex-item
         * children take their content width and centre. We force the
         * stats containers to full width so the grid spreads out.
         *
         * Note also: styles.css has a generic `.active { animation:
         * spin ... }` rule meant for the loading spinner. The Today
         * tab has class="active" and would inherit that spin -- which
         * is why we override animation:none below for the tabs.
         */
        .stats-container {
            width: 99%;
            box-sizing: border-box;
        }

        .stats-tabs {
            display: flex;
            gap: 1em;
            padding: 0.5em 1em;
            border-bottom: 1px solid #ccc;
            margin-bottom: 1em;
            flex-wrap: wrap;
        }
        .stats-tabs a {
            color: #4285f4;
            text-decoration: none;
            font-weight: bold;
            cursor: pointer;
        }
        .stats-tabs a.active {
            color: #2a8a2a;
            animation: none;
        }

        .stats-tile-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            padding: 0 1em 1em 1em;
            box-sizing: border-box;
            width: 100%;
        }
        .stats-tile {
            background: #fff;
            border: 1px solid #ccc;
            border-left: 4px solid #3fff33;
            padding: 10px 14px;
            border-radius: 4px;
        }
        .stats-tile .label {
            font-size: 0.85em;
            color: #555;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .stats-tile .value {
            font-size: 1.6em;
            color: #4285f4;
            font-weight: bold;
            margin-top: 4px;
        }
        .stats-tile .unit {
            font-size: 0.6em;
            color: #888;
            margin-left: 4px;
        }
        .stats-tile.cost .value {
            color: #d04040;
        }
        .stats-tile.pv .value {
            color: #2a8a2a;
        }
        .stats-tile.skip .value {
            color: #b87333;
        }

        .stats-compare {
            margin: 1em;
            border-collapse: collapse;
            width: calc(100% - 2em);
            background: #fff;
        }
        .stats-compare th, .stats-compare td {
            padding: 8px 12px;
            border-bottom: 1px solid #eee;
            text-align: right;
        }
        .stats-compare th {
            background: #f7f7f7;
            color: #333;
        }
        .stats-compare th:first-child,
        .stats-compare td:first-child {
            text-align: left;
            color: #555;
        }

        .stats-section-heading {
            padding: 0 1em;
            margin-top: 1em;
            margin-bottom: 0.4em;
            color: #4285f4;
        }

        .stats-note {
            color: #888;
            font-style: italic;
            padding: 0 1em;
        }

        body.dark-mode .stats-tile,
        body.dark-mode .stats-compare {
            background: #2a2a2a;
            border-color: #444;
            color: #ccc;
        }
        body.dark-mode .stats-compare th {
            background: #1a1a1a;
            color: #ccc;
        }
        body.dark-mode .stats-tile .label {
            color: #aaa;
        }
        body.dark-mode .stats-tabs {
            border-bottom-color: #444;
        }
    </style>
</head>

<body>
    % include('header', title='Statistics')

    <div class="stats-container">

    <div class="stats-tabs">
        <a class="active" data-range="today">[ Today ]</a>
        <a data-range="yesterday">[ Yesterday ]</a>
        <a data-range="week">[ 7 Days ]</a>
        <a data-range="month">[ Month ]</a>
        <a data-range="year">[ Year ]</a>
    </div>

    <%
        # Render the "today" data initially. The JS switcher rewrites
        # tile values from the data-* attributes on the grid -- no
        # round-trip to the server needed.
        active = stats["today"]
    %>

    <div class="stats-tile-grid"
         data-today-iso="{{ stats['today']['iso'] }}"
         data-today-consumption="{{ stats['today']['consumption_wh'] }}"
         data-today-grid="{{ stats['today']['grid_wh'] }}"
         data-today-grid-export="{{ stats['today']['grid_export_wh'] }}"
         data-today-pv="{{ stats['today']['pv_wh'] }}"
         data-today-battery-charge="{{ stats['today']['battery_charge_wh'] }}"
         data-today-battery-discharge="{{ stats['today']['battery_discharge_wh'] }}"
         data-today-cost="{{ stats['today']['cost_eur'] }}"
         data-today-cycles="{{ stats['today']['cycles'] }}"
         data-today-rte="{{ stats['today']['rte_pct'] }}"
         data-today-solar-skips="{{ stats['today']['solar_skips'] }}"
         data-today-battery-skips="{{ stats['today']['battery_skips'] }}"
         data-yesterday-iso="{{ stats['yesterday']['iso'] }}"
         data-yesterday-consumption="{{ stats['yesterday']['consumption_wh'] }}"
         data-yesterday-grid="{{ stats['yesterday']['grid_wh'] }}"
         data-yesterday-grid-export="{{ stats['yesterday']['grid_export_wh'] }}"
         data-yesterday-pv="{{ stats['yesterday']['pv_wh'] }}"
         data-yesterday-battery-charge="{{ stats['yesterday']['battery_charge_wh'] }}"
         data-yesterday-battery-discharge="{{ stats['yesterday']['battery_discharge_wh'] }}"
         data-yesterday-cost="{{ stats['yesterday']['cost_eur'] }}"
         data-yesterday-cycles="{{ stats['yesterday']['cycles'] }}"
         data-yesterday-rte="{{ stats['yesterday']['rte_pct'] }}"
         data-yesterday-solar-skips="{{ stats['yesterday']['solar_skips'] }}"
         data-yesterday-battery-skips="{{ stats['yesterday']['battery_skips'] }}"
         data-week-iso="{{ stats['week']['iso'] }}"
         data-week-consumption="{{ stats['week']['consumption_wh'] }}"
         data-week-grid="{{ stats['week']['grid_wh'] }}"
         data-week-grid-export="{{ stats['week']['grid_export_wh'] }}"
         data-week-pv="{{ stats['week']['pv_wh'] }}"
         data-week-battery-charge="{{ stats['week']['battery_charge_wh'] }}"
         data-week-battery-discharge="{{ stats['week']['battery_discharge_wh'] }}"
         data-week-cost="{{ stats['week']['cost_eur'] }}"
         data-week-cycles="{{ stats['week']['cycles'] }}"
         data-week-rte="{{ stats['week']['rte_pct'] }}"
         data-week-solar-skips="{{ stats['week']['solar_skips'] }}"
         data-week-battery-skips="{{ stats['week']['battery_skips'] }}"
         data-month-iso="{{ stats['month']['iso'] }}"
         data-month-consumption="{{ stats['month']['consumption_wh'] }}"
         data-month-grid="{{ stats['month']['grid_wh'] }}"
         data-month-grid-export="{{ stats['month']['grid_export_wh'] }}"
         data-month-pv="{{ stats['month']['pv_wh'] }}"
         data-month-battery-charge="{{ stats['month']['battery_charge_wh'] }}"
         data-month-battery-discharge="{{ stats['month']['battery_discharge_wh'] }}"
         data-month-cost="{{ stats['month']['cost_eur'] }}"
         data-month-cycles="{{ stats['month']['cycles'] }}"
         data-month-rte="{{ stats['month']['rte_pct'] }}"
         data-month-solar-skips="{{ stats['month']['solar_skips'] }}"
         data-month-battery-skips="{{ stats['month']['battery_skips'] }}"
         data-year-iso="{{ stats['year']['iso'] }}"
         data-year-consumption="{{ stats['year']['consumption_wh'] }}"
         data-year-grid="{{ stats['year']['grid_wh'] }}"
         data-year-grid-export="{{ stats['year']['grid_export_wh'] }}"
         data-year-pv="{{ stats['year']['pv_wh'] }}"
         data-year-battery-charge="{{ stats['year']['battery_charge_wh'] }}"
         data-year-battery-discharge="{{ stats['year']['battery_discharge_wh'] }}"
         data-year-cost="{{ stats['year']['cost_eur'] }}"
         data-year-cycles="{{ stats['year']['cycles'] }}"
         data-year-rte="{{ stats['year']['rte_pct'] }}"
         data-year-solar-skips="{{ stats['year']['solar_skips'] }}"
         data-year-battery-skips="{{ stats['year']['battery_skips'] }}">

        <div class="stats-tile">
            <div class="label">Range</div>
            <div class="value" id="tile-date" style="font-size:1.0em;">{{ active['iso'] }}</div>
        </div>

        <div class="stats-tile">
            <div class="label">House Consumption</div>
            <div class="value">
                <span id="tile-consumption">{{ "{:.0f}".format(active['consumption_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile">
            <div class="label">Grid Import</div>
            <div class="value">
                <span id="tile-grid">{{ "{:.0f}".format(active['grid_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile pv">
            <div class="label">Grid Export</div>
            <div class="value">
                <span id="tile-grid-export">{{ "{:.0f}".format(active['grid_export_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile pv">
            <div class="label">PV Production</div>
            <div class="value">
                <span id="tile-pv">{{ "{:.0f}".format(active['pv_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile">
            <div class="label">Battery Charged</div>
            <div class="value">
                <span id="tile-battery-charge">{{ "{:.0f}".format(active['battery_charge_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile">
            <div class="label">Battery Discharged</div>
            <div class="value">
                <span id="tile-battery-discharge">{{ "{:.0f}".format(active['battery_discharge_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile">
            <div class="label">Cycles</div>
            <div class="value"
                 title="charge_wh / battery_capacity_wh ({{ stats['battery_capacity_wh'] }} Wh)">
                <span id="tile-cycles">{{ "{:.3f}".format(active['cycles']) }}</span>
            </div>
        </div>

        <div class="stats-tile"
             title="Round-trip efficiency: discharge_wh / charge_wh">
            <div class="label">RTE</div>
            <div class="value">
                <span id="tile-rte">{{ "{:.1f}".format(active['rte_pct']) }}</span>
                <span class="unit">%</span>
            </div>
        </div>

        <div class="stats-tile cost"
             title="Stored as cents internally; shown as EUR.">
            <div class="label">Grid Cost</div>
            <div class="value">
                <span id="tile-cost"
                      title="{{ '{:.4f}'.format(active['cost_eur']) }} ¢">{{ "{:.4f}".format(active['cost_eur'] / 100.0) }}</span>
                <span class="unit">€</span>
            </div>
        </div>

        <div class="stats-tile skip"
             title="How often the solar-forecast abort condition skipped a charge in this range.">
            <div class="label">Solar Skips</div>
            <div class="value">
                <span id="tile-solar-skips">{{ active['solar_skips'] }}</span>
            </div>
        </div>

        <div class="stats-tile skip"
             title="How often the battery-range abort condition skipped a charge in this range.">
            <div class="label">Battery Skips</div>
            <div class="value">
                <span id="tile-battery-skips">{{ active['battery_skips'] }}</span>
            </div>
        </div>
    </div>

    <h3 class="stats-section-heading">Today vs. Yesterday</h3>
    <table class="stats-compare">
        <thead>
            <tr>
                <th>Metric</th>
                <th>Today ({{ stats['today']['iso'] }})</th>
                <th>Yesterday ({{ stats['yesterday']['iso'] }})</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>House consumption</td>
                <td>{{ "{:.0f}".format(stats['today']['consumption_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['consumption_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>Grid import</td>
                <td>{{ "{:.0f}".format(stats['today']['grid_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['grid_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>Grid export</td>
                <td>{{ "{:.0f}".format(stats['today']['grid_export_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['grid_export_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>PV production</td>
                <td>{{ "{:.0f}".format(stats['today']['pv_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['pv_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>Battery charged</td>
                <td>{{ "{:.0f}".format(stats['today']['battery_charge_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['battery_charge_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>Battery discharged</td>
                <td>{{ "{:.0f}".format(stats['today']['battery_discharge_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['battery_discharge_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>Cycles</td>
                <td>{{ "{:.3f}".format(stats['today']['cycles']) }}</td>
                <td>{{ "{:.3f}".format(stats['yesterday']['cycles']) }}</td>
            </tr>
            <tr>
                <td>RTE</td>
                <td>{{ "{:.1f}".format(stats['today']['rte_pct']) }} %</td>
                <td>{{ "{:.1f}".format(stats['yesterday']['rte_pct']) }} %</td>
            </tr>
            <tr>
                <td>Solar-forecast skips</td>
                <td>{{ stats['today']['solar_skips'] }}</td>
                <td>{{ stats['yesterday']['solar_skips'] }}</td>
            </tr>
            <tr>
                <td>Battery-range skips</td>
                <td>{{ stats['today']['battery_skips'] }}</td>
                <td>{{ stats['yesterday']['battery_skips'] }}</td>
            </tr>
            <tr>
                <td>Grid cost</td>
                <td title="{{ '{:.4f}'.format(stats['today']['cost_eur']) }} ¢">{{ "{:.4f}".format(stats['today']['cost_eur'] / 100.0) }} €</td>
                <td title="{{ '{:.4f}'.format(stats['yesterday']['cost_eur']) }} ¢">{{ "{:.4f}".format(stats['yesterday']['cost_eur'] / 100.0) }} €</td>
            </tr>
        </tbody>
    </table>

    <h3 class="stats-section-heading">Lifetime Skip Counters</h3>
    <table class="stats-compare">
        <thead>
            <tr>
                <th>Metric</th>
                <th>All-time</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Solar-forecast skips total</td>
                <td>{{ stats['solar_skip_total'] }}</td>
            </tr>
            <tr>
                <td>Battery-range skips total</td>
                <td>{{ stats['battery_skip_total'] }}</td>
            </tr>
        </tbody>
    </table>

    <h3 class="stats-section-heading">Intraday: Hourly Consumption</h3>
    <div style="padding: 0 1em 1em 1em; overflow-x: auto;">
        {{ !stats['intraday_svg'] }}
    </div>

    <h3 class="stats-section-heading">Last 30 Days</h3>
    <div style="padding: 0 1em 1em 1em; overflow-x: auto;">
        {{ !stats['history_svg'] }}
    </div>

    <p class="stats-note">
        % if stats['history_days_available'] == 0:
            No completed days in history yet -- the Yesterday / 7 Days / Month / Year
            tabs will populate as SEUSS keeps running.
        % else:
            {{ stats['history_days_available'] }} day(s) of completed history
            available. Charts (intraday curves and forecast vs. actual) will be
            added in Part C.
        % end
    </p>

    </div><!-- /stats-container -->

    % include('footer')

    <script>
        // Tab switcher. We have data for all five ranges as data-*
        // attributes on the grid; switching just rewrites tile values
        // and the highlighted date. No fetch needed.
        (function() {
            const grid = document.querySelector('.stats-tile-grid');
            if (!grid) return;
            const tabs = document.querySelectorAll('.stats-tabs a[data-range]');

            const formatNum = (v, decimals) => {
                const n = parseFloat(v);
                if (isNaN(n)) return '0';
                return n.toFixed(decimals);
            };

            const setText = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.textContent = val;
            };

            function showRange(range) {
                const get = key => grid.getAttribute('data-' + range + '-' + key);

                setText('tile-date', get('iso'));
                setText('tile-consumption', formatNum(get('consumption'), 0));
                setText('tile-grid', formatNum(get('grid'), 0));
                setText('tile-grid-export', formatNum(get('grid-export'), 0));
                setText('tile-pv', formatNum(get('pv'), 0));
                setText('tile-battery-charge', formatNum(get('battery-charge'), 0));
                setText('tile-battery-discharge', formatNum(get('battery-discharge'), 0));
                setText('tile-cycles', formatNum(get('cycles'), 3));
                setText('tile-rte', formatNum(get('rte'), 1));
                setText('tile-solar-skips', get('solar-skips') || '0');
                setText('tile-battery-skips', get('battery-skips') || '0');

                // Cost: stored in cents, shown as EUR; tooltip keeps cents.
                const costRaw = parseFloat(get('cost')) || 0;
                const tileCost = document.getElementById('tile-cost');
                if (tileCost) {
                    tileCost.textContent = (costRaw / 100.0).toFixed(4);
                    tileCost.setAttribute('title', costRaw.toFixed(4) + ' ¢');
                }

                tabs.forEach(t => {
                    if (t.getAttribute('data-range') === range) {
                        t.classList.add('active');
                    } else {
                        t.classList.remove('active');
                    }
                });
            }

            tabs.forEach(tab => {
                tab.addEventListener('click', e => {
                    e.preventDefault();
                    showRange(tab.getAttribute('data-range'));
                });
            });
        })();
    </script>
</body>
</html>
