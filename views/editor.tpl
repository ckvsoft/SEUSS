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
            <form id="configForm" class="editor-form" autocomplete="off">
    <div class="editor-wrap">
        <div class="editor-toolbar">
            <label for="selectedSection">Select Section:</label>
            <select id="selectedSection" name="selectedSection">
                <option value="ess_unit">Ess Unit</option>
                <option value="markets">Markets</option>
                <option value="pv_panels">Pv Panels</option>
                <option value="smart_switches">Smart Switches</option>
                <option value="solar_forecast_providers">Solar Forecast Providers</option>
            </select>
            <button id="sendSectionButton" type="button">Send Section</button>
            <input type="submit" value="Save Configuration">
        </div>

        <div class="editor-grid">
        <fieldset>
            <legend>General</legend>
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
                    "skip_charge_when_battery_covers_expensive_phase",
                    "skip_charge_when_cheaper_cluster_coming",
                    "cheaper_cluster_min_reserve_hours",
                    "skip_charge_for_upcoming_negative_prices",
                    "smart_discharge_priority_to_expensive_hours",
                    "delay_grid_charging_below_active_soc_limit",
                    "discharge_fallthrough_on_charge_veto",
                ]
                economics_keys = [
                    "economic_price_ceiling",
                    "round_trip_efficiency",
                ]
                # Grid tariff (Austria, from ~2027): the demand-charge
                # limiter + the SNAP/WiNAP grid-fee windows. Short
                # display names keep the editor compact -- the full
                # descriptions live in the README and the tooltips (i).
                grid_keys = [
                    "grid_tariff_enabled",
                    "grid_demand_peak_limit_w",
                    "grid_demand_peak_target_w",
                    "grid_demand_peak_shaving",
                    "grid_demand_peak_shaving_min_soc_percent",
                    "grid_work_price_ct",
                    "grid_zone_discount_percent",
                    "grid_zone_snap_enabled",
                    "grid_zone_winap_enabled",
                ]
                grid_labels = {
                    "grid_tariff_enabled": "Enabled",
                    "grid_demand_peak_limit_w": "Peak Limit (W)",
                    "grid_demand_peak_target_w": "Peak Target (W)",
                    "grid_demand_peak_shaving": "Peak Shaving",
                    "grid_demand_peak_shaving_min_soc_percent": "Shaving Min SOC (%)",
                    "grid_work_price_ct": "Grid Work Price (ct/kWh)",
                    "grid_zone_discount_percent": "Zone Discount (%)",
                    "grid_zone_snap_enabled": "SNAP Window",
                    "grid_zone_winap_enabled": "WiNAP Window",
                }
                # Cap-strategy-only switches: dormant under the economic
                # strategy (the marginal rule decides; the flags are
                # simply not registered there). Hidden while economic
                # is active; they re-appear when flipping back to cap.
                cap_only_keys = {
                    "skip_charge_when_battery_covers_expensive_phase",
                    "skip_charge_when_cheaper_cluster_coming",
                    "cheaper_cluster_min_reserve_hours",
                    "charging_price_hard_cap",
                }
                # Hidden from the editor: deprecated flags. They stay
                # functional for backward compatibility (existing
                # configs keep working) but must not be configured
                # anymore -- see the DEPRECATED rows in the README.
                deprecated_keys = [
                    "skip_charge_when_battery_sufficient",
                    "skip_charge_when_battery_covers_overnext",
                    # Auto-detected since 0.8.58: measured grid-charge
                    # power wins, else GX/BMS capability. Manual value
                    # ignored (goes stale after hardware changes).
                    "charge_power_watts",
                    # Inert since the dynamic_ess removal (2026-10):
                    # every value resolves to classic; the real control
                    # channel picks itself per firmware (hub4 -> the
                    # RAM setpoint keeper, else the classic registers).
                    # Nothing left to choose -- hidden, documented in
                    # the README table.
                    "control_backend",
                ]
                grouped_keys = set(solar_keys + battery_keys + economics_keys + grid_keys + deprecated_keys)
                section_keys = ["ess_unit", "markets", "prices", "pv_panels", "smart_switches", "solar_forecast_providers"]
                %>
                % for key, value in config.items():
                    % if key not in section_keys and key not in grouped_keys and key not in deprecated_keys:
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
                            <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                            <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}><br/>
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

                </fieldset>

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
                                <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                                <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}><br/>
                            % else:
                                <input type="text" id="{{ key }}" name="{{ key }}" value="{{ value }}"><br>
                            % end
                        % end
                    % end
                </fieldset>

                <fieldset>
                    <legend>Battery / Charging</legend>
                    <p class="economic-note" id="economic-note" {{ '' if economic_mode else 'style="display:none;"' }}>Economic mode active: the cap-only rules (covering-block, cheaper-cluster, hard cap) are hidden while dormant &mdash; the marginal-price rule decides. They re-appear when the strategy is switched back to Cap.</p>
                    % if isinstance(config.get("prices"), list) and config["prices"] and "charging_strategy" in config["prices"][0]:
                        <%
                        strategy_value = config["prices"][0]["charging_strategy"]
                        if tooltips and "charging_strategy" in tooltips:
                            title = tooltips.get("charging_strategy")
                            additional = ' \u2139\ufe0f'
                        else:
                            title = ''
                            additional = ''
                        end
                        %>
                        <label class="tooltip" for="prices:charging_strategy" title="{{ title }}">{{ " ".join(word.capitalize() for word in "charging_strategy".split("_")) }}{{ additional }}</label><br>
                        <select id="prices:charging_strategy" name="prices:charging_strategy">
                            <option value="cap" {{ 'selected' if strategy_value == 'cap' else '' }}>Cap (hard cap blocks charging)</option>
                            <option value="economic" {{ 'selected' if strategy_value == 'economic' else '' }}>Economic (marginal displaced price)</option>
                        </select><br>
                        <br>
                    % end
                    % for key in battery_keys:
                        % if key in config:
                            <div class="cfg-row" data-cap-only="{{ '1' if key in cap_only_keys else '0' }}" {{ !('style="display:none;"' if economic_mode and key in cap_only_keys else '') }}>
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
                                <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                                <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}><br/>
                            % else:
                                <input type="text" id="{{ key }}" name="{{ key }}" value="{{ value }}"><br>
                            % end
                            </div>
                        % end
                    % end
                </fieldset>

                <fieldset>
                    <legend>Economic strategy</legend>
                    % for key in economics_keys:
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
                                <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                                <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}><br/>
                            % else:
                                <input type="text" id="{{ key }}" name="{{ key }}" value="{{ value }}"><br>
                            % end
                        % end
                    % end
                </fieldset>

                <fieldset>
                    <legend>Grid Tariff</legend>
                    % for key in grid_keys:
                        % if key in config:
                            <%
                            value = config[key]
                            label = grid_labels.get(
                                key, " ".join(word.capitalize()
                                              for word in key.split("_")))
                            if tooltips and key in tooltips:
                                title = tooltips.get(key)
                                additional = ' \u2139\ufe0f'
                            else:
                                title = ''
                                additional = ''
                            end
                            %>
                            <label class="tooltip" for="{{ key }}" title="{{ title }}">{{ label }}{{ additional }}</label>
                            % if isinstance(value, bool):
                                <input type="hidden" id="{{ key }}_hidden" name="{{ key }}" value="off">
                                <input type="checkbox" id="{{ key }}" name="{{ key }}" {{ 'checked' if value == True else '' }}>
                            % else:
                                <input type="text" id="{{ key }}" name="{{ key }}" value="{{ value }}">
                            % end
                            <br/>
                        % end
                    % end
                </fieldset>

                % if isinstance(config["prices"], list):
                    <fieldset>
                        <legend>Prices</legend>
                        % for price_data in config["prices"]:
                            % for field_key, field_value in price_data.items():
                                % if field_key == "charging_strategy":
                                    % continue
                                % end
                                <%
                                cap_only = field_key in cap_only_keys
                                if tooltips and field_key in tooltips:
                                    title=tooltips.get(field_key)
                                    additional=' ℹ️'
                                else:
                                    title = ''
                                    additional= ''
                                end
                                formatted_text = " ".join(word.capitalize() for word in field_key.split("_")) + additional
                                %>
                                <div class="cfg-row" data-cap-only="{{ '1' if cap_only else '0' }}" {{ !('style="display:none;"' if economic_mode and cap_only else '') }}>
                                <label class="tooltip" for="prices:{{ field_key }}" title="{{ title }}">{{ formatted_text }}</label><br/>
                                % if isinstance(field_value, bool):
                                    <input type="hidden" id="prices:{{ field_key }}_hidden" name="prices:{{ field_key }}" value="off">
                                    <input type="checkbox" id="prices:{{ field_key }}" name="prices:{{ field_key }}" {{ 'checked' if field_value == True else '' }}><br/>
                                % else:
                                    <input type="text" id="prices:{{ field_key }}" name="prices:{{ field_key }}" value="{{ field_value }}"><br>
                                % end
                                </div>
                            % end
                        % end
                    </fieldset>
                % else:
                    <p>Prices is not a list!</p>
                % end
        </div>

        <div class="editor-sections">
            <div id="sectionFields_ess_unit" style="display: none;"></div>
            <div id="sectionFields_markets" style="display: none;"></div>
            <div id="sectionFields_pv_panels" style="display: none;"></div>
            <div id="sectionFields_smart_switches" style="display: none;"></div>
            <div id="sectionFields_solar_forecast_providers" style="display: none;"></div>
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
    <script>
        // Charging-strategy toggle: instantly show/hide the cap-only
        // switches (dormant under economic) WITHOUT save + reload --
        // mirrors the server-side rendering (same rows, same note).
        (function () {
            var strat = document.getElementById('prices:charging_strategy');
            if (!strat) return;
            var note = document.getElementById('economic-note');
            var rows = document.querySelectorAll('.cfg-row[data-cap-only="1"]');
            function apply() {
                var economic = (strat.value === 'economic');
                if (note) note.style.display = economic ? '' : 'none';
                for (var i = 0; i < rows.length; i++) {
                    rows[i].style.display = economic ? 'none' : '';
                }
            }
            strat.addEventListener('change', apply);
            strat.addEventListener('input', apply);
            apply();
        })();
    </script>

</body>

</html>
