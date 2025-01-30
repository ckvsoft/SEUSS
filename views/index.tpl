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
            <div>{{ !chart_svg }}</div>
            <h1>Tomorrow</h1>
            <div>{{ !next_chart_svg }}</div>
        </div>
        <div class="right">
            <p id="datetime"></p>
            <p>Version: {{ version }}</p>
            <div id="legend">
                {{ !legend_svg }}
            </div>
            <h1>Realtime Data</h1>
            <div id="averageWh">Average: -</div>
            <div id="averageWhD">Average Now: -</div>
            <div id="power">Power: -</div>
            <div id="consumptionD">Consumption today: -</div>
        </div>
    </div>

    % include('footer')

    <script>
        setInterval(function () {
            var currentDate = new Date();
            document.getElementById('datetime').innerHTML = 'Current date and time: ' + currentDate;
        }, 1000);
    </script>
    <script>
        let ws; // Declare WebSocket globally
        let reconnectInterval = 5000; // Time (in ms) to wait before trying to reconnect
        let reconnectAttempts = 0; // Count of reconnection attempts
        const maxReconnectAttempts = 10; // Optional: Maximum reconnection attempts (or use infinite retries)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.hostname; // Get only the hostname, not the port
        const port = 8765; // Desired port
        const wsUrl = `${protocol}//${host}:${port}`;

        function connectWebSocket() {
            ws = new WebSocket(wsUrl);

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

        // Initialize WebSocket connection
        connectWebSocket();
    </script>

</body>

</html>
