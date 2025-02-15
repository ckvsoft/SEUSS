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
            <div id="legend_svg">
                {{ !legend_svg }}
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
                    </div>
                    <div class="realtime-right">
                        <div id="averageWhD">Average Now: -</div>
                        <div id="consumptionD">Consumption today: -</div>
                        <div id="costs">Costs: -</div>
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
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.hostname; // Get only the hostname, not the port
        const port = 8765; // Desired port
        const wsUrl = `${protocol}//${host}:${port}`;
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
            ws = new WebSocket(wsUrl);
            console.log('Connected to ' + wsUrl);

            ws.onopen = function () {
                console.log('Connected to the WebSocket server');
                reconnectAttempts = 0; // Reset reconnection attempts after successful connection
            };

            ws.onmessage = function (event) {
                console.log('Message from server:', event.data);

                try {
                    const data = JSON.parse(event.data);

                    if (data.averageWh !== undefined) {
                        document.getElementById("averageWh").textContent = `Average: ${data.averageWh.toFixed(2)} Wh`;
                    }
                    if (data.averageWhD !== undefined) {
                        document.getElementById("averageWhD").textContent = `Average now: ${data.averageWhD.toFixed(2)} Wh`;
                    }
                    if (data.power !== undefined) {
                        document.getElementById("power").textContent = `Power: ${data.power.toFixed(2)} W`;
                    }
                    if (data.grid_power !== undefined) {
                        document.getElementById("grid_power").textContent = `Gridpower: ${data.grid_power.toFixed(2)} W`;
                    }
                    if (data.battery_power !== undefined) {
                        document.getElementById("battery_power").textContent = `Batterypower: ${data.battery_power.toFixed(2)} W`;
                    }
                    if (data.costs !== undefined) {
                        document.getElementById("costs").textContent = `Costs: ${data.costs.toFixed(2)} \u00A2`;
                    }
                    if (data.total_costs_today !== undefined) {
                        document.getElementById("total_costs_today").textContent = `Total Costs Today: ${data.total_costs_today.toFixed(2)} \u00A2`;
                    }
                    if (data.consumptionD !== undefined) {
                        document.getElementById("consumptionD").textContent = `Consumption today: ${data.consumptionD.toFixed(2)} Wh`;
                    }

                    // 🔄 Induktionskreis aktivieren
                    const loadingCircle = document.getElementById("loadingCircle");
                    loadingCircle.classList.add("active");

                    // Nach 1.5 Sekunden die Animation wieder entfernen
                    setTimeout(() => {
                        loadingCircle.classList.remove("active");
                    }, 1500);

                } catch (error) {
                    console.error('Error processing server message:', error);
                }
            };

            ws.onerror = function (error) {
                console.error('WebSocket error:', error);
            };

            ws.onclose = function () {
                console.log('Connection to server closed');
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
