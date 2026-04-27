# SEUSS Backlog

Ideas and known small issues. Updated for fix6 / Statistics Part 1.

## Statistics Part 2

`/stats` currently only has Today / Yesterday tabs functional;
7 Days / Month / Year are stubbed. Lifting them needs:

  * **Longer history retention.** The `*_by_day` dicts in StatsManager
    grow unbounded right now -- nothing trims old entries. Decide on
    retention (e.g. 13 months for year-comparisons) and add cleanup
    in save_day().
  * **Hourly granularity per day** for the "Generation vs Consumption"
    intraday chart in the original mockup. Currently we only retain
    `hourly_wh` for the *current* hour. Need a `hourly_wh_by_day`
    dict (date -> [24]) populated from save_hour().
  * **SOC time-series.** Today only the last value is in WS. Add a
    ringbuffer (96 samples/day at 15-min resolution) that resets at
    midnight.
  * **Forecast vs Actual.** Persist the OpenMeteo per-hour forecast
    at the moment it's computed, then compare against measured at the
    end of each hour. Both go into a date-keyed dict.
  * **Charge vs Discharge split.** Today we only track absolute
    throughput. Splitting needs the BATTERY_POWER sign convention
    confirmed -- positive = discharge in Victron is the assumption,
    not yet validated in the live system.
  * **Cycles & RTE.** Once Charge/Discharge are split, cycles =
    daily_charge_wh / battery_capacity_wh (capacity from essunit),
    RTE = daily_discharge_wh / daily_charge_wh.
  * **Grid Export accumulator.** Needs the negative-flow side of
    AC_GRID_POWER. Symmetric to `daily_grid_wh` (positive flow).
  * **Skip counters** for `use_solar_forecast_to_abort` and
    `skip_charge_when_battery_sufficient` -- show how often each
    abort condition actually fired.

## Efficiency / Loss refactor (Part 1.5)

The momentary efficiency calculation in
`PowerDataHandler.process_data()` has known issues:

  * `last_loss_efficiency` "sticky" caching gives a stale view of the
    system -- once loss > 0 fires, the value is held until the next
    loss > 0 frame, which can be hours.
  * Battery charging counted as `usable_energy` -- hides charging
    losses entirely.
  * Inverter standby losses get attributed to specific instants
    rather than averaged over the day.

Better approach: daily energy balance in Wh:

    energy_in  = pv_wh + max(grid_wh, 0) + discharge_wh
    energy_out = consumption_wh + max(export_wh, 0)
    battery_balance = charge_wh - discharge_wh
    daily_loss = energy_in - energy_out - battery_balance
    daily_efficiency = energy_out / (energy_in - battery_balance)

Requires Charge/Discharge split (Part 2 dependency). Battery internal
losses remain invisible because we can't measure DC before vs. after
the charger -- unless P_DC_inverter_Charger is populated by the
user's MQTT setup; the field exists but is not yet wired.

## OpenMeteo: total_area + efficiency vs totPower

`total_area = 0` (the default) silently zeros the per-panel forecast.
Documented in the README tooltip in fix4. A future revision could
either remove total_area + efficiency from the schema and derive
everything from totPower (kWp), or change the default for new installs
so it produces a sensible forecast without the user having to know
the m^2 of their panels. Both declined during fix4 in favour of
"docs only" so existing calibrated setups don't shift.

## Naming: `current_hour_solar_yield`

Field in `solar/solardata.py` named `current_hour_solar_yield` but
populated in `core/seusscore.py:get_total_solar_yield` with the
day-so-far inverter total. The name is misleading; the value is
correct. Rename to `today_yield_so_far_wh` at next major refactor.

## D-Bus power consumption

`powerconsumption/powerconsumptiondbus.py` exists as a stub but is
not wired into `PowerConsumptionManager` (which only recognises
`type == "mqtt"`). README mentions "Direct control with D-BUS is in
the works". When wired up, the DBus implementation needs to honour
the new `update(..., pv_power=)` parameter from fix6.

## solar.efficiency duplicates solar.adjustment_factor

Two stats keys hold the same info at different scales:

  * `solar.adjustment_factor` -- e.g. 0.85
  * `solar.efficiency`        -- e.g. 85.0  (= adjustment_factor * 100)

Both written together in `solar/openmeteo.py` after each learning
step. Could probably consolidate.
