## Design Decision: Configurable Cluster Lengths over 15-min Quarters

### Overview

SEUSS originally based **all charging and discharging decisions on hourly prices**, even when a spot market delivered finer-grained data. With the introduction of 15-minute spot prices on European day-ahead markets in 2025, that hard-wired hour scope became too restrictive — but blindly optimizing on every individual 15-minute slot turned out to be just as bad. The current model keeps the spirit of the original design (stable, contiguous, hardware-friendly switching windows) while making the window length itself a per-deployment configuration.

This is a **conscious architectural decision** to ensure consistent, realistic, and comparable behavior across all supported spot markets, ESS systems, and tariff models.

---

### Market Data — quarter-resolution internally

Currently supported markets provide prices with different temporal resolutions:

- **aWATTar** → hourly prices (fixed for the entire hour)
- **ENTSO-E** → native 15-minute prices since 2025 (PT15M); legacy hourly responses are still tolerated and split into 4 identical quarters with a warning
- **Tibber** → 15-minute prices when available, hourly otherwise (auto-detected)

Internally SEUSS now normalises **all market data to 15-minute quarters**, so the rest of the system never has to care about the source resolution. Awattar's hourly entries are split into four identical quarters, ENTSO-E's PT15M is used as-is, and ENTSO-E's PT60M legacy data is split with a `WARN`-level log entry.

---

### Tariff resolution — billing model decides aggregation

Most Austrian retail contracts (Awattar Hourly, Tibber default tariff) bill **per hour** even though the underlying spot market may publish 15-minute prices. For these users, optimising on quarter-shifted clusters would not match the bill — they pay the hourly average regardless. The `tariff_resolution` config setting handles this:

- **`hourly`** (default) — the four quarter prices of an hour are averaged on data load. Cluster selection sees a flat hourly price profile and lands clusters on full hours, just like the pre-2025 SEUSS.
- **`quarterly`** — quarter prices are kept as-is. Cluster selection uses sliding-window placement and may start clusters at `:15`, `:30` or `:45` of an hour to capture a real sub-hour low or high.

Default is `hourly` because that matches the most common Austrian retail contract.

---

### Cluster model — N clusters of M minutes each

Charging and discharging decisions are now made over **clusters**, not individual quarters. A cluster is a contiguous run of quarter-hour items of a configured length.

```
charging:    N_charge     clusters of charging_block_minutes    minutes
discharging: N_discharge  clusters of discharging_block_minutes minutes
switching:   N_switch     clusters of switching_block_minutes   minutes
```

Where:
- `N_*` is the corresponding `number_of_*_prices_*` config value (integer mode = literal cluster count, decimal mode = "all clusters above/below X × day-average")
- `*_block_minutes` is the cluster length, snapped to multiples of 15

Cluster selection is greedy and disjoint per day:

1. **Charge:** rank all sliding-window candidate clusters by price, take the N cheapest disjoint clusters.
2. **Discharge:** same, but expensive-first; respects already-selected charge clusters via an exclusion list so charging and discharging never overlap.
3. **Optional gap fill (`fill_gaps_with_short_clusters`)**: when sliding-window placement leaves a gap shorter than `block_minutes` between two selected clusters, fill it with a shorter discharge cluster (15 / 30 / 45 min). This keeps the chart contiguous when totals add up to 24 h.

The selection runs separately per local day, so today's cluster choices never change when tomorrow's day-ahead data arrives at noon — important because `use_second_day` may extend the data window mid-day.

---

### Why not optimise on every individual 15-minute slot

The argument from the original design note still applies in spirit:

#### 1. Hardware stability

Charging and discharging are continuous physical processes. Switching the inverter every 15 minutes increases wear on hardware (relays, contactors, battery cycle counts) and leads to unstable control behaviour. Cluster lengths default to 60 minutes; users who want shorter cycles set `*_block_minutes` to 30 or 15 explicitly.

#### 2. Sub-hour cluster lengths are opt-in

The old example still holds:

```
quarter prices in one hour: [5, 30, 30, 30]
```

Picking only the `5` would treat one tiny slot as "cheap" while 75 % of the hour is expensive. With the cluster model, `charging_block_minutes=60` means the algorithm sees this as a single 23.75-cent cluster — not cheap. If the user **wants** sub-hour optimisation, they explicitly set `charging_block_minutes=15`. The behaviour is then transparent.

#### 3. Hard cap is per-quarter, but cluster length is per-config

A separate concern: the hard cap (`charging_price_hard_cap`) is checked per quarter, not per cluster average. So a single expensive 15-minute slot inside an otherwise cheap 60-minute cluster still pauses charging for that quarter — but the surrounding cheap quarters continue. The chart paints the blocked quarter olive instead of green so the user can tell at a glance.

This decouples two concepts:
- **Cluster length** is about hardware-friendly switching cadence ("how long do I run this once started?")
- **Hard cap** is about price safety ("never pay more than X regardless")

---

### Design Principle

> **Higher-resolution price data improves the accuracy of price decisions,  
> but the user — not the resolution — decides how long a switching cycle should be.**

SEUSS optimises **clusters of configurable length**, not individual quarters by default.

---

### Migration from older configs

Configs from pre-2025 SEUSS continue to work without intervention:

- Missing `*_block_minutes` keys default to 60 (= the old hourly behaviour)
- Missing `tariff_resolution` defaults to `hourly`
- Missing `fill_gaps_with_short_clusters` defaults to `true`
- Missing `number_of_lowest_prices_for_switching` defaults to `0`, which falls back to `number_of_lowest_prices_for_charging`

The first start after the upgrade rewrites the config file with the new keys filled in, so subsequent edits in the web UI see all options.

---

### Summary

The cluster model is a **deliberate abstraction layer** between the raw 15-minute spot data and the actual switching decisions:

- it aligns all markets to a uniform 15-minute internal representation
- it reflects real ESS operating behaviour through the cluster length setting
- it gives hourly-tariff users (Awattar, Tibber default) the original hour-aligned behaviour for free via `tariff_resolution: hourly`
- it lets quarterly-tariff users opt in to true sub-hour optimisation
- it preserves predictable, contiguous charging and discharging windows where they make sense, while letting the hard cap cut single expensive quarters out
