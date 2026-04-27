![Logo](views/static/images/logo-seuss.png?raw=true "SEUSS")

# SEUSS

### [SEUSS -> Smart Ess Unit Spotmarket Switcher]

#### Please report the bugs and suggest improvements. Thank you to everyone who has already taken part.

###### If you would like to contribute extensions to this, please submit the pull request in the dev branch. For bug fixes, the pull request can also be made on the main branch

### What does this software do?

This is a Python 3 Application that turns on your ESS unit (controller) at the right time when your hourly dynamic
energy prices are low. Or used for discharging when prices are extremely high.

---

### Design Note: Configurable Cluster Lengths over 15-min Quarters

Since 2025 the European spot markets deliver 15-minute prices via ENTSO-E. SEUSS works internally on quarter-hour items but groups them into **clusters** of a configurable length (`charging_block_minutes`, `discharging_block_minutes`, `switching_block_minutes`, default 60 min) for selection and switching. Within `tariff_resolution: hourly` (the default for typical Awattar/Tibber retail tariffs), the four quarters of an hour share the average price so clusters land on full hours.

**Why this matters:**

- ⚖ **Tariff-aware:** Hourly billing? Use `tariff_resolution: hourly` and quarters within an hour are treated equally — clusters align to full hours, just like before. Quarterly billing? Switch to `quarterly` and SEUSS uses the real 15-min spread.
- ⏱ **Configurable cluster length:** Whether you want 60-minute charge clusters or 30-minute ones is now a config setting, not hard-wired.
- 🔌 **Predictable totals:** `8 charge × 60 min + 16 discharge × 60 min = 24 h fully covered`. The optional `fill_gaps_with_short_clusters` keeps the day contiguous when sliding-window placement leaves small slivers.
- 🛠 **Hardware stability:** The hard cap is checked per quarter, so a single expensive 15-min slot in an otherwise cheap cluster pauses charging without breaking the cluster apart visually (it shows olive in the chart).

> For a detailed explanation of the cluster model, see the [full design note](./SEUSS_hourly_price_design_decision.md).

---
#### Currently supported systems are:

### ESS Units

___

- ***Victron Venus OS energy storage systems such as the MultiPlus II series***

___

### Spot Markets

___

- ***aWATTar***
- ***Entso-E***
- ***Tibber***

___
The control of the ESS unit (controller) is done via mqtt. The advantage of this control is:
that this application does not have to run directly on VenusOS. Direct control with D-BUS is in the works

# Tested

This version was successful with
___

- ***Linux Ubuntu >= 22.04***
- ***Venus OS Raspberry >= v3.12***

___
tested

# Install

Download the installation script from the GitHub repository execute the following command in your terminal:

```
wget -O seuss_install.sh https://raw.githubusercontent.com/ckvsoft/SEUSS/dev/scripts/seuss_install.sh`
```

Run the installer script with additional options to prepare everything in a subdirectory for your inspection. For
example:

```
bash seuss_install.sh`
```

The default directory is /data/seuss (Venus OS) But you can optionally specify a different directory by using the
environment variable TARGET_DIRECTORY e.g.

