<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Config Editor</title>
    <link rel="stylesheet" type="text/css" href="/static/styles.css">
    <link rel="shortcut icon" href="/static/favicon.ico" />
</head>

<body>
    % include('header', title='Config Editor')
            <form id="meinFormular" autocomplete="off">
    <div class="container">
        <div class="left">
                % for key, value in config.items():
                    <%
                    if tooltips and key in tooltips:
                        title=tooltips.get(key)
                        additional=' ℹ️'
                    else:
                        title = ''
                        additional= ''
                    end
                    formatted_text = " ".join(word.capitalize() for word in key.split("_")) + additional
                    %>
                    % if key not in ["ess_unit", "markets", "prices", "pv_panels", "smart_switches"]:
                        <label class="tooltip" for="{{ key }}" title="{{ title }}">{{ formatted_text }}</label>
                        % if isinstance(value, bool):
                            <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}><br/>
                            <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                        % elif key == "password":
                            <label class="tooltip" for="{{ key }}" title="{{ title }}">{{ formatted_text }}</label>
                            <input type="password" id="{{ key }}" name="{{ key }} autofill="new-password">
                            <span id="password-toggle" onclick="togglePasswordVisibility()">👁️</span><br>
                        % elif key == "log_level":
                            <select id="{{ key }}" name="{{ key }}">
                                <option value="DEBUG" {{ 'selected' if value == 'DEBUG' else '' }}>DEBUG</option>
                                <option value="ERROR" {{ 'selected' if value == 'ERROR' else '' }}>ERROR</option>
                                <option value="WARNING" {{ 'selected' if value == 'WARNING' else '' }}>WARNING</option>
                                <option value="INFO" {{ 'selected' if value == 'INFO' else '' }}>INFO</option>
                            </select><br>
                        % else:
                            <input type="text" id="{{ key }}" name="{{ key }} " value="{{ value }}"><br>
                        % end
                    % end
                % end

                % if isinstance(config["prices"], list):
                    <fieldset>
                        <legend>Prices</legend>
                        % for price_data in config["prices"]:
                            % for field_key, field_value in price_data.items():
                                <%
                                if tooltips and field_key in tooltips:
                                    title=tooltips.get(field_key)
                                    additional=' ℹ️'
                                else:
                                    title = ''
                                    additional= ''
                                end
                                formatted_text = " ".join(word.capitalize() for word in field_key.split("_")) + additional
                                %>
                                <label class="tooltip" for="prices:{{ field_key }}" title="{{ title }}">{{ formatted_text }}</label><br/>
                                % if isinstance(field_value, bool):
                                    <input type="checkbox" id="prices:{{ field_key }}" name="prices:{{ field_key }}" {{ 'checked' if field_value == True else '' }}><br/>
                                    <input type="hidden" id="prices:{{ field_key }}_hidden" name="prices:{{ field_key }}" value="off">
                                % else:
                                    <input type="text" id="prices:{{ field_key }}" name="prices:{{ field_key }}" value="{{ field_value }}"><br>
                                % end
                            % end
                        % end
                    </fieldset>
                % else:
                    <p>Prices is not a list!</p>
                % end
        </div>

        <div class="right">
                <label class="tooltip" for="selectedSection">Select Section:</label>
                <select id="selectedSection" name="selectedSection">
                    <option value="ess_unit">Ess Unit</option>
                    <option value="markets">Markets</option>
                    <option value="pv_panels">Pv Panels</option>
                    <option value="smart_switches">Smart Switches</option>
                    <!-- Weitere Optionen nach Bedarf hinzufügen -->
                </select>

                <button id="sendSectionButton">Abschnitt senden</button>
                <div id="sectionFields_ess_unit" style="display: none;">
                    <!-- Felder für die Sektion "ess_unit" -->
                </div>

                <div id="sectionFields_markets" style="display: none;">
                    <!-- Felder für die Sektion "markets" -->
                </div>

                <div id="sectionFields_pv_panels" style="display: none;">
                    <!-- Felder für die Sektion "pv_panels" -->
                </div>

                <div id="sectionFields_smart_switches" style="display: none;">
                    <!-- Felder für die Sektion "smart_switches" -->
                </div>

                <input type="submit" value="Save Configuration">
        </div>
    </div>
            </form>

    % include('footer')

    <script src="static/js/editor.js"></script>
    <script>
        var config = {{ !json_config }};
        var tooltips = {{ !tooltips }};
        var names = {{ !names }};
    </script>

</body>

</html>
