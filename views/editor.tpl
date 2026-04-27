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
                <%
                # Top-level keys that get their own grouped fieldset
                # below; the generic loop should skip them.
                solar_keys = [
                    "use_solar_forecast_to_abort",
                    "solar_adj_ewma_alpha",
                    "solar_adj_min_theoretical_wh",
                    "solar_adj_min_sun_hours",
                    "solar_adj_max_daily_change",
                ]
                battery_keys = [
                    "skip_charge_when_battery_sufficient",
                    "delay_grid_charging_below_active_soc_limit",
                ]
                grouped_keys = set(solar_keys + battery_keys)
                section_keys = ["ess_unit", "markets", "prices", "pv_panels", "smart_switches"]
                %>
                % for key, value in config.items():
                    % if key not in section_keys and key not in grouped_keys:
                        <%
                        if tooltips and key in tooltips:
                            title = tooltips.get(key)
                            additional = ' \u2139\ufe0f'
                        else:
                            title = ''
                            additional = ''
                        end
                        formatted_text = " ".join(word.capitalize() for word in key.split("_")) + additional
                        %>
                        <label class="tooltip" for="{{ key }}" title="{{ title }}">{{ formatted_text }}</label>
                        % if isinstance(value, bool):
                            <br/>
                            <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}><br/>
                            <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                        % elif key == "log_level":
                            <select id="{{ key }}" name="{{ key }}">
                                <option value="DEBUG" {{ 'selected' if value == 'DEBUG' else '' }}>DEBUG</option>
                                <option value="ERROR" {{ 'selected' if value == 'ERROR' else '' }}>ERROR</option>
                                <option value="WARNING" {{ 'selected' if value == 'WARNING' else '' }}>WARNING</option>
                                <option value="INFO" {{ 'selected' if value == 'INFO' else '' }}>INFO</option>
                            </select><br>
                        % elif key == "tariff_resolution":
                            <select id="{{ key }}" name="{{ key }}">
                                <option value="hourly" {{ 'selected' if value == 'hourly' else '' }}>Hourly</option>
                                <option value="quarterly" {{ 'selected' if value == 'quarterly' else '' }}>Quarterly (15 min)</option>
                            </select><br>
                        % else:
                            <input type="text" id="{{ key }}" name="{{ key }} " value="{{ value }}"><br>
                        % end
                    % end
                % end

                <fieldset>
                    <legend>Solar Forecast</legend>
                    % for key in solar_keys:
                        % if key in config:
                            <%
                            value = config[key]
                            if tooltips and key in tooltips:
                                title = tooltips.get(key)
                                additional = ' \u2139\ufe0f'
                            else:
                                title = ''
                                additional = ''
                            end
                            formatted_text = " ".join(word.capitalize() for word in key.split("_")) + additional
                            %>
                            <label class="tooltip" for="{{ key }}" title="{{ title }}">{{ formatted_text }}</label>
                            % if isinstance(value, bool):
                                <br/>
                                <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}><br/>
                                <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                            % else:
                                <input type="text" id="{{ key }}" name="{{ key }}" value="{{ value }}"><br>
                            % end
                        % end
                    % end
                </fieldset>

                <fieldset>
                    <legend>Battery / Charging</legend>
                    % for key in battery_keys:
                        % if key in config:
                            <%
                            value = config[key]
                            if tooltips and key in tooltips:
                                title = tooltips.get(key)
                                additional = ' \u2139\ufe0f'
                            else:
                                title = ''
                                additional = ''
                            end
                            formatted_text = " ".join(word.capitalize() for word in key.split("_")) + additional
                            %>
                            <label class="tooltip" for="{{ key }}" title="{{ title }}">{{ formatted_text }}</label>
                            % if isinstance(value, bool):
                                <br/>
                                <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}><br/>
                                <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                            % else:
                                <input type="text" id="{{ key }}" name="{{ key }}" value="{{ value }}"><br>
                            % end
                        % end
                    % end
                </fieldset>

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