```
TARGET_DIRECTORY=/opt/seuss bash seuss_install.sh`
```

On a Cerbo GX the filesystem is mounted read only.
See [https://www.victronenergy.com/live/ccgx:root_access](https://www.victronenergy.com/live/ccgx:root_access).
In order to make the filesystem writeable you need to execute the following command before running the installation script:

```
/opt/victronenergy/swupdate-scripts/resize2fs.sh
```

# Configuration

After `SEUSS` has been successfully installed, a website is available at the IP address and port 5000 of
the `Computer/VenusOS` on which `SEUSS` was installed.

- You can view or download the log file.
- Furthermore, the configuration can be carried out using the [Config Editor] menu item.
- Tool tips for most points are displayed here.

#### Log Viewer

- ![Logo](views/static/images/logviewer.png?raw=true "SEUSS Log Viewer")

#### Config Editor - ESS Units

- ![Logo](views/static/images/configeditor_ess.png?raw=true "SEUSS Config Editor")

#### Config Editor - PV Panels

- ![Logo](views/static/images/configeditor_panels.png?raw=true "SEUSS Config Editor")

These can also be found in the Settings description.
For those who prefer to work in a config file, there is config.json

# Settings

## General

| Setting             | Meaning                                                                                                                                                                                                                                                                                                                                                                  |
|---------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `time_zone`         | Essential for correct timing of operations based on your geographic location.<br/> Format like `Europe/Vienna`, `Europe/Amsterdam`, ...                                                                                                                                                                                                                                  |
| `tariff_resolution` | How your contract bills the electricity. <br/>`hourly` (default) — billing is per hour even if the spot data is quarter-hour (typical Awattar / Tibber retail tariffs). The four 15-minute prices of an hour are averaged so cluster selection lands on full hours.<br/>`quarterly` — true 15-minute billing; clusters may start on `:15`, `:30` or `:45` of an hour.    |
| `log_file_path`     | Sets an alternative path to which the log files are saved.                                                                                                                                                                                                                                                                                                               |
| `log_level`         | Used Loglevel are: `INFO`, `WARNING`, `ERROR` and `DEBUG`. see [Log Levels](#loglevels)                                                                                                                                                                                                                                                                                  |

## Prices

#### Please change prices (always use Cent/kWh, no matter if you're using Awattar (displaying Cent/kWh) or Entsoe API (displaying EUR/MWh) / net prices excl. tax).

Since the move to 15-minute spot data, SEUSS works internally on quarter-hour items but groups them into **clusters** (= contiguous blocks) for charging, discharging and switching. Each cluster is exactly the configured `*_block_minutes` long. The number of clusters is the corresponding `number_of_*_prices_*` setting. So `8 charge clusters × 60 min = 8 hours of charging`.

When sliding-window placement (`tariff_resolution: quarterly`) leaves small gaps between charge and discharge clusters, the optional `fill_gaps_with_short_clusters` covers those slivers with shorter discharge blocks so the chart paints contiguously when the totals add up to 24 h.

| Setting                                      | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
|----------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `use_second_day`                             | `enable/disable` to compare today and tomorrow prices if they become available<br/>Note: If you activate this and the prices decrease over several days,it is possible that there will be no charging or switching for several days until the lowest prices are reached.                                                                                                                                                                                                                                                                                       |
| `number_of_lowest_prices_for_charging`       | Number of cheapest charge **clusters** per day, where each cluster is `charging_block_minutes` long.<br/>**mode 1 (integer)**: the literal number of clusters, e.g. `8` with `charging_block_minutes=60` gives 8 hours of charging per day.<br/>**mode 2 (decimal in `(0, 1)`)**: thresholding mode, e.g. `0.85` selects every cluster whose average is below 85% of the day average — the count is computed.<br/>Legacy: `1.0` is treated as "1 cheapest cluster" (the old "100% of average" interpretation never made sense and is preserved as integer-1).   |
| `number_of_highest_prices_for_discharging`   | Number of most expensive discharge **clusters** per day, each `discharging_block_minutes` long. Same dual-mode semantics as the charging counterpart (integer = literal count, decimal `>1` = "above X×day-average").                                                                                                                                                                                                                                                                                                                                          |
| `number_of_lowest_prices_for_switching`      | Independent cluster count for smart-switch operation. `0` (default) falls back to `number_of_lowest_prices_for_charging`. Set this when your smart switches should run on a different schedule than the ESS charging window (e.g. boilers that need longer runs).                                                                                                                                                                                                                                                                                              |
| `charging_block_minutes`                     | Length of each charging cluster in minutes. Multiples of 15, no upper limit. Default `60` keeps the historical hour-cluster behaviour. Smaller values trade against switching-cycle wear.                                                                                                                                                                                                                                                                                                                                                                      |
| `discharging_block_minutes`                  | Length of each discharging cluster in minutes. Same rules as `charging_block_minutes`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `switching_block_minutes`                    | Length of each smart-switch cluster in minutes.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `fill_gaps_with_short_clusters`              | When sliding-window cluster placement leaves a gap of less than `*_block_minutes` between two selected blocks, fill it with a shorter discharge cluster (15 / 30 / 45 min). Default `true`. Disable to keep cluster lengths strictly equal to `*_block_minutes` and accept small white slivers in the chart.                                                                                                                                                                                                                                                   |
| `charging_price_limit`                       | Charging is always enabled when the per-quarter price is below this value, regardless of cluster selection. Use this as a "safety floor": below this price, always charge.                                                                                                                                                                                                                                                                                                                                                                                     |
| `charging_price_hard_cap`                    | Charging is strictly prohibited when the per-quarter price exceeds this value. Checked per quarter (not per cluster average), so a single expensive 15-minute slot inside an otherwise cheap cluster still pauses charging for that quarter. The chart paints such quarters **olive** instead of green so you see them at a glance.                                                                                                                                                                                                                            |
| `use_solar_forecast_to_abort`                | When enabled, charging is aborted while two conditions both hold: **(a)** the combined adjusted solar forecast for today + tomorrow covers at least two days of average consumption, AND **(b)** the current battery SOC alone covers consumption until tomorrow's sunrise (with a 10% safety buffer). Either condition alone has known failure modes (forecast-only drains the battery overnight; SOC-only ignores a streak of bad-weather days), so both must hold. Falls back to "charging allowed" on any missing data. Default `false`. The accuracy of the underlying solar forecast is governed by the `solar_adj_*` settings below. |
| `skip_charge_when_battery_sufficient`        | When enabled, charging is skipped while **all** of these hold: the current price is above `charging_price_limit`; there exists a future, equally-cheap or cheaper charge cluster later in the schedule; AND the current usable SOC (current_wh - min_wh) covers projected consumption until that future cluster (10% safety buffer). Independent of solar -- this complements `use_solar_forecast_to_abort` for setups without usable PV. When both flags are on, the solar abort is evaluated first; this one only matters if solar didn't already trigger a skip. Falls back to "charging allowed" on missing consumption data. Default `false`. |
| `solar_adj_ewma_alpha`                       | Smoothing factor for the solar forecast adjustment factor (`adjustment_factor` in stats). Range `0.0`–`1.0`. Each day's observed-vs-forecast ratio enters the persisted multiplier with weight `alpha`; the prior value keeps weight `1 - alpha`. Default `0.3` (moderate smoothing). `1.0` reproduces the legacy behaviour (each day overwrites the factor). `0.0` freezes the factor at its current value.                                                                                                                                                  |
| `solar_adj_min_theoretical_wh`               | Minimum theoretical net yield (Wh) accumulated since 00:00 before SEUSS will update the adjustment factor on a given evaluation. Default `1000`. Lower values learn earlier in the day but react more strongly to morning weather quirks; raise this if your forecast tends to over-correct on cloudy mornings.                                                                                                                                                                                                                                                |
| `solar_adj_min_sun_hours`                    | Minimum hours past local sunrise (approximated as hours past 06:00) before SEUSS will update the adjustment factor. Default `4.0`. Pairs with `solar_adj_min_theoretical_wh` -- both conditions must be met. Set higher in regions with very late sunrise.                                                                                                                                                                                                                                                                                                     |
| `solar_adj_max_daily_change`                 | Maximum absolute change of the adjustment factor per evaluation. Default `0.20` (i.e. ±20% per day). Set to `0` to disable the cap. Prevents a single freak day from yanking the factor across its full `[0.2, 2.0]` range.                                                                                                                                                                                                                                                                                                                                    |
| `delay_grid_charging_below_active_soc_limit` | Prevents charging from the grid when it returns if SOC is below the Active SOC Limit and electricity prices are high.                                                                                                                                                                                                                                                                                                                                                                                                                                          |

### Chart visualisation

The price chart in the SEUSS web UI now shows quarter-resolution colours on top of the hourly bars:

- **Green** — quarter is part of an active charging cluster and the per-quarter price is under `charging_price_hard_cap`. Past hours show as darker green.
- **Olive** — quarter is part of a charging cluster but its price exceeds the hard cap, so SEUSS will skip that 15-minute slot. Distinguishes "would charge but cap blocks" from "unrelated grey hour".
- **Red** — quarter is part of an active discharging cluster. Past hours show as darker red.
- **Grey** — quarter is not part of any cluster (because the totals don't cover 24 h).

Hovering over an hour bar shows a tooltip with the four real per-quarter prices for that hour — useful when `tariff_resolution=quarterly` makes them differ.

The chart text adapts automatically to light and dark mode via the `chart-text` CSS class in `views/static/styles.css`.

## ESS Units

### Victron

| Setting               | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                  |
|:----------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `use_vrm`             | If this point is enabled (true), an attempt is made to connect to the Victron via the VRM portal.<br/>This requires a user/password in the VRM portal                                                                                                                                                                                                                                                                    |
| `ip_address`          | The local IP address of the Victron.<br/>This is required if `use_vrm` is disabled (false).<br/>Otherwise this field remains empty                                                                                                                                                                                                                                                                                       |
| `unit_id`             | VRM Portal ID<br/>can be found in the `Settings / VRM online portal / VRM Portal Id`.<br/>Note: This ID is required to access the Victron even if you are not using a VRM portal                                                                                                                                                                                                                                         |
| `user`                | mail adress you use to connect to VRM portal                                                                                                                                                                                                                                                                                                                                                                             |
| `password`            | password you use to connect to VRM portal                                                                                                                                                                                                                                                                                                                                                                                |
| `max_discharge_power` | Default: -1<br/>If you use `Limit inverter power` in the ESS menu then this value must be entered here.<br/>If the inverter is set to `Discharge false` by this app then this value will be overwritten in the ESS.<br/>This limit here is set in discharge mode in the ESS.<br/>If no limit is set then leave the value at `-1`.<br/>Example: Enter `1000` to limit the discharge to `1000W`, Enter `-1` for full Power |
| `only_observation`    | If `only observation` is activated the essunit will only be used for statistical purposes. The essunit does not execute any conditions                                                                                                                                                                                                                                                                                   |
| `enabled`             | To use this entry it must be `enabled`. Otherwise `disabled`                                                                                                                                                                                                                                                                                                                                                             |

## Spot Markets

### aWATTar

| Setting    | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
|:-----------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `country`  | Choose location AT or DE                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `fee`      | This parameter defines the fee to be added to the base price. The fee can be specified as a percentage (e.g., 3% + 2.5 for 3% of the base price plus a fixed fee of 2.5 cents), or just a fixed amount (e.g., 2.5 for a flat fee of 2.5 cents). The fixed fee must always be specified in cents. If no fee should be applied, this field must be left empty. The final price is calculated using the formula: Final price = Base price + Fee. Please note that the price is calculated excluding tax, and the fee is already included in the final price. For the special case of "entsoe", there is no direct fee. In this case, the fee should be taken from the primary market. If "entsoe" is the primary market, the fee should be taken from the fallback market instead.  |
| `primary`  | If this market is enabled this point sets it as the primary market                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `enabled`  | To use this entry it must be `enabled`. Otherwise `disabled`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

### Entso-e

| Setting      | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
|:-------------|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `api_token`  | How to get the free api_security_token:<br/>1. Go to https://transparency.entsoe.eu/ --> register and create an account<br/>2. Send an email to transparency@entsoe.eu with “Restful API access” in the subject line<br/>3. The ENTSO-E Helpdesk will respond to your request within 3 working days.<br/>4. Generate a security token at https://transparency.entsoe.eu/usrm/user/myAccountSettings                                                                                                                                                                                                                                                                                                                                                                             |
| `in_domain`  | To find out your in and out domain key go to:<br/>https://www.entsoe.eu/data/energy-identification-codes-eic/eic-area-codes-map/                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `out_domain` | like `in_domain`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `fee`        | This parameter defines the fee to be added to the base price. The fee can be specified as a percentage (e.g., 3% + 2.5 for 3% of the base price plus a fixed fee of 2.5 cents), or just a fixed amount (e.g., 2.5 for a flat fee of 2.5 cents). The fixed fee must always be specified in cents. If no fee should be applied, this field must be left empty. The final price is calculated using the formula: Final price = Base price + Fee. Please note that the price is calculated excluding tax, and the fee is already included in the final price. For the special case of "entsoe", there is no direct fee. In this case, the fee should be taken from the primary market. If "entsoe" is the primary market, the fee should be taken from the fallback market instead. |
| `primary`    | If this market is enabled this point sets it as the primary market                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `enabled`    | To use this entry it must be `enabled`. Otherwise `disabled`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

### Tibber

| Setting      | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
|:-------------|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `api_token`  | To get the tibber_api_key:<br/>1. log in with a free or customer Tibber account at https://developer.tibber.com/settings/access-token<br/>2. Create a token by selecting the scopes you need (select "price")<br/>3. Use this link to create a free account with your smartphone: https://tibber.com/de/invite/ojgfbx2e                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `price_unit` | Set to:<br/>"energy" to use the spotmarket-prices (default),<br/>"total" to use the total prices including taxes and fees,<br/>"tax" to use only the taxes and fees                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `fee`        | This parameter defines the fee to be added to the base price. The fee can be specified as a percentage (e.g., 3% + 2.5 for 3% of the base price plus a fixed fee of 2.5 cents), or just a fixed amount (e.g., 2.5 for a flat fee of 2.5 cents). The fixed fee must always be specified in cents. If no fee should be applied, this field must be left empty. The final price is calculated using the formula: Final price = Base price + Fee. Please note that the price is calculated excluding tax, and the fee is already included in the final price. For the special case of "entsoe", there is no direct fee. In this case, the fee should be taken from the primary market. If "entsoe" is the primary market, the fee should be taken from the fallback market instead. |
| `primary`    | If this market is enabled this point sets it as the primary market                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `enabled`    | To use this entry it must be `enabled`. Otherwise `disabled`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

## PV Panels

| Setting           | Meaning                                                                                      |
|:------------------|:---------------------------------------------------------------------------------------------|
| `locLat`          | Latitude                                                                                     |
| `locLong`         | Longitude                                                                                    |
| `angle`           | Angle of your panels 0 (horizontal) … 90 (vertical)                                          |
| `direction`       | Plane azimuth, -180 … 180 (-180 = north, -90 = east, 0 = south, 90 = west, 180 = north)      |
| `totPower`        | Installed peak power in **kWp** -- the hardware ceiling above which the inverter cannot deliver, regardless of irradiance. Used as a hard cap on each hour's forecast (`min(theoretical_yield, totPower * 1000)`).                                                                                                                                                                                                                                                                                                                            |
| `total_area`      | Physical surface area of the installed panels in **m²**, as mounted on roof / ground / wall. Sum of the glass area of all modules in this group (e.g. 10 modules × 1.7 m² = 17 m²). Together with `efficiency` this drives the *theoretical* hourly yield: `irradiance_W_per_m² × total_area × efficiency`. **Important:** if you leave this at `0` (the default), the theoretical yield is `0` and **the entire forecast for this panel collapses to zero** -- only the `totPower` cap remains, and `min(0, cap) = 0`. So you must set both `total_area` and `efficiency` for the forecast to work, even though `totPower` already encodes the hardware limit. A future revision may consolidate these. |
| `efficiency`      | Module efficiency in **%** (typical 18–22 for modern silicon). Multiplied with `total_area` to convert irradiance into Wh. You can also lower this value over time to model panel ageing or persistent partial shading without changing the physical area.                                                                                                                                                                                                                                                                                       |
| `damping_morning` | With this parameter you can adjust the result in the morning. Value float 0..1, default 0    |
| `damping_evening` | With this parameter you can adjust the result in the evening. Value float 0..1, default 0    |
| `enabled`         | To use this entry it must be `enabled`. Otherwise `disabled`                                 |

## Smart Switches  

### Shelly  

| Setting    | Meaning                                                                                                                                                                                                                                 |
|:-----------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ips`      | A list of IP addresses assigned to the device. Use `\|` to separate multiple IPs. Prefix an IP with `!` to temporarily disable it without removing it from the list. Example: `"10.1.1.20 \| !10.1.1.21"` (IP `10.1.1.21` is disabled). |
| `user`     | The username required for authentication (if applicable).                                                                                                                                                                               |
| `password` | The password required for authentication (can be encoded in base64).                                                                                                                                                                    |
| `enabled`  | To use this entry, it must be set to `true`. Otherwise, it is `false` (disabled).                                                                                                                                                       |

