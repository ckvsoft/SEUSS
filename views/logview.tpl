<!-- index.tpl -->
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Log Viewer</title>
    <link rel="stylesheet" type="text/css" href="/static/styles.css">
    <link rel="shortcut icon" href="/static/favicon.ico" />

</head>

<body>

    % include('header', title='Log Viewer')

    <div id="log-container">
        <p>{{!log_content}}</p>
    </div>

    <div id="output">scrollTop: 0</div>
    <div>
        <button onclick="manualRefresh()">Manuelles Refresh</button>
        <button onclick="downloadLog()">Download Log</button>

        <form id="download-form" action="/download_log" method="post">
        </form>
    </div>

    <script>

        const scroller = document.querySelector("#log-container");
        const output = document.querySelector("#output");
        var currentScrollTop = 0

        scroller.addEventListener("scroll", (event) => {
            output.textContent = `scrollTop: ${scroller.scrollTop}`;
            currentScrollTop = scroller.scrollTop;
        });


        function manualRefresh() {
            updateLogContent();
        }

        function downloadLog() {
            // Trigger the form submission for log download
            document.forms["download-form"].submit();
        }

        function updateLogContent() {
            var logContainer = document.getElementById('log-container');

            var xhr = new XMLHttpRequest();
            xhr.onreadystatechange = function () {
                if (xhr.readyState === 4 && xhr.status === 200) {
                    logContainer.innerHTML = "<p>" + xhr.responseText + "</p>";
                }
            };
            xhr.open('GET', '/update_log', true);
            xhr.send();
        }

    setInterval(updateLogContent, 2000);
    </script>

    % include('footer')


</body>
</html>
