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
                <h1>Realtime Data</h1>
                <div class="realtime-container">
                    <div class="realtime-left">
                        <div id="averageWh">Average: -</div>
                        <div id="power">Power: -</div>
                    </div>
                    <div class="realtime-right">
                        <div id="averageWhD">Average Now: -</div>
                        <div id="consumptionD">Consumption today: -</div>
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

        setInterval(function () {
            var currentDate = new Date();
            document.getElementById('datetime').innerHTML = 'Current date and time: ' + currentDate;

            // Prüfen, ob es zur vollen Stunde ist (Minute 0)
            if (currentDate.getMinutes() === 0 && currentDate.getHours() !== lastUpdatedHour) {
                updateCharts();  // Chart-Update nur zur vollen Stunde
                lastUpdatedHour = currentDate.getHours();
            }
        }, 1000);

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
                        const averageWhElement = document.getElementById("averageWh");
                        if (averageWhElement) {
                            averageWhElement.textContent = `Average: ${data.averageWh.toFixed(2)} Wh`;
                        }
                    }
                    if (data.averageWhD !== undefined) {
                        const averageWhDElement = document.getElementById("averageWhD");
                        if (averageWhDElement) {
                            averageWhDElement.textContent = `Average now: ${data.averageWhD.toFixed(2)} Wh`;
                        }
                    }
                    if (data.power !== undefined) {
                        const powerElement = document.getElementById("power");
                        if (powerElement) {
                            powerElement.textContent = `Power: ${data.power.toFixed(2)} W`;
                        }
                    }
                    if (data.consumptionD !== undefined) {
                        const consumptionDElement = document.getElementById("consumptionD");
                        if (consumptionDElement) {
                            consumptionDElement.textContent = `Consumption today: ${data.consumptionD.toFixed(2)} Wh`;
                        }
                    }

                    const responseElement = document.getElementById("response");
                    if (responseElement) {
                        responseElement.textContent = `Server response: ${event.data}`;
                    }
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