### Tasmota  

| Setting    | Meaning                                                                                                                                                                                      |
|:-----------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ips`      | A list of IP addresses assigned to the device. Use `\|` to separate multiple IPs. Prefix an IP with `!` to temporarily disable it without removing it from the list. Example: `"10.1.1.30"`. |
| `user`     | The username required for authentication.                                                                                                                                                    |
| `password` | The password required for authentication (can be encoded in base64).                                                                                                                         |
| `enabled`  | To use this entry, it must be set to `true`. Otherwise, it is `false` (disabled).                                                                                                            |

### Fritz  

| Setting    | Meaning                                                                                                                                                                                                                                                                                                 |
|:-----------|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ips`      | A list of IP addresses assigned to the device. Use `\|` to separate multiple IPs. Prefix an IP with `!` to temporarily disable it without removing it from the list. Example: `"192.168.178.1 \| !10.1.1.23"` (IP `10.1.1.23` is disabled).                                                             |
| `ains`     | A list of AINs (Actor Identification Numbers) for Fritz devices. Multiple AINs are separated by commas, and if multiple IPs are used, the AINs for each IP are separated by `\|`. Example: `"1234,3443,2333 \| 1234,4456,7866,3421"`.                                                                   |
| `user`     | The username required for authentication.                                                                                                                                                                                                                                                               |
| `password` | The password required for authentication (can be encoded in base64).                                                                                                                                                                                                                                    |
| `enabled`  | To use this entry, it must be set to `true`. Otherwise, it is `false` (disabled).                                                                                                                                                                                                                       |

