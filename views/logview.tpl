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
        % if show_debug:
        <input type="checkbox" id="checkbox" checked>
        <label for="checkbox" style="display: inline-block;">show Debug</label>
        % end

        <button onclick="manualRefresh()">Manuelles Refresh</button>
        <button onclick="downloadLog()">Download Log</button>

        <form id="download-form" action="/download_log" method="post">
        </form>
    </div>

    <script>
        const scroller = document.querySelector("#log-container");
        const output = document.querySelector("#output");
        var currentScrollTop = 0;

        scroller.addEventListener("scroll", (event) => {
            output.textContent = `scrollTop: ${scroller.scrollTop}`;
            currentScrollTop = scroller.scrollTop;
        });

        function manualRefresh() {
            const checkboxValue = document.getElementById('checkbox').checked;
            updateLogContent(checkboxValue);
        }

        function downloadLog() {
            // Trigger the form submission for log download
            document.forms["download-form"].submit();
        }

        function updateLogContent(param) {
            var logContainer = document.getElementById('log-container');

            // Konvertiere den Checkbox-Status in einen String
            const paramString = param ? 'true' : 'false';

            // Füge den Parameter zur URL hinzu
            const url = `/update_log?show_debug=${paramString}`;

            fetch(url)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.text();
                })
                .then(data => {
                    // Speichern des aktuellen Scrollwerts
                    const previousScrollTop = scroller.scrollTop;

                    // Aktualisieren des Inhalts
                    logContainer.innerHTML = "<p>" + data + "</p>";

                    // Wiederherstellen des vorherigen Scrollwerts
                    scroller.scrollTop = previousScrollTop;
                })
                .catch(error => {
                    console.error('Fetch error:', error);
                });
        }

        setInterval(() => {
            const checkboxValue = document.getElementById('checkbox').checked;
            manualRefresh(checkboxValue);
        }, 2000);

    </script>

    % include('footer')

</body>
</html>
