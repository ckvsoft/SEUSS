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
         data-today-loss="{{ stats['today']['loss_wh'] }}"
         data-today-imbalance="{{ stats['today']['imbalance_wh'] }}"
         data-today-solar-skips="{{ stats['today']['solar_skips'] }}"
         data-today-battery-skips="{{ stats['today']['battery_skips'] }}"
         data-today-battery-overnext-skips="{{ stats['today']['battery_overnext_skips'] }}"
         data-today-battery-expensive-phase-skips="{{ stats['today']['battery_expensive_phase_skips'] }}"
         data-today-soc-target-skips="{{ stats['today']['soc_target_skips'] }}"
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
         data-yesterday-loss="{{ stats['yesterday']['loss_wh'] }}"
         data-yesterday-imbalance="{{ stats['yesterday']['imbalance_wh'] }}"
         data-yesterday-solar-skips="{{ stats['yesterday']['solar_skips'] }}"
         data-yesterday-battery-skips="{{ stats['yesterday']['battery_skips'] }}"
         data-yesterday-battery-overnext-skips="{{ stats['yesterday']['battery_overnext_skips'] }}"
         data-yesterday-battery-expensive-phase-skips="{{ stats['yesterday']['battery_expensive_phase_skips'] }}"
         data-yesterday-soc-target-skips="{{ stats['yesterday']['soc_target_skips'] }}"
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
         data-week-loss="{{ stats['week']['loss_wh'] }}"
         data-week-imbalance="{{ stats['week']['imbalance_wh'] }}"
         data-week-solar-skips="{{ stats['week']['solar_skips'] }}"
         data-week-battery-skips="{{ stats['week']['battery_skips'] }}"
         data-week-battery-overnext-skips="{{ stats['week']['battery_overnext_skips'] }}"
         data-week-battery-expensive-phase-skips="{{ stats['week']['battery_expensive_phase_skips'] }}"
         data-week-soc-target-skips="{{ stats['week']['soc_target_skips'] }}"
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
         data-month-loss="{{ stats['month']['loss_wh'] }}"
         data-month-imbalance="{{ stats['month']['imbalance_wh'] }}"
         data-month-solar-skips="{{ stats['month']['solar_skips'] }}"
         data-month-battery-skips="{{ stats['month']['battery_skips'] }}"
         data-month-battery-overnext-skips="{{ stats['month']['battery_overnext_skips'] }}"
         data-month-battery-expensive-phase-skips="{{ stats['month']['battery_expensive_phase_skips'] }}"
         data-month-soc-target-skips="{{ stats['month']['soc_target_skips'] }}"
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
         data-year-loss="{{ stats['year']['loss_wh'] }}"
         data-year-imbalance="{{ stats['year']['imbalance_wh'] }}"
         data-year-solar-skips="{{ stats['year']['solar_skips'] }}"
         data-year-battery-skips="{{ stats['year']['battery_skips'] }}"
         data-year-battery-overnext-skips="{{ stats['year']['battery_overnext_skips'] }}"
         data-year-battery-expensive-phase-skips="{{ stats['year']['battery_expensive_phase_skips'] }}"
         data-year-soc-target-skips="{{ stats['year']['soc_target_skips'] }}">

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
                 title="Battery cycles in this range = charge_wh / battery_capacity_wh. Capacity ({{ stats['battery_capacity_wh'] }} Wh) is auto-detected from the pack voltage on first essunit loop after start. If you see exactly 0.0 it usually means either (a) no charging has happened in the range yet, or (b) the essunit hasn't reported a valid battery voltage yet so capacity is still unknown -- check the log for 'Detected … LiFePO4 system' to confirm detection ran.">
                <span id="tile-cycles">{{ "{:.3f}".format(active['cycles']) }}</span>
            </div>
        </div>

        <div class="stats-tile"
             title="Round-trip efficiency: how much of the energy you put INTO the battery comes back OUT (discharge_wh / charge_wh × 100). For a healthy LFP system the long-term average is around 92-96%. Short ranges where the battery was net-drained (started high, no full charge yet) show '--' because RTE is only meaningful when a full charge AND discharge have both happened in the range. Look at the Month/Year tabs for a realistic figure.">
            <div class="label">RTE</div>
            <div class="value">
                <span id="tile-rte">{{ "--" if active['rte_pct'] < 0 else "{:.1f}".format(active['rte_pct']) }}</span>
                <span class="unit">%</span>
            </div>
        </div>

        <div class="stats-tile"
             title="Energy 'loss' integrated over the range: max(input − usable, 0). 'Input' = battery discharge + grid import + PV. 'Usable' = AC consumption + grid export + battery charge. Realistically this is mostly inverter / wiring losses and should be a single-digit percent of the total throughput.">
            <div class="label">Loss</div>
            <div class="value">
                <span id="tile-loss">{{ "{:.0f}".format(active['loss_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile"
             title="Signed energy imbalance integrated over the range: input − usable WITHOUT the max(...,0) clamp. A POSITIVE value is normal -- it equals the inverter / wiring loss. A NEGATIVE value means SEUSS recorded more consumption than the known sources can supply, which points at a missing source (e.g. a PV inverter not registered with the GX) or a sign-convention issue with one of the sensors. Use this together with Loss to spot whether the daily energy balance actually closes.">
            <div class="label">Imbalance</div>
            <div class="value">
                <span id="tile-imbalance">{{ "{:+.0f}".format(active['imbalance_wh']) }}</span>
                <span class="unit">Wh</span>
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

        <div class="stats-tile skip"
             title="How often the look-ahead 'covers until OVERNEXT cheap cluster' abort skipped a charge in this range. Only fires when the battery alone is enough to bridge through the next cheap cluster AND the expensive phase that follows.">
            <div class="label">Overnext Skips</div>
            <div class="value">
                <span id="tile-battery-overnext-skips">{{ active['battery_overnext_skips'] }}</span>
            </div>
        </div>

        <div class="stats-tile skip"
             title="How often the 'covers entire expensive phase' abort skipped a charge in this range. Fires when the battery alone covers consumption until the next charge cluster of any price -- the recommended successor to the older battery-range / overnext aborts.">
            <div class="label">Expensive Phase Skips</div>
            <div class="value">
                <span id="tile-battery-expensive-phase-skips">{{ active['battery_expensive_phase_skips'] }}</span>
            </div>
        </div>

        <div class="stats-tile skip"
             title="Always-on safety abort: how often charging was skipped because the battery already reached the SOC target configured in the Victron Scheduler (with 1% tolerance). If this is non-zero you've avoided pointless 'charge-to-100%-while-already-there' cycles.">
            <div class="label">SOC Target Skips</div>
            <div class="value">
                <span id="tile-soc-target-skips">{{ active['soc_target_skips'] }}</span>
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
                <td>{{ "--" if stats['today']['rte_pct'] < 0 else "{:.1f} %".format(stats['today']['rte_pct']) }}</td>
                <td>{{ "--" if stats['yesterday']['rte_pct'] < 0 else "{:.1f} %".format(stats['yesterday']['rte_pct']) }}</td>
            </tr>
            <tr>
                <td>Loss</td>
                <td>{{ "{:.0f}".format(stats['today']['loss_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['loss_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>Imbalance (signed)</td>
                <td>{{ "{:+.0f}".format(stats['today']['imbalance_wh']) }} Wh</td>
                <td>{{ "{:+.0f}".format(stats['yesterday']['imbalance_wh']) }} Wh</td>
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
                <td>Overnext-cluster skips</td>
                <td>{{ stats['today']['battery_overnext_skips'] }}</td>
                <td>{{ stats['yesterday']['battery_overnext_skips'] }}</td>
            </tr>
            <tr>
                <td>Expensive-phase skips</td>
                <td>{{ stats['today']['battery_expensive_phase_skips'] }}</td>
                <td>{{ stats['yesterday']['battery_expensive_phase_skips'] }}</td>
            </tr>
            <tr>
                <td>SOC-target skips</td>
                <td>{{ stats['today']['soc_target_skips'] }}</td>
                <td>{{ stats['yesterday']['soc_target_skips'] }}</td>
            </tr>
            <tr>
                <td>Grid cost</td>
                <td title="{{ '{:.4f}'.format(stats['today']['cost_eur']) }} ¢">{{ "{:.4f}".format(stats['today']['cost_eur'] / 100.0) }} €</td>
                <td title="{{ '{:.4f}'.format(stats['yesterday']['cost_eur']) }} ¢">{{ "{:.4f}".format(stats['yesterday']['cost_eur'] / 100.0) }} €</td>
            </tr>
        </tbody>
    </table>

    <h3 class="stats-section-heading">Today's Hourly Energy Balance</h3>
    <p style="font-size: 0.9em; opacity: 0.85; margin: 0.4em 0 0.8em 0;">
        Per-hour breakdown of today's energy balance. <b>Loss</b> is non-negative
        (input − usable when positive), typical inverter / wiring loss should be
        a few percent of throughput. <b>Imbalance</b> is signed: a NEGATIVE value
        means consumption exceeded the known sources for that hour, which points
        at a missing source or a sensor sign issue. Hours with no activity yet
        (loss = 0 and imbalance = 0) are hidden so the table only shows what's
        actually happened today.
    </p>
    <table class="stats-compare">
        <thead>
            <tr>
                <th>Hour</th>
                <th>Loss</th>
                <th>Imbalance (signed)</th>
            </tr>
        </thead>
        <tbody>
            % nonzero_rows = [hb for hb in stats.get('hourly_balance', []) if hb['loss_wh'] != 0 or hb['imbalance_wh'] != 0]
            % if not nonzero_rows:
            <tr>
                <td colspan="3" style="text-align:center; opacity:0.6; font-style:italic;">
                    No activity recorded yet for today.
                </td>
            </tr>
            % end
            % for hb in nonzero_rows:
            <tr>
                <td>{{ "{:02d}:00".format(hb['hour']) }}</td>
                <td>{{ "{:.0f}".format(hb['loss_wh']) }} Wh</td>
                <td>{{ "{:+.0f}".format(hb['imbalance_wh']) }} Wh</td>
            </tr>
            % end
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
            <tr>
                <td>Overnext-cluster skips total</td>
                <td>{{ stats['battery_overnext_skip_total'] }}</td>
            </tr>
            <tr>
                <td>Expensive-phase skips total</td>
                <td>{{ stats['battery_expensive_phase_skip_total'] }}</td>
            </tr>
            <tr>
                <td>SOC-target skips total</td>
                <td>{{ stats['soc_target_skip_total'] }}</td>
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
                // RTE -1 marker = invalid (discharge > charge), render as "--"
                const rteRaw = parseFloat(get('rte'));
                setText('tile-rte', (isNaN(rteRaw) || rteRaw < 0) ? '--' : rteRaw.toFixed(1));
                setText('tile-loss', formatNum(get('loss'), 0));
                // Imbalance: keep the explicit sign so users see + vs -.
                const imb = parseFloat(get('imbalance')) || 0;
                const imbEl = document.getElementById('tile-imbalance');
                if (imbEl) imbEl.textContent = (imb >= 0 ? '+' : '') + imb.toFixed(0);
                setText('tile-solar-skips', get('solar-skips') || '0');
                setText('tile-battery-skips', get('battery-skips') || '0');
                setText('tile-battery-overnext-skips', get('battery-overnext-skips') || '0');
                setText('tile-battery-expensive-phase-skips', get('battery-expensive-phase-skips') || '0');
                setText('tile-soc-target-skips', get('soc-target-skips') || '0');

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

            // Live updates via WebSocket: when the "Today" tab is the
            // active one, refresh the daily totals from the same WS
            // payload that the status page consumes. The data-* grid
            // attributes are also updated so re-clicking "Today" later
            // shows the fresh values, and other tabs stay snapshot-ed
            // at their server-render time. Skips, RTE, Cycles and Loss
            // are not in the WS payload (they're computed server-side
            // from per-day history) so they remain at the server-rendered
            // value until the page is reloaded.
            // Server may supply a fully-qualified WebSocket URL via
            // the `web_socket_url` config option (e.g.
            // "wss://he60.example.com/ws" for reverse-proxy setups).
            // When empty, fall back to the legacy same-host port-8765
            // direct connection.
            const configuredWsUrl = "{{ web_socket_url }}";
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsHost = window.location.hostname;
            const wsPort = 8765;
            const wsUrl = configuredWsUrl || (wsProtocol + '//' + wsHost + ':' + wsPort);

            let ws;
            let reconnectAttempts = 0;
            const maxReconnectAttempts = 10;
            const reconnectInterval = 5000;

            function isTodayActive() {
                const activeTab = document.querySelector('.stats-tabs a.active');
                if (!activeTab) return false;
                return activeTab.getAttribute('data-range') === 'today';
            }

            function applyLiveUpdate(data) {
                if (!data || typeof data !== 'object') return;

                // Map WS payload keys -> (data-today-* attribute, tile-id)
                const map = [
                    ['consumptionD',       'consumption',        'tile-consumption',        0],
                    ['gridD',              'grid',               'tile-grid',               0],
                    ['gridExportD',        'grid-export',        'tile-grid-export',        0],
                    ['pvD',                'pv',                 'tile-pv',                 0],
                    ['batteryChargeD',     'battery-charge',     'tile-battery-charge',     0],
                    ['batteryDischargeD',  'battery-discharge',  'tile-battery-discharge',  0],
                    ['lossD',              'loss',               'tile-loss',               0],
                ];

                map.forEach(entry => {
                    const wsKey = entry[0], attrKey = entry[1], tileId = entry[2], decimals = entry[3];
                    const v = data[wsKey];
                    if (typeof v !== 'number') return;
                    grid.setAttribute('data-today-' + attrKey, v);
                    if (isTodayActive()) {
                        setText(tileId, v.toFixed(decimals));
                    }
                });

                // Imbalance is signed -- keep the +/- prefix when shown.
                if (typeof data.imbalanceD === 'number') {
                    grid.setAttribute('data-today-imbalance', data.imbalanceD);
                    if (isTodayActive()) {
                        const imbEl = document.getElementById('tile-imbalance');
                        if (imbEl) {
                            imbEl.textContent = (data.imbalanceD >= 0 ? '+' : '') + data.imbalanceD.toFixed(0);
                        }
                    }
                }

                // total_costs_today is in cents on the WS bus, EUR on the
                // tile (matching the existing showRange() conversion).
                if (typeof data.total_costs_today === 'number') {
                    grid.setAttribute('data-today-cost', data.total_costs_today);
                    if (isTodayActive()) {
                        const tileCost = document.getElementById('tile-cost');
                        if (tileCost) {
                            tileCost.textContent = (data.total_costs_today / 100.0).toFixed(4);
                            tileCost.setAttribute('title', data.total_costs_today.toFixed(4) + ' \u00a2');
                        }
                    }
                }
            }

            function connectWS() {
                ws = new WebSocket(wsUrl);
                ws.onopen = function() {
                    reconnectAttempts = 0;
                };
                ws.onmessage = function(event) {
                    try {
                        const data = JSON.parse(event.data);
                        applyLiveUpdate(data);
                    } catch (err) {
                        // Non-JSON payload or partial frame -- ignore.
                    }
                };
                ws.onclose = function() {
                    if (reconnectAttempts < maxReconnectAttempts) {
                        reconnectAttempts++;
                        setTimeout(connectWS, reconnectInterval);
                    }
                };
                ws.onerror = function() { /* close handler will reconnect */ };
            }

            connectWS();
        })();
    </script>
</body>
</html>
