<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Status Info</title>
    <link rel="stylesheet" type="text/css" href="static/styles.css">
</head>

<body>
    % include('header', title='Status')

    <div class="container">
        <div class="left">
            <!-- SVG-Code oder andere Inhalte -->
            <div>{{ !chart_svg }}</div>
            <h1>Experimental</h1>
            <div id="chart_avg_svg">{{ !chart_avg_svg }}</div>
            <!-- Slider für 0-99 Prozent -->
            <div>
                <label for="slider1">Slider 1 (0-99%): </label>
                <input type="range" id="slider1" min="0" max="99" value="99" oninput="handleSliderChange()">
                <span id="slider1Value">99</span>
            </div>
            <!-- Slider für 100-200 Prozent -->
            <div>
                <label for="slider2">Slider 2 (100-200%): </label>
                <input type="range" id="slider2" min="100" max="200" value="100" oninput="handleSliderChange()">
                <span id="slider2Value">100</span>
            </div>
            <!-- Slider für SOC -->
            <div>
                <label for="sliderSOC">SOC Slider: </label>
                <input disabled=true type="range" id="sliderSOC" min="0" max="100" value="50" oninput="handleSliderChange()">
                <span id="sliderSOCValue">50</span>
            </div>
            <!-- Slider für Sonnenenergie -->
            <div>
                <label for="sliderSolar">Solar Slider: </label>
                <input disabled=true type="range" id="sliderSolar" min="0" max="1000" value="500" oninput="handleSliderChange()">
                <span id="sliderSolarValue">500</span>
            </div>
        </div>
        <div class="right">
            <p id="datetime"></p>
            <p>Version: {{ version }}</p>
            <div id="legend">
                {{ !legend_svg }}
            </div>
        </div>
    </div>

    % include('footer')

    <script>
        function updateChart(percentage1, percentage2, soc, solar) {
            var xhr = new XMLHttpRequest();
            xhr.onreadystatechange = function () {
                if (xhr.readyState === XMLHttpRequest.DONE) {
                    if (xhr.status === 200) {
                        document.getElementById('chart_avg_svg').innerHTML = xhr.responseText;
                    } else {
                        console.error('Error fetching chart data:', xhr.status, xhr.statusText);
                    }
                }
            };

            // Hier sollte der Server-Endpunkt für die Datenaktualisierung sein.
            // Bitte ersetzen Sie 'update_chart_endpoint' durch den tatsächlichen Endpunkt auf Ihrem Server.
            var endpoint = '/update_chart_endpoint?percentage1=' + percentage1 + '&percentage2=' + percentage2 + '&soc=' + soc + '&solar=' + solar;
            xhr.open('GET', endpoint, true);
            xhr.send();
        }

        function handleSliderChange() {
            var slider1Value = document.getElementById('slider1').value;
            var slider2Value = document.getElementById('slider2').value;
            var sliderSOCValue = document.getElementById('sliderSOC').value;
            var sliderSolarValue = document.getElementById('sliderSolar').value;

            // Aktualisieren Sie das Diagramm basierend auf den Slider-Werten
            updateChart(slider1Value, slider2Value, sliderSOCValue, sliderSolarValue);

            // Aktualisieren Sie die Anzeige der Slider-Werte
            document.getElementById('slider1Value').innerHTML = slider1Value;
            document.getElementById('slider2Value').innerHTML = slider2Value;
            document.getElementById('sliderSOCValue').innerHTML = sliderSOCValue;
            document.getElementById('sliderSolarValue').innerHTML = sliderSolarValue;
        }

        setInterval(function () {
            var currentDate = new Date();
            document.getElementById('datetime').innerHTML = 'Current date and time: ' + currentDate;
        }, 1000);
    </script>
</body>

</html>
