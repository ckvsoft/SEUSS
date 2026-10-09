![Logo](views/static/images/logo-seuss.png?raw=true "SEUSS")

# SEUSS

### SEUSS → Smart ESS Unit Spotmarket Switcher

Bug reports and improvement ideas are welcome — thanks to everyone who has contributed so far.

Want to contribute an extension? Please open the pull request against the **dev** branch. Bug fixes can also go to **main**.

## What does SEUSS do?

SEUSS is a small Python 3 program that controls your battery (ESS) based on your dynamic electricity prices: it **charges when power is cheap** and lets the battery **discharge when power is expensive**.

Every few minutes it reads the current and upcoming prices, decides *charge / discharge / idle*, and tells the Victron system what to do through the grid setpoint. It talks to the Victron over MQTT, so it does **not** have to run on the VenusOS device itself. Everything is configured in a web editor.

## Concepts in plain words

- **Spot price** — the exchange price for electricity, per 15-minute slot. Comes from your market feed (aWATTar / ENTSO-E / Tibber).
- **Fee** — your supplier's markup on top of the spot price (`fee` per market, e.g. `3% + 1.5` = 3 % of the spot price + 1.5 ct fixed).
- **Grid fee** — what your network operator charges. Two parts: the **work price** (ct per kWh, `grid_work_price_ct`) and, from 2027, a **demand charge** based on your highest 15-minute power (the `grid_demand_*` settings).
- **SNAP / WiNAP** — cheaper grid-fee windows for Austrian households: **SNAP** in summer (Apr–Sep, 10–16 h), **WiNAP** in winter (Oct–Mar, 22–04 h). Both already exist.
- **Cluster** — a run of consecutive 15-minute slots SEUSS treats as one charge/discharge block (`*_block_minutes`).
- **SOC** — state of charge of the battery in %.
- **RTE** — round-trip efficiency (charge + discharge losses), `round_trip_efficiency`.

**Clusters:** instead of switching on every single 15-minute slot, SEUSS groups slots into **clusters** of a configurable length (`charging_block_minutes`, `discharging_block_minutes`, `switching_block_minutes`, default 60 min) — a compromise between reacting to prices and not switching the hardware constantly. See the [full design note](./SEUSS_hourly_price_design_decision.md) for details.

---

#### Currently supported systems


**ESS units**

- ***Victron Venus OS energy storage systems such as the MultiPlus II series***

**Spot markets**

- ***aWATTar***
- ***Entso-E***
- ***Tibber***

The ESS unit is controlled over MQTT, so SEUSS does not have to run directly on VenusOS. Direct D-BUS control is in the works.

## Tested

- ***Linux Ubuntu >= 22.04***
- ***Venus OS Raspberry >= v3.12***

## Install

Download the installer from GitHub and run it:

```
wget -O seuss_install.sh https://raw.githubusercontent.com/ckvsoft/SEUSS/dev/scripts/seuss_install.sh`
```

```
bash seuss_install.sh
```

Default install directory is `/data/seuss` on Venus OS. Pick another with `TARGET_DIRECTORY`:

```
TARGET_DIRECTORY=/opt/seuss bash seuss_install.sh
```

On a Cerbo GX the filesystem is mounted read-only
([root access](https://www.victronenergy.com/live/ccgx:root_access)). Make it writable first:

```
/opt/victronenergy/swupdate-scripts/resize2fs.sh
```

## Configuration

After install, the SEUSS web UI is served on port **5000** of the machine running it. There you can:

- view / download the log,
- edit the configuration in the **Config Editor** (with tooltips on most fields).

For those who prefer a file, everything lives in `config.json`.

#### Log Viewer

- ![Logo](views/static/images/logviewer.png?raw=true "SEUSS Log Viewer")

#### Config Editor - ESS Units

- ![Logo](views/static/images/configeditor_ess.png?raw=true "SEUSS Config Editor")

#### Config Editor - PV Panels

- ![Logo](views/static/images/configeditor_panels.png?raw=true "SEUSS Config Editor")

---

# Settings

Settings use **Cent/kWh**, no matter which market you use (aWATTar shows Cent/kWh, ENTSO-E shows EUR/MWh — SEUSS normalises both). Prices are **net**, excl. tax, unless you set `vat_percent`.

## General

| Setting             | Meaning                                                                                                                                                                                                                             |
|---------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `time_zone`         | Your local time zone, e.g. `Europe/Vienna`, `Europe/Amsterdam`. Needed so charging happens at the right clock time.                                                                                                                  |
| `tariff_resolution` | How your contract is billed. `hourly` (default): the four 15-minute prices of an hour are averaged, so blocks line up with full hours (typical aWATTar / Tibber retail tariffs). `quarterly`: true 15-minute billing; blocks may start at `:15`, `:30`, `:45`. |
| `log_file_path`     | Alternative path for the log file.                                                                                                                                                                                                   |
| `log_level`         | `INFO`, `WARNING`, `ERROR` or `DEBUG` — see [Log levels](#log-levels).                                                                                                                                                                |

## Prices

Since the move to 15-minute spot data, SEUSS works internally on quarter-hour prices but groups them into **clusters** (= contiguous blocks) for charging, discharging and switching. Each cluster is exactly `*_block_minutes` long; the number of clusters is the matching `number_of_*_prices_*` setting. So `8 charge clusters × 60 min = 8 h of charging` per day.

When `tariff_resolution: quarterly` leaves small gaps between charge and discharge clusters, `fill_gaps_with_short_clusters` fills them with shorter blocks so the day paints contiguously.

| Setting                                      | Meaning                                                                                                                                                                                                                                                              |
|----------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `use_second_day`                             | Also consider tomorrow's prices once published. Note: if prices keep falling over several days, SEUSS may wait and not charge/switch until they bottom out. Default `false`.                                                                                         |
| `number_of_lowest_prices_for_charging`       | How many cheap **charging blocks** per day (each `charging_block_minutes` long). Integer = literal count, e.g. `8` × 60 min = 8 h. Decimal in `(0, 1)` = "every block cheaper than X× the day average", e.g. `0.85` (count is calculated). `1.0` = one cheapest block. If charging + discharging blocks don't add up to 24 h, SEUSS logs a startup warning (the rest stays grey). |
| `number_of_highest_prices_for_discharging`   | How many expensive **discharge blocks** per day (each `discharging_block_minutes`). Same integer/decimal rules as the charging count.                                                                                                                                |
| `number_of_lowest_prices_for_switching`      | Block count for the smart switches. `0` (default) reuses the charging count. Set it when the switches should run on a different schedule.                                                                                                                            |
| `charging_block_minutes`                     | Length of each charging block in minutes (multiple of 15). Default `60`. Shorter = reacts faster, switches more often.                                                                                                                                               |
| `discharging_block_minutes`                  | Same, for discharge blocks.                                                                                                                                                                                                                                          |
| `switching_block_minutes`                    | Same, for smart-switch blocks.                                                                                                                                                                                                                                       |
| `fill_gaps_with_short_clusters`              | When block placement leaves a gap shorter than a block, fill it with a shorter block (15/30/45 min) so the chart paints contiguously. Default `true`.                                                                                                                |
| `charging_price_limit`                       | "Always charge" floor: below this price (ct/kWh) charging is allowed regardless of block selection.                                                                                                                                                                  |
| `charging_price_hard_cap`                    | "Never charge above this" (ct/kWh), checked per 15-minute slot. Only used in `cap` strategy. Such slots show **olive** in the chart.                                                                                                                                 |
| `charging_strategy`                          | `cap` (default): charge in the cheapest blocks, blocked above `charging_price_hard_cap`. `economic`: charge whenever `quarter price / round_trip_efficiency` is below the price of the most expensive hour the extra energy would displace (uses the upcoming price chain). Usually saves more; replaces the hard cap with `economic_price_ceiling` as a safety leash. |
| `economic_price_ceiling`                     | Safety limit (ct/kWh) for `economic`: never charge above this, even if the rule says so. Only guards against bad price data. Default `60`.                                                                                                                           |
| `round_trip_efficiency`                      | Battery efficiency (charge + discharge) used by `economic`, default `0.90`. The charge price is divided by this before comparing to the displaced price.                                                                                                            |
| `vat_percent`                                | VAT in %, default `0` = off (prices exclude tax). When set (e.g. `20`), all prices are multiplied by `(1 + VAT/100)` at the end, so displayed/compared prices are gross. Raise your price caps/limits accordingly.                                                  |
| `soc_target_resume_gap_percent`              | Hysteresis for the SOC-target stop: charging stops just below the target and only resumes after SOC drops this many % further (default `2`). Prevents on/off flip-flopping at the boundary.                                                                          |
| `setpoint_refresh_seconds`                   | How often SEUSS re-sends the grid setpoint (default `30`, allowed 5–120). The Victron override decays ~180 s after the last write, so keep this well below that.                                                                                                     |
| `feedin_max_w`                               | Ceiling (W) of the manual "feed into grid" slider on the index page, default `5000`. Slider: `-1` = off (automatic modes resume), `0` = hold grid neutral at 0 W, `> 0` = feed that many W into the grid.                                                            |
| `feedin_min_soc_percent`                     | SOC floor (%) at which the manual slider auto-stops, default `25` (protects the pack). The feed-in also stops when the price is `<= 0` (feeding would cost money).                                                                                                   |
| `grid_tariff_enabled`                        | Master switch for the grid-fee features (`grid_*`). Default `false`. Needs Victron hub4 firmware (the grid-import limit is enforced through the setpoint).                                                                                                           |
| `grid_demand_peak_limit_w`                   | **Total limit (W), default 10000.** The grid power SEUSS never exceeds. With peak shaving on, the battery covers a house load above it. `0` = no limit.                                                                                                             |
| `grid_demand_peak_target_w`                  | **Charge cap (W), default 5000.** Highest grid power SEUSS allows itself **while charging**. Example: house already at 3 kW → SEUSS adds only ~2 kW of charging to stay at 5 kW. `0` = charge as fast as the total limit allows.                                    |
| `grid_demand_peak_shaving`                   | Let the battery cover house peaks (default `false`). If a load alone would exceed the total limit, the battery discharges the difference — only above the SOC floor.                                                                                                  |
| `grid_demand_peak_shaving_min_soc_percent`   | SOC floor (%) for peak shaving, default `30`. Below it the battery is spared and the load is allowed.                                                                                                                                                               |
| `grid_work_price_ct`                         | Grid work price (ct/kWh), default `0` = off. When set, this grid fee is added to every price (discounted in SNAP/WiNAP), so it counts in the chart and in the charging decision. You can also place it explicitly with `{grid_fee}` in a market `fee`.              |
| `grid_zone_discount_percent`                 | Discount (%) on the grid work price inside SNAP/WiNAP, default `20`.                                                                                                                                                                                                |
| `grid_zone_snap_enabled`                     | Apply the SNAP window (Apr–Sep, 10–16 h). Default `true`.                                                                                                                                                                                                           |
| `grid_zone_winap_enabled`                    | Apply the WiNAP window (Oct–Mar, 22–04 h). Default `true`.                                                                                                                                                                                                          |
| `use_solar_forecast_to_abort`                | Skip charging when the adjusted solar forecast **plus** the current SOC together can cover consumption until tomorrow's sunrise. Default `false`. Tuned by the `solar_adj_*` settings.                                                                              |
| `skip_charge_when_battery_sufficient`        | **Deprecated (hidden).** Replaced by `skip_charge_when_battery_covers_expensive_phase`.                                                                                                                                                                             |
| `skip_charge_when_battery_covers_overnext`   | **Deprecated (hidden).** Redundant with the above.                                                                                                                                                                                                                  |
| `skip_charge_when_battery_covers_expensive_phase` | Skip charging if the current SOC alone covers consumption until the next charge block (any price). Conservative — counts only what's in the pack now. Default `false`.                                                                                           |
| `smart_discharge_priority_to_expensive_hours` | When SOC can't cover the whole expensive phase, discharge only in the most expensive blocks and let the grid serve the cheaper ones. Default `false`.                                                                                                               |
| `skip_charge_for_upcoming_negative_prices`   | Skip charging now (positive price) if prices will go negative soon and the battery will have room to absorb the free energy later. Default `false`.                                                                                                                 |
| `skip_charge_when_cheaper_cluster_coming`    | Skip the current charge if a strictly cheaper block is coming and a simulation shows the plan stays safe. Default `false`. Uses `cheaper_cluster_min_reserve_hours`.                                                                                                 |
| `cheaper_cluster_min_reserve_hours`          | Safety margin (in hours of average consumption) the simulation must keep above the minimum SOC, default `2.0`.                                                                                                                                                      |
| `solar_adj_ewma_alpha`                       | Smoothing (0–1) of the solar-forecast correction factor, default `0.3`. Higher = reacts faster.                                                                                                                                                                     |
| `solar_adj_min_theoretical_wh`               | Minimum forecast yield (Wh) since midnight before the factor updates, default `1000`.                                                                                                                                                                               |
| `solar_adj_min_sun_hours`                    | Minimum hours after sunrise before the factor updates, default `4.0`.                                                                                                                                                                                               |
| `solar_adj_max_daily_change`                 | Maximum change of the factor per day, default `0.20` (±20 %).                                                                                                                                                                                                       |
| `delay_grid_charging_below_active_soc_limit` | Don't grid-charge when SOC is below the Active SOC Limit **and** prices are high. Default `false`.                                                                                                                                                                  |
| `discharge_fallthrough_on_charge_veto`       | When a charge window is vetoed by the strategy, let the battery fall through to the normal discharge rules instead of idling. Shows **orange** in the chart when it actually discharges. Default `false`.                                                            |
| `control_backend`                            | **Inert (hidden).** Always resolves to `classic`; the real control channel is chosen by firmware.                                                                                                                                                                   |

**Charge power (no config key):** the COMMAND side (SetpointKeeper) deliberately commands a high target (32000 W) — the ESS loop self-regulates at the physical ceiling. The PLANNING side (economic rule) uses the measured grid-charge power, auto-calibrated during real charge sessions. The legacy `charge_power_watts` key is ignored and hidden.

### Chart visualisation

The price chart shows quarter-resolution colours on top of the hourly bars:

- **Green** — quarter is in an active charging block and the price is under the effective ceiling.
- **Olive** — quarter is in a charging block but blocked by the price rule (SEUSS will skip it).
- **Orange** — charging was vetoed but the battery actually discharged (fall-through).
- **Red** — quarter is in an active discharging block.
- **Grey** — quarter is in no block (charging + discharging don't cover 24 h).
- **Blue / amber overlay** — the SNAP (amber) and WiNAP (blue) grid-fee windows, when `grid_tariff_enabled` is on.

Hover an hour for the four per-quarter prices. The chart follows light/dark mode via the `chart-text` CSS class.

## HTTP API for external consumers

### `GET /api/prices`

Price snapshot: current quarter price, cheap-block flag, hourly price curves for today/tomorrow with per-hour colour flags, the effective hard cap, and the SNAP/WiNAP zone flags (`zone_today` / `zone_tomorrow`). Built for external displays/controllers such as a thermostat.

### `GET /api/battery`

Battery + decision snapshot, refreshed every evaluation cycle (RAM-only, no SD writes):

```json
{
  "state": "charging",            // "charging" | "discharging" | "idle" | "unknown"
  "soc_percent": 52.0,
  "soc_wh": 9330.0,
  "capacity_wh": 17900.0,
  "min_soc_percent": 10.0,
  "control_backend": "classic",
  "charging_strategy": "economic",
  "current_price": 38.05,
  "charge_condition": "lowestprice_block_2 ... active",
  "discharge_condition": "Discharge allowed: ... surplus ...",
  "economic": {
    "marginal_price": 45.0,
    "threshold_quarter_price": 40.5,
    "basis": "stats",
    "round_trip_efficiency": 0.9,
    "charge_power_w": 2500.0,
    "charge_power_source": "measured"
  },
  "grid_demand": {
    "enabled": true,
    "hard_limit_w": 10000.0,
    "charge_target_w": 5000.0,
    "shaving": true,
    "quarter_avg_w": 3200.0,
    "quarter_remaining_s": 420,
    "month_peak_w": 7400.0
  },
  "timestamp": "2026-09-29T08:35:11"
}
```

Check `timestamp` for staleness — the value only updates while the SEUSS loop is alive.

## ESS Units

### Victron

| Setting               | Meaning                                                                                                                                                                                                                                                                                                                        |
|:----------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `use_vrm`             | Connect through the Victron VRM portal (needs a VRM user/password).                                                                                                                                                                                                                                                            |
| `ip_address`          | Local IP of the Victron. Required when `use_vrm` is off.                                                                                                                                                                                                                                                                       |
| `unit_id`             | VRM Portal ID (`Settings / VRM online portal / VRM Portal Id`). Required even when not using VRM.                                                                                                                                                                                                                             |
| `user`                | VRM portal email.                                                                                                                                                                                                                                                                                                             |
| `password`            | VRM portal password.                                                                                                                                                                                                                                                                                                          |
| `max_discharge_power` | Default `-1`. If you use `Limit inverter power` in the ESS menu, enter that value here; if no limit, leave `-1`. Example: `1000` limits discharge to 1000 W, `-1` = full power. On **VenusOS >= 3.50** SEUSS writes this ONCE (only if it was 0) and gates discharge per decision through the hub4 RAM override; on older firmware the register is toggled per decision. |
| `only_observation`    | Only use this ESS unit for statistics — no conditions are executed.                                                                                                                                                                                                                                                            |
| `enabled`             | This entry must be `enabled` to be used.                                                                                                                                                                                                                                                                                       |

### Charge/discharge switching (classic backend)

- **VenusOS >= 3.50:** per-decision gating runs through the hub4 **RAM overrides** (`/Overrides/Setpoint`, `/Overrides/MaxDischargePower`) — no SD writes for switching; the SD registers keep your values.
- **Older firmware:** the SD registers are toggled per decision (`Schedule/Charge/0/Day` 7/-7, `MaxDischargePower` value/0), written only on change.
- SEUSS **never** writes `/Settings/DynamicEss/*`. A leftover `DynamicEss/Mode=4` (from an older build) disables the classic "Scheduled charge levels" feature on VenusOS 3.7x — set Dynamic ESS to off once if that page shows *Inactive*.

### aWATTar

| Setting    | Meaning                                                                                                          |
|:-----------|:-----------------------------------------------------------------------------------------------------------------|
| `country`  | Location: `AT` or `DE`.                                                                                          |
| `fee`      | Supplier markup added to the base price. Percentage and/or fixed cents, e.g. `3% + 2.5` = 3 % of base + 2.5 ct; `2.5` = flat 2.5 ct. Leave empty for none. Final price = Base price + Fee. |
| `primary`  | Marks this market as the primary one (when enabled).                                                             |
| `enabled`  | This entry must be `enabled` to be used.                                                                         |

### Entso-e

| Setting      | Meaning                                                                                                                                                                                                |
|:-------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `api_token`  | Free token: register at https://transparency.entsoe.eu/ , email transparency@entsoe.eu with subject "Restful API access" (reply within ~3 working days), then create a token at https://transparency.entsoe.eu/usrm/user/myAccountSettings |
| `in_domain`  | Your in-domain EIC code — see https://www.entsoe.eu/data/energy-identification-codes-eic/eic-area-codes-map/                                                                                            |
| `out_domain` | Same as `in_domain`.                                                                                                                                                                                    |
| `fee`        | Supplier markup (see aWATTar `fee`). ENTSO-E itself has no fee — take it from the primary market (or, if ENTSO-E is primary, from the fallback market).                                                 |
| `primary`    | Marks this market as the primary one (when enabled).                                                                                                                                                    |
| `enabled`    | This entry must be `enabled` to be used.                                                                                                                                                                |

### Tibber

| Setting      | Meaning                                                                                                                                                                                                                                          |
|:-------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `api_token`  | Create a token at https://developer.tibber.com/settings/access-token (select scope "price").                                                                                                                                                    |
| `price_unit` | `energy` (default, spot prices), `total` (incl. taxes/fees) or `tax` (taxes/fees only).                                                                                                                                                          |
| `fee`        | Supplier markup (see aWATTar `fee`).                                                                                                                                                                                                            |
| `primary`    | Marks this market as the primary one (when enabled).                                                                                                                                                                                            |
| `enabled`    | This entry must be `enabled` to be used.                                                                                                                                                                                                        |

## Solar Forecast Providers

SEUSS can pull the solar forecast from one or more providers. Configure `solar_forecast_providers` in `config.json`.

| Setting                | Meaning                                                                    |
|:-----------------------|:---------------------------------------------------------------------------|
| `api_key`              | API key for this provider (e.g. Solcast).                                   |
| `resource_ids`         | Provider resource IDs, comma-separated (one per PV site).                    |
| `min_interval_minutes` | Minimum minutes between forecast fetches for this provider (default `90`).   |

## PV Panels

| Setting           | Meaning                                                                                              |
|:------------------|:-----------------------------------------------------------------------------------------------------|
| `locLat`          | Latitude.                                                                                            |
| `locLong`         | Longitude.                                                                                           |
| `angle`           | Panel angle: 0 (horizontal) … 90 (vertical).                                                         |
| `direction`       | Azimuth: `-180` = north, `-90` = east, `0` = south, `90` = west.                                     |
| `totPower`        | Installed peak power in **kWp** — the hardware ceiling. Used as a hard cap on each hour's forecast. |
| `total_area`      | Panel surface in **m²** (e.g. 10 modules × 1.7 m² = 17 m²). **Must be set** — if left at `0`, the forecast collapses to zero. |
| `efficiency`      | Module efficiency in **%** (typical 18–22). Multiplied with `total_area` to convert irradiance into Wh. |
| `damping_morning` | Morning adjustment, float 0…1, default `0`.                                                         |
| `damping_evening` | Evening adjustment, float 0…1, default `0`.                                                         |
| `horizon`         | Season-correct horizon shading: obstruction silhouette as `[[azimuth_deg, elevation_deg], ...]`. Empty `[]` = open sky. See below. |
| `horizon_residual`| Share of the forecast kept when the sun is behind an obstruction (diffuse light). Percent, default `15`. |
| `enabled`         | This entry must be `enabled` to be used.                                                            |

### Horizon shading (season-correct)

A fixed `damping_evening` can't tell seasons apart: a tree shading the array on low-sun autumn afternoons does nothing in summer. The `horizon` profile models the real geometry — SEUSS computes the sun's elevation/azimuth per forecast hour (NOAA, no network) and compares it to your silhouette.

```json
"horizon": [[120, 0], [180, 8], [210, 8], [240, 25], [280, 25], [320, 0]],
"horizon_residual": 15
```

Reads as: *open sky from the east up to 180°; a hill to the south blocking everything below ~8°; a tree in the southwest blocking everything below 25° between 240° and 280°; open sky from 320°.*

Measure once from the panel position: a compass app for the azimuth, an inclinometer for the treetop/ridge elevation. Rough values are fine — linear interpolation smooths the rest. Hours behind the silhouette get `horizon_residual` % of the forecast; hours above it run the normal damping. Panels without a `horizon` entry behave as before.

## Smart Switches

### Shelly

| Setting    | Meaning                                                                                                                       |
|:-----------|:------------------------------------------------------------------------------------------------------------------------------|
| `ips`      | List of IP addresses, separated by `\|`. Prefix an IP with `!` to disable it without removing it, e.g. `"10.1.1.20 \| !10.1.1.21"`. |
| `user`     | Username for authentication (if needed).                                                                                       |
| `password` | Password (can be base64-encoded).                                                                                              |
| `enabled`  | Must be `true` to use this entry.                                                                                              |

### Tasmota

| Setting    | Meaning                                                                                                                       |
|:-----------|:------------------------------------------------------------------------------------------------------------------------------|
| `ips`      | List of IP addresses, separated by `\|`. Prefix an IP with `!` to disable it, e.g. `"10.1.1.30"`.                               |
| `user`     | Username for authentication.                                                                                                   |
| `password` | Password (can be base64-encoded).                                                                                              |
| `enabled`  | Must be `true` to use this entry.                                                                                              |

### Fritz

| Setting    | Meaning                                                                                                                                                     |
|:-----------|:------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ips`      | List of IP addresses, separated by `\|`. Prefix an IP with `!` to disable it, e.g. `"192.168.178.1 \| !10.1.1.23"`.                                          |
| `ains`     | AINs (Actor IDs). Commas between AINs, `\|` between IPs, e.g. `"1234,3443,2333 \| 1234,4456,7866,3421"`.                                                       |
| `user`     | Username for authentication.                                                                                                                                |
| `password` | Password (can be base64-encoded).                                                                                                                           |
| `enabled`  | Must be `true` to use this entry.                                                                                                                           |

### RemoteGPIO

| Setting | Meaning                                                                                             |
|:--------|:----------------------------------------------------------------------------------------------------|
| `pins`  | GPIO pin numbers, comma-separated per IP and pipe-separated between IPs, e.g. `"17,18 \| 21 \| 20"`. |

### Per-IP override (all switch types)

By default every IP uses the global `number_of_lowest_prices_for_switching` and `switching_block_minutes`. Two optional pipe-separated lists override this per IP:

| Setting                 | Meaning                                                                                                                                              |
|:------------------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `lowest_prices_per_ip`  | Pipe-separated, aligned with the **active** IPs (excluding any prefixed with `!`). Each entry = cluster count for that IP; empty = global default. Example `"8\|4\|"`. |
| `block_minutes_per_ip`  | Pipe-separated, same alignment. Each entry = cluster length in minutes; empty = global default. Example `"60\|30\|"`.                                   |

When **any** entry uses one of these, all switches are evaluated per IP — the "switch them all together" logic only runs when no override is set anywhere.

---

# Statistics page

The `/stats` route is a multi-tab dashboard with daily, 7-day, monthly and yearly aggregations.

## Tabs

**Today / Yesterday / 7 Days / Month / Year** — same tiles for the selected range. Today updates live; the other tabs refresh on page reload.

## Tiles

| Tile                  | Meaning                                                                                                                                    |
|:----------------------|:-------------------------------------------------------------------------------------------------------------------------------------------|
| **House Consumption** | Wh consumed by AC loads.                                                                                                                    |
| **Grid Import / Export** | Energy imported from / exported to the grid.                                                                                             |
| **PV Production**     | Total PV yield.                                                                                                                             |
| **Battery Charged / Discharged** | Wh in / out of the battery.                                                                                                      |
| **Cycles**            | `charge_wh / battery_capacity_wh`. Capacity is auto-detected from the Victron battery monitor.                                             |
| **RTE**               | Round-trip efficiency (`discharge / charge × 100`). Shows `--` if the range drained more than it charged. Healthy LFP packs: ~92–96 % over Month/Year. |
| **Loss**              | Inverter / wiring loss over the range (Wh).                                                                                                 |
| **Imbalance (signed)**| `input − usable` without the `max(…, 0)` clamp. Positive = normal (equals Loss); negative points at a missing source (e.g. a PV inverter not registered with the GX) or a sensor sign issue. |
| **Grid Cost**         | Cost of the grid energy used in the range (stored in cents, shown in €).                                                                     |
| **Skip Counters**     | How often each abort condition (Solar / Battery-range / Overnext / Expensive-phase / SOC-target) skipped a charge.                            |

## Live updates

The Today tab uses the same WebSocket as the home page: Consumption / Grid / Grid Export / PV / Battery Charge / Battery Discharge / Cost / Loss / Imbalance update without a reload. Cycles, RTE and skip counters refresh on reload.

## Today's Hourly Energy Balance

Below the comparison table, a per-hour breakdown of today's Loss and Imbalance shows *when* the balance went off — a steady sensor offset appears in every hour, a one-off event (e.g. inverter standby at night) only in those hours. Empty hours are hidden.

## Solar Forecast

When `use_solar_forecast_to_abort` is on (or PV panels are configured), the stats page shows the adjusted Open-Meteo forecast used by the abort logic. **Forecast Today** = `measured PV so far + adjusted forecast for the rest of the day`; **Adjustment Factor** = EWMA of recent actual-vs-forecast (clipped to [0.2, 2.0]); `1.00` = on target, `<1.0` = consistently below forecast, `>1.0` = better than forecast. SEUSS multiplies every raw forecast by this factor — what you see is what the conditions use.

## History retention

| Setting                       | Meaning                                                                                                                                    |
|:------------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------|
| `stats_history_retention_days`| Days of per-day history to keep. Default `400` (a full year-over-year plus a month buffer). `0` = no cleanup.                               |

---

## Log levels

### `ERROR`

Something failed that hinders a specific operation. The app keeps running at reduced functionality, but these should be investigated promptly.

### `WARN`

Something unexpected happened; the app continues normally. Worth fixing before it escalates.

### `INFO`

Significant normal events. The default level — a summary of the app's normal behaviour.

### `DEBUG`

Detailed messages for troubleshooting (variables, error codes, …). Verbose.

## Inspiration

The idea came from @christian1980nrw's project, and this is my first Victron Venus OS project — I adopted some approaches from the projects below. For very small systems the bash-script approach is probably better.

##### Thanks for passing on the knowledge:

- [Spotmarket-Switcher](https://github.com/christian1980nrw/Spotmarket-Switcher)
- [dynamic-ess](https://github.com/tfranssen/dynamic-ess)
