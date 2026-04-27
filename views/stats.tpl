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
         * children take their content width and centre. We explicitly
         * force the stats containers to full width so the grid spreads
         * out instead of clustering in the middle.
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
        }
        .stats-tabs a {
            color: #4285f4;
            text-decoration: none;
            font-weight: bold;
            cursor: pointer;
        }
        .stats-tabs a.active {
            color: #2a8a2a;
        }
        .stats-tabs a.disabled {
            color: #aaa;
            cursor: not-allowed;
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
            text-align: left;
            background: #f7f7f7;
            color: #333;
        }
        .stats-compare td:first-child {
            text-align: left;
            color: #555;
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
        <a class="disabled" title="Available in Part 2">[ 7 Days ]</a>
        <a class="disabled" title="Available in Part 2">[ Month ]</a>
        <a class="disabled" title="Available in Part 2">[ Year ]</a>
    </div>

    <%
        # Render once for "today" -- the tab switcher rewrites the
        # tile + cost values via JS below using the data attributes
        # on this same DOM. No round-trip to the server needed.
        active = stats["today"]
    %>

    <div class="stats-tile-grid"
         data-today-iso="{{ stats['today']['iso'] }}"
         data-yesterday-iso="{{ stats['yesterday']['iso'] }}"
         data-today-consumption="{{ stats['today']['consumption_wh'] }}"
         data-today-grid="{{ stats['today']['grid_wh'] }}"
         data-today-pv="{{ stats['today']['pv_wh'] }}"
         data-today-battery="{{ stats['today']['battery_throughput_wh'] }}"
         data-today-cost="{{ stats['today']['cost_eur'] }}"
         data-yesterday-consumption="{{ stats['yesterday']['consumption_wh'] }}"
         data-yesterday-grid="{{ stats['yesterday']['grid_wh'] }}"
         data-yesterday-pv="{{ stats['yesterday']['pv_wh'] }}"
         data-yesterday-battery="{{ stats['yesterday']['battery_throughput_wh'] }}"
         data-yesterday-cost="{{ stats['yesterday']['cost_eur'] }}">

        <div class="stats-tile">
            <div class="label">Date</div>
            <div class="value" id="tile-date" style="font-size:1.2em;">{{ active['iso'] }}</div>
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
            <div class="label">PV Production</div>
            <div class="value">
                <span id="tile-pv">{{ "{:.0f}".format(active['pv_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile">
            <div class="label">Battery Throughput</div>
            <div class="value">
                <span id="tile-battery">{{ "{:.0f}".format(active['battery_throughput_wh']) }}</span>
                <span class="unit">Wh</span>
            </div>
        </div>

        <div class="stats-tile cost">
            <div class="label">Grid Cost</div>
            <div class="value">
                <span id="tile-cost">{{ "{:.4f}".format(active['cost_eur']) }}</span>
                <span class="unit">€</span>
            </div>
        </div>
    </div>

    <h3 style="padding: 0 1em;">Today vs. Yesterday</h3>
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
                <td>PV production</td>
                <td>{{ "{:.0f}".format(stats['today']['pv_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['pv_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>Battery throughput</td>
                <td>{{ "{:.0f}".format(stats['today']['battery_throughput_wh']) }} Wh</td>
                <td>{{ "{:.0f}".format(stats['yesterday']['battery_throughput_wh']) }} Wh</td>
            </tr>
            <tr>
                <td>Grid cost</td>
                <td>{{ "{:.4f}".format(stats['today']['cost_eur']) }} €</td>
                <td>{{ "{:.4f}".format(stats['yesterday']['cost_eur']) }} €</td>
            </tr>
        </tbody>
    </table>

    <p class="stats-note">
        % if stats['history_days_available'] == 0:
            No completed days in history yet -- yesterday's row will populate
            once SEUSS has been running across a midnight rollover.
        % else:
            {{ stats['history_days_available'] }} day(s) of completed history
            available. Longer ranges (7 days, month, year) will be available
            in Part 2 once enough data has accumulated and the views are built.
        % end
    </p>

    </div><!-- /stats-container -->

    % include('footer')

    <script>
        // Tab switcher. We have today + yesterday data on the grid as
        // data-* attributes; switching just rewrites the tile values
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

            function showRange(range) {
                const iso = grid.getAttribute('data-' + range + '-iso');
                document.getElementById('tile-date').textContent = iso;
                document.getElementById('tile-consumption').textContent =
                    formatNum(grid.getAttribute('data-' + range + '-consumption'), 0);
                document.getElementById('tile-grid').textContent =
                    formatNum(grid.getAttribute('data-' + range + '-grid'), 0);
                document.getElementById('tile-pv').textContent =
                    formatNum(grid.getAttribute('data-' + range + '-pv'), 0);
                document.getElementById('tile-battery').textContent =
                    formatNum(grid.getAttribute('data-' + range + '-battery'), 0);
                document.getElementById('tile-cost').textContent =
                    formatNum(grid.getAttribute('data-' + range + '-cost'), 4);

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
