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
        </div>
    </div>

    % include('footer')

    <script>
        setInterval(function () {
            var currentDate = new Date();
            document.getElementById('datetime').innerHTML = 'Current date and time: ' + currentDate;
        }, 1000);
    </script>
</body>

</html>
