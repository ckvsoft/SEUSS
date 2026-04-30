<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Status Info</title>
    <link rel="stylesheet" type="text/css" href="static/styles.css">
    <link rel="shortcut icon" href="/static/favicon.ico" />
</head>
<body>
    % include('header', title='Status')

    <div class="container">
        <div class="left">
            <!-- SVG-Code oder andere Inhalte -->
            <h1>Today</h1>
            <div id="chart_svg">{{ !chart_svg }}</div>
            <h1>Tomorrow</h1>
            <div id="next_chart_svg">{{ !next_chart_svg }}</div>
        </div>
        <div class="right">
            <p id="datetime">Current date and time: -</p>
            <p>Version: {{ version }}</p>
            <div class="legend-soc-container">
                <div id="legend_svg">
                    {{ !legend_svg }}
                </div>

                <div id="soc-container">
                    <div class="soc-label">SOC</div>
                    <div id="soc-value">-- %</div>
                </div>
            </div>
            <div>
                <div>
                    <div class="realtime-header">
                        <h1>Realtime Data</h1>
                        <div class="loading-circle" id="loadingCircle"></div>
                    </div>
                </div>
                <div class="realtime-container">
                    <div class="realtime-left">
                        <div id="averageWh">Average: -</div>
                        <div id="power">Power: -</div>
                        <div id="grid_power">Gridpower: -</div>
                        <div id="battery_power">Batterypower: -</div>
                        <div id="pv">Pv: -</div>
                        <div id="loss">Loss: -</div>
                        <div id="efficiency">Efficiency: -</div>
                    </div>
                    <div class="realtime-right">
                        <div id="averageWhD">Average Now: -</div>
                        <div id="consumptionD">Consumption today: -</div>
                        <div id="gridD">Grid today: -</div>
                        <div id="gridExportD">Grid export today: -</div>
                        <div id="gridH">Grid this hour: -</div>
                        <div id="pvD">PV today: -</div>
                        <div id="batteryChargeD">Battery charged today: -</div>
                        <div id="batteryDischargeD">Battery discharged today: -</div>
                        <div id="costs">Current Hour Costs: -</div>
                        <div id="total_costs_today">Total Costs Today: -</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    % include('footer')

    <script>
        let ws; // Declare WebSocket globally
        let reconnectInterval = 5000; // Time (in ms) to wait before trying to reconnect
        let reconnectAttempts = 0; // Count of reconnection attempts
        const maxReconnectAttempts = 10; // Optional: Maximum reconnection attempts (or use infinite retries)
        // Build a list of WebSocket URL candidates and try them in order.
        // Slot 0: same-host same-port path /ws -- the right answer when
        //   SEUSS sits behind a reverse proxy that terminates TLS on a
        //   non-default port (e.g. https://example.com:50000/) and routes
        //   /ws by path. The browser only ever sees the proxy's URL, so
        //   a path-based route is the cleanest way to keep WS working.
        // Slot 1: legacy direct-port (same hostname, port 8765) -- the
        //   right answer for plain LAN installs where the page is served
        //   directly from SEUSS on port 5000 and 8765 is reachable too.
        // The first candidate that connects within ~2.5s wins; otherwise
        // we move on. After a successful connection that later drops,
        // reconnect uses the same winning URL until 10 failures, then
        // restarts the scan.
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.hostname;
        const pagePort = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
        const wsCandidates = [
            `${protocol}//${host}:${pagePort}/ws`,
            `${protocol}//${host}:8765`,
        ];
        let wsCandidateIndex = 0;
        let wsUrl = wsCandidates[0];
        // Once we successfully open a WS to a candidate, lock onto it.
        // Reconnects after a working session retry the same URL --
        // candidate-cycling only matters during initial discovery.
        let wsLockedIn = false;
        let lastUpdatedHour = -1;  // Flag für die letzte aktualisierte Stunde
        let lastUpdatedMinute = -1;  // Flag für die letzte aktualisierte Minute

        setInterval(function () {
            var currentDate = new Date();
            document.getElementById('datetime').innerHTML = 'Current date and time: ' + currentDate;

            var currentHour = currentDate.getHours();
            var currentMinute = currentDate.getMinutes();

            // Volle Stunde prüfen (aber nur einmal pro Stunde)
            if (currentMinute === 0 && currentHour !== lastUpdatedHour) {
                updateCharts();
                lastUpdatedHour = currentHour;
                lastUpdatedMinute = currentMinute;
            }

            // Zwischen 13:00 und 14:00 Uhr zusätzlich alle 15 Minuten (13:00, 13:15, 13:30, 13:45)
            if (currentHour === 13 && currentMinute % 15 === 0 && lastUpdatedMinute !== currentMinute) {
                updateCharts();
                lastUpdatedMinute = currentMinute;  // Speichert, dass diese Minute schon geupdatet wurde
            }

        }, 1000); // Jede Sekunde laufen lassen

        function connectWebSocket() {
            // If we've burned through all candidates without ever
            // reaching ws.onopen, cycle back and start over rather
            // than retrying the same dead URL forever.
            ws = new WebSocket(wsUrl);
            console.log('Trying WebSocket: ' + wsUrl);

            // Failsafe: a dead URL on the first slot may not raise
            // onerror/onclose for a long time on some browsers (ERR_
            // CONNECTION_REFUSED takes ~30s). Time out after 3s and
            // hop to the next candidate ourselves.
            let probeTimer = setTimeout(() => {
                if (ws && ws.readyState === WebSocket.CONNECTING) {
                    console.log('WebSocket probe timeout for ' + wsUrl);
                    try { ws.close(); } catch (e) { /* noop */ }
                }
            }, 3000);

            ws.onopen = function () {
                clearTimeout(probeTimer);
                console.log('Connected to the WebSocket server at ' + wsUrl);
                reconnectAttempts = 0;
                wsLockedIn = true;  // remember the working URL across reconnects
            };

            ws.onmessage = function (event) {
                console.log('Message from server:', event.data);

                try {
                    const data = JSON.parse(event.data);

                    function updateValue(id, label, value, unit = "") {
                        const element = document.getElementById(id);
                        if (element && typeof value === "number") {
                            element.textContent = `${label}: ${value.toFixed(2)} ${unit}`;
                        }
                    }

                    updateValue("averageWh", "Average", data.averageWh, "Wh");
                    updateValue("averageWhD", "Average Now", data.averageWhD, "Wh");
                    updateValue("power", "Power", data.power, "W");
                    updateValue("grid_power", "Gridpower", data.grid_power, "W");
                    updateValue("battery_power", "Batterypower", data.battery_power, "W");
                    updateValue("costs", "Current Hour Costs", data.costs, "¢");
                    updateValue("total_costs_today", "Total Costs Today", data.total_costs_today, "¢");
                    updateValue("loss", "Loss", data.loss, "W");
                    updateValue("efficiency", "Efficiency", data.efficiency, "%");
                    updateValue("pv", "PV", data.pv, "W");
                    updateValue("consumptionD", "Consumption today", data.consumptionD, "Wh");
                    updateValue("gridD", "Grid today", data.gridD, "Wh");
                    updateValue("gridExportD", "Grid export today", data.gridExportD, "Wh");
                    updateValue("gridH", "Grid this hour", data.gridH, "Wh");
                    updateValue("pvD", "PV today", data.pvD, "Wh");
                    updateValue("batteryChargeD", "Battery charged today", data.batteryChargeD, "Wh");
                    updateValue("batteryDischargeD", "Battery discharged today", data.batteryDischargeD, "Wh");
                    if (data.soc !== undefined && data.soc !== null) {
                        document.getElementById("soc-value").textContent = data.soc.toFixed(0) + " %";
                    }

                    // 🔄 Ladeanimation aktivieren
                    const loadingCircle = document.getElementById("loadingCircle");
                    if (loadingCircle) {
                        loadingCircle.classList.add("active");

                        // Nach 1.5 Sekunden die Animation wieder entfernen
                        setTimeout(() => {
                            loadingCircle.classList.remove("active");
                        }, 1500);
                    }
                } catch (error) {
                    console.error("Error processing server message:", error);
                }
            };

            ws.onerror = function (error) {
                console.error('WebSocket error on ' + wsUrl + ':', error);
            };

            ws.onclose = function () {
                clearTimeout(probeTimer);
                console.log('Connection to ' + wsUrl + ' closed');
                // If we've never had a successful connection on this
                // URL, advance to the next candidate. Once a candidate
                // worked (wsLockedIn=true), stick with it -- a drop
                // after a successful session is a transient network
                // issue, not a config problem.
                if (!wsLockedIn) {
                    wsCandidateIndex = (wsCandidateIndex + 1) % wsCandidates.length;
                    wsUrl = wsCandidates[wsCandidateIndex];
                }
                attemptReconnect();
            };
        }

        function attemptReconnect() {
            if (reconnectAttempts < maxReconnectAttempts || maxReconnectAttempts === 0) {
                reconnectAttempts++;
                console.log(`Attempting to reconnect... (Attempt ${reconnectAttempts})`);
                setTimeout(() => {
                    connectWebSocket();
                }, reconnectInterval);
            } else {
                console.warn('Max reconnection attempts reached. Stopping reconnection.');
            }
        }

        function updateCharts() {
            console.log('fetch /get_charts');
            fetch('/get_charts')  // Unified API endpoint
                .then(response => response.json())  // Parse JSON response
                .then(data => {
                    if (data.today_chart !== undefined) {
                        const todayChart = document.getElementById("chart_svg");
                        if (todayChart) todayChart.innerHTML = data.today_chart;
                    }

                    if (data.tomorrow_chart !== undefined) {
                        const tomorrowChart = document.getElementById("next_chart_svg");
                        if (tomorrowChart) tomorrowChart.innerHTML = data.tomorrow_chart;
                    }

                    if (data.legend_svg !== undefined) {
                        const legend_svg = document.getElementById("legend_svg");
                        if (legend_svg) legend_svg.innerHTML = data.legend_svg;
                    }
                })
                .catch(error => console.error("Error updating charts:", error));

            console.log("Charts updated at full hour");
        }

        // Initialize WebSocket connection
        connectWebSocket();

    </script>

</body>

</html>