### Per-IP override (all switch types)

By default every IP under a smart-switch entry uses the global `number_of_lowest_prices_for_switching` and `switching_block_minutes` from the `prices` section. Two optional pipe-separated lists let you override these per IP:

| Setting                 | Meaning                                                                                                                                                                                                                                          |
|:------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `lowest_prices_per_ip`  | Pipe-separated list, position-aligned with the **active** IPs in `ips` (i.e. excluding any prefixed with `!`). Each entry is the cluster count for that IP. An empty entry means "use the global default". Example: `"8\|4\|"` runs the first IP on the 8 cheapest clusters, the second on 4, the third on the global default. |
| `block_minutes_per_ip`  | Pipe-separated list, position-aligned with the **active** IPs in `ips`. Each entry is the cluster length in minutes (multiple of 15) for that IP. An empty entry means "use the global default". Example: `"60\|30\|"`.                                                |

When **any** smart-switch entry uses one of these overrides, all switches are evaluated per-IP — the legacy "switch them all together based on a single condition" logic kicks in only when no override is configured anywhere.

***

## Loglevels

### `ERROR`

The `ERROR` log level indicates error conditions within an application that hinder the execution of a specific
operation. While the application can continue functioning at a reduced level of functionality or
performance,<br/>`ERROR` logs signify issues that should be investigated promptly.

### `WARN`

Events logged at the `WARN` level typically indicate that something unexpected has
occurred, but the application can continue to function normally for the time being.
It is also used to signify conditions that should be promptly addressed before they
escalate into problems for the application.

### `INFO`

The `INFO` level captures events in the system that are significant to the
application's business purpose. Such events are logged to show that the system is
operating normally. Production systems typically default to logging at this level
so that a summary of the application's normal behavior is visible to anyone
reviewing the logs.

### `DEBUG`

The `DEBUG` level is used for logging messages that aid developers in identifying
issues during a debugging session. The content of the messages logged at the DEBUG
level will vary depending on your application, but they typically contain
detailed information that assists its developers in troubleshooting problems
efficiently. This can include variables' state within the surrounding scope or
relevant error codes. |

## Inspiration

The idea is inspired by the @christian1980nrw project linked below. This project is my first with the Victron Venus OS,
so I adopted some ideas and approaches from the following projects. The approach is the same and for very narrow systems
the implementation with a bash script is probably better

##### – thank you very much for passing on the knowledge:

- [Spotmarket-Switcher](https://github.com/christian1980nrw/Spotmarket-Switcher)
- [dynamic-ess](https://github.com/tfranssen/dynamic-ess)
