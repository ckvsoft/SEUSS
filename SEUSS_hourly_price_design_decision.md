## Design Decision: Hourly Prices as the Core Decision Unit

### Overview

SEUSS intentionally performs **charging and discharging decisions based on hourly prices**, even when a spot market provides higher-resolution price data (e.g. 15-minute prices from ENTSO-E or Tibber).

This is a **conscious architectural decision** to ensure consistent, realistic, and comparable behavior across all supported spot markets and ESS systems.

---

### Market Data Normalization

Currently supported markets provide prices with different temporal resolutions:

- **aWATTar** → hourly prices (fixed for the entire hour)
- **ENTSO-E** → 15-minute prices
- **Tibber** → 15-minute prices

To achieve uniform behavior, SEUSS **normalizes all market data to hourly prices** before any charging or discharging logic is applied.

For markets with 15-minute prices, the four values per hour are aggregated into a single **representative hourly price** using a deterministic, commercially rounded method.

This ensures that:

- ENTSO-E and Tibber prices are **semantically equivalent** to aWATTar prices
- no provider gains an artificial advantage due to higher resolution
- price comparisons remain predictable and fair

---

### Why SEUSS Does Not Optimize on 15-Minute Prices

Although higher-resolution prices may appear more precise, directly optimizing on 15-minute slots introduces several fundamental problems:

#### 1. Energy storage systems operate on hour-scale windows

Charging and discharging are **continuous physical processes**.  
Frequent switching based on 15-minute fluctuations:

- increases wear on hardware
- leads to unstable control behavior
- does not reflect real-world ESS operating constraints

Hourly decision windows provide the necessary stability.

---

#### 2. Minimum-price selection becomes misleading

Example (15-minute prices within one hour):

```
[5, 30, 30, 30]
```

Selecting the minimum price (5) would classify this hour as “cheap”, even though **75% of the hour is expensive**.

Hourly aggregation avoids this distortion by representing the **entire hour**, not short outliers.

---

#### 3. Charging window semantics break at sub-hour resolution

At hourly resolution:

```
4 cheapest prices = 4 hours of charging
```

At 15-minute resolution:

```
4 cheapest prices = 1 hour total,
possibly scattered across the entire day
```

This destroys the concept of **contiguous charging or discharging periods**, which is essential for meaningful ESS control.

---

### Design Principle

> **Higher-resolution price data may improve the accuracy of an hourly price,  
> but it must not change the decision unit itself.**

SEUSS optimizes **hours**, not individual time slots.

---

### Conclusion

Using hourly prices is not a limitation but a **deliberate abstraction layer**:

- it aligns all markets to the same semantic level
- it reflects real ESS operating behavior
- it preserves the meaning of “cheapest” and “most expensive” periods
- it avoids misleading optimization based on short-term price spikes

For these reasons, SEUSS will continue to base all charging and discharging logic on **hourly prices**.
