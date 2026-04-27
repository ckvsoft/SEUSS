#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2025 Christian Kvasny chris(at)ckvsoft.at
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#  THE SOFTWARE.
#
#  Project: [SEUSS -> Smart Ess Unit Spotmarket Switcher
#

from datetime import datetime, timedelta, timezone

from core.config import Config
from core.log import CustomLogger
from core.timeutilities import TimeUtilities
from core.utils import Utils
from design_patterns.factory.generic_loader_factory import GenericLoaderFactory


# =============================================================================
# PriceBlock -- a contiguous run of N quarter-items treated as one unit
# =============================================================================
# A PriceBlock represents a charging or discharging window: e.g. "the
# 60 minutes between 14:30 and 15:30, average price 8.5 ct/kWh".
#
# It is built from a list of consecutive 15-minute items. The block's
# start/end are derived from its first and last item; the average price
# is computed as integer-millicent floor-division (consistent with the
# rest of the codebase, which treats item.price as int millicents).
#
# The block exposes the same interface points that conditions.py and
# seussweb.py need: get_start_datetime, get_end_datetime, get_price,
# is_active_now, is_expired, contains.
# =============================================================================

class PriceBlock:
    """A contiguous run of items, treated as a single charge/discharge unit."""

    def __init__(self, items, block_type="charge"):
        if not items:
            raise ValueError("PriceBlock requires at least one item")
        self._items = list(items)
        self._block_type = block_type
        # Cache integer-millicent average. We use floor division to stay
        # in the integer domain, matching how individual item prices are
        # stored.
        total = sum(int(it.price) for it in self._items)
        self._avg_price = total // len(self._items)

    # -- identity / time bounds ---------------------------------------------

    def get_start_datetime(self, localtime=False):
        start = self._items[0].get_start_datetime(localtime=False)
        if localtime:
            return TimeUtilities.convert_utc_to_local(start)
        return start

    def get_end_datetime(self, localtime=False):
        # The last item's endtime already has the -1s offset baked in by
        # Item.__init__. We add it back so the block's "end" is the
        # exclusive end of the last quarter (i.e. the start of the next
        # one). Callers that want an inclusive end can use
        # get_end_datetime(localtime=False) - timedelta(seconds=1).
        end = self._items[-1].get_end_datetime(localtime=False)
        if end is None:
            return None
        end_exclusive = end + timedelta(seconds=1)
        if localtime:
            return TimeUtilities.convert_utc_to_local(end_exclusive)
        return end_exclusive

    def get_duration_minutes(self):
        return sum(it.get_duration_minutes() or 15 for it in self._items)

    # -- price --------------------------------------------------------------

    def get_avg_price(self, convert=True):
        """Average price across all member items. Integer-millicent by default."""
        if convert:
            return Utils.millicent_to_cent(self._avg_price)
        return self._avg_price

    def get_items(self):
        return list(self._items)

    def get_block_type(self):
        return self._block_type

    # -- queries ------------------------------------------------------------

    def is_active_now(self):
        """True if `now` (UTC) lies within this block's time span."""
        now = datetime.now(timezone.utc)
        return self.contains(now)

    def contains(self, when):
        """True if `when` (tz-aware datetime) falls inside this block."""
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        start = self.get_start_datetime()
        end = self.get_end_datetime()
        if start is None or end is None:
            return False
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return start <= when < end

    def is_expired(self, check_time=True):
        """True if the block lies entirely in the past."""
        end = self.get_end_datetime()
        if end is None:
            return False
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return end <= datetime.now(timezone.utc)

    def overlaps(self, other):
        """True if this block shares any time with another block."""
        if not isinstance(other, PriceBlock):
            return False
        a_start = self.get_start_datetime()
        a_end = self.get_end_datetime()
        b_start = other.get_start_datetime()
        b_end = other.get_end_datetime()
        return a_start < b_end and b_start < a_end

    # -- repr ---------------------------------------------------------------

    def describe(self, localtime=True):
        """Short, log-friendly description: '14:30-15:30 avg 8.50 Cent/kWh'."""
        start = self.get_start_datetime(localtime=localtime)
        end = self.get_end_datetime(localtime=localtime)
        if isinstance(start, datetime):
            start_str = start.strftime("%H:%M")
        else:
            start_str = str(start).split(' ')[-1] if start else "?"
        if isinstance(end, datetime):
            end_str = end.strftime("%H:%M")
        else:
            end_str = str(end).split(' ')[-1] if end else "?"
        return f"{start_str}-{end_str} avg {self.get_avg_price(True)} Cent/kWh"

    def describe_quarters(self, localtime=True):
        """Per-quarter detail for DEBUG logs: '14:30=8.4 14:45=8.5 ...'."""
        parts = []
        for it in self._items:
            t = it.get_start_datetime(localtime=localtime)
            if isinstance(t, datetime):
                t_str = t.strftime("%H:%M")
            else:
                t_str = str(t).split(' ')[-1] if t else "?"
            parts.append(f"{t_str}={it.get_price(True)}")
        return " ".join(parts)


# =============================================================================
# Itemlist -- container of quarter-resolution Items + block selection logic
# =============================================================================

class Itemlist:
    def __init__(self, items=None):
        self._item_list = items if items is not None else []
        self._config = Config()
        self._logger = CustomLogger()

        self.primary_market_name = next(
            (m['name'] for m in self._config.markets
             if m.get('primary', False) and m.get('enabled', False)),
            "DefaultMarket"
        )
        self.failback_market_name = next(
            (m['name'] for m in self._config.markets
             if not m.get('primary', False) and m.get('enabled', False)),
            "DefaultFailbackMarket"
        )
        self.current_market_name = self.primary_market_name

    # -- container basics ---------------------------------------------------

    def add_item(self, item):
        self._item_list.append(item)

    @staticmethod
    def create_item_list(items=None):
        return Itemlist(items)

    def get_current_list(self):
        return self._item_list

    def get_item_count(self):
        return len(self._item_list)

    def remove_expired_items(self):
        self._item_list = [it for it in self._item_list if not it.is_expired()]

    def remove_all_items(self):
        self._item_list.clear()

    # -- price queries (item-level, used by web UI and conditions.info) ----

    def get_current_price(self, convert=False):
        now = datetime.now(timezone.utc)
        for item in self._item_list:
            start = item.get_start_datetime()
            end = item.get_end_datetime()
            if start is None or end is None:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if start <= now <= end:
                return item.get_price(convert)
        self._logger.log.error("get_current_price -> Item not found.")
        return None

    def get_average_price_by_date(self, convert=False):
        """Average prices for today's items and tomorrow's items."""
        today_items, tomorrow_items = [], []
        for item in self._item_list:
            bucket = self.is_today_or_tomorrow(item)
            if bucket == 'today':
                today_items.append(item)
            elif bucket == 'tomorrow':
                tomorrow_items.append(item)

        def calc(items):
            if not items:
                return None
            total = sum(int(it.get_price(False)) for it in items)
            avg_mc = total // len(items)
            if convert:
                return float(Utils.millicent_to_cent(avg_mc))
            return avg_mc

        return calc(today_items), calc(tomorrow_items)

    def is_today_or_tomorrow(self, item):
        today_start = TimeUtilities.get_now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_end = today_start.replace(hour=23, minute=59, second=59)
        tomorrow_start = today_start + timedelta(days=1)
        item_start = TimeUtilities.convert_utc_to_local(
            item.get_start_datetime(), False
        )
        if item_start is None:
            return None
        if today_start <= item_start <= today_end:
            return 'today'
        if tomorrow_start <= item_start:
            return 'tomorrow'
        return None

    # -- UI helper: aggregate quarter prices to hourly buckets --------------
    # The web SVG chart expects 24 hourly entries per day. With quarter
    # items in the list, we average each hour's 4 quarters back to a
    # single hourly value just for display. The decision logic does NOT
    # use this -- it operates on the underlying quarter items directly.
    # -----------------------------------------------------------------------

    @staticmethod
    def get_price_hour_lists(item_list):
        """
        Aggregate quarter items to hourly averages for the UI chart.
        Returns: today_data, today_hours, tomorrow_data, tomorrow_hours
        where *_data is {hour_int: avg_cent_float}.
        """
        sorted_items = sorted(item_list, key=lambda x: x.get_start_datetime())

        today = datetime.today().date()
        today_buckets = {}      # hour -> [prices]
        tomorrow_buckets = {}

        for item in sorted_items:
            local = item.get_start_datetime(localtime=True)
            if not local:
                continue
            try:
                date_part, time_part = local.split(' ')
                start_date = datetime.strptime(date_part, "%Y-%m-%d").date()
                start_hour = int(time_part.split(':')[0])
            except (ValueError, AttributeError):
                continue

            price = float(item.get_price(convert=True))
            target = today_buckets if start_date <= today else tomorrow_buckets
            target.setdefault(start_hour, []).append(price)

        def avg_dict(buckets):
            return {h: round(sum(prices) / len(prices), 4)
                    for h, prices in buckets.items()}

        today_data = avg_dict(today_buckets)
        tomorrow_data = avg_dict(tomorrow_buckets)
        return (
            today_data, list(today_data.keys()),
            tomorrow_data, list(tomorrow_data.keys())
        )

    @staticmethod
    def get_quarter_prices(item_list, target_date):
        """
        Per-quarter prices for the given local date.
        Returns: dict {(hour, quarter_index): price_cent_float}.

        The chart uses this to evaluate the hard cap on a per-quarter
        basis (instead of the hourly average), so a 11:00 quarter at
        16.8 ct shows as grey while the 11:15 quarter at 14.5 ct
        (in a charge cluster) shows as green -- without the misleading
        impression that "the same hour" is half over and half under cap.
        """
        out = {}
        for item in item_list:
            local = item.get_start_datetime(localtime=True)
            if not local:
                continue
            try:
                date_part, time_part = local.split(' ')
                start_date = datetime.strptime(date_part, "%Y-%m-%d").date()
                hh, mm = time_part.split(':')[:2]
                start_hour = int(hh)
                start_minute = int(mm)
            except (ValueError, AttributeError):
                continue
            if start_date != target_date:
                continue
            q = start_minute // 15
            out[(start_hour, q)] = float(item.get_price(convert=True))
        return out

    # =====================================================================
    # Block selection -- the new core API for charging/discharging
    # =====================================================================

    def get_lowest_charging_blocks(self, count_or_pct, block_minutes=60,
                                   item_list=None):
        """
        Find the cheapest charging blocks.

        - Integer `count_or_pct` >= 1: select up to N disjoint sliding
          blocks of `block_minutes` length, lowest avg price first.
        - Float `count_or_pct` in (0, 1): "all blocks whose avg price
          is below count_or_pct * day_average". Disjoint Greedy.
        - Float `count_or_pct` >= 1.0: legacy quirk -- treat as integer
          ceiling. Mirrors the old config behaviour where 1.0 meant
          "1 cheapest" (not "100% of average").

        Returns a list of PriceBlock, sorted by start time.
        """
        return self._select_blocks(
            count_or_pct, block_minutes,
            item_list=item_list,
            block_type="charge",
            reverse=False,
        )

    def get_highest_discharging_blocks(self, count_or_pct, block_minutes=60,
                                       item_list=None, exclude_blocks=None,
                                       fill_gaps=False):
        """
        Find the most expensive discharging blocks.

        Same parameter semantics as get_lowest_charging_blocks, but picks
        the highest-avg blocks. `exclude_blocks` lets the caller pass in
        already-selected charging blocks so discharging blocks don't
        overlap with them.

        fill_gaps: if True, after the regular full-length selection, fill
        any quarter-gaps (e.g. 30-min slivers between two charge blocks)
        with shorter discharge blocks (15/30/45-min). Use this to make
        8 charge + 16 discharge = 24h fully coloured even when sliding
        charge blocks leave gaps.
        """
        return self._select_blocks(
            count_or_pct, block_minutes,
            item_list=item_list,
            block_type="discharge",
            reverse=True,
            exclude_blocks=exclude_blocks,
            fill_gaps=fill_gaps,
        )

    def get_future_high_blocks_until_next_low(self, discharge_blocks,
                                              charge_blocks):
        """
        Of the given discharge blocks, return only those that lie BEFORE
        the next non-expired charge block. Used by the surplus calculation
        in conditions.py: we only need to reserve battery capacity for
        the expensive period until we can charge again cheaply.

        If no future charge block exists, all non-expired discharge blocks
        are returned (we'll have to ride out an indefinite expensive run).
        """
        now = datetime.now(timezone.utc)

        # Find the earliest future charge block that hasn't expired yet.
        next_charge_start = None
        for cb in charge_blocks or []:
            if cb.is_expired():
                continue
            cb_start = cb.get_start_datetime()
            if cb_start.tzinfo is None:
                cb_start = cb_start.replace(tzinfo=timezone.utc)
            # We only care about charge blocks that start in the future
            # (or are currently active -- in which case there's no
            # "expensive run to ride out", so we skip them).
            if cb_start <= now:
                continue
            if next_charge_start is None or cb_start < next_charge_start:
                next_charge_start = cb_start

        future_high = []
        for db in discharge_blocks or []:
            if db.is_expired():
                continue
            if next_charge_start is None:
                future_high.append(db)
                continue
            db_start = db.get_start_datetime()
            if db_start.tzinfo is None:
                db_start = db_start.replace(tzinfo=timezone.utc)
            if db_start < next_charge_start:
                future_high.append(db)

        return future_high

    # ------------------------------------------------------------------
    # Internal: the actual sliding-window block search
    # ------------------------------------------------------------------

    def _select_blocks(self, count_or_pct, block_minutes,
                       item_list=None, block_type="charge",
                       reverse=False, exclude_blocks=None,
                       fill_gaps=False):
        """
        Select N blocks from the items.

        Parameters
        ----------
        count_or_pct : int or float
            int -> exact number of blocks, e.g. 8 = "8 cheapest 60-min runs"
            float -> threshold against day average, e.g. 0.85 = "all under 85%"
        block_minutes : int
            Length of each block in minutes (must be a multiple of 15).
        item_list : list[Item] or None
            Items to consider. Defaults to self._item_list.
        block_type : "charge" or "discharge"
            Tags the resulting PriceBlock objects.
        reverse : bool
            False = pick cheapest (charge), True = pick most expensive (discharge).
        exclude_blocks : list[PriceBlock] or None
            Already-selected blocks whose time spans must not be reused.
            Typically pass charge_blocks here when selecting discharge.
        fill_gaps : bool
            If True (only meaningful for discharge), after the regular
            full-length selection, fill any remaining quarter-gaps within
            the day with shorter blocks (15/30/45-min). This is the user
            opt-in to make 8 charge + 16 discharge = 24h fully coloured
            even when sliding charge blocks leave 30-min gaps.
        """
        if item_list is None:
            item_list = self._item_list
        if not item_list:
            return []

        # 1. Sort items chronologically.
        sorted_items = sorted(item_list, key=lambda x: x.get_start_datetime())

        # 2. Determine block size in quarters.
        block_quarters = max(1, int(round(block_minutes / 15)))

        # 3. Decide selection mode from count_or_pct.
        is_integer_count = isinstance(count_or_pct, int) or (
            isinstance(count_or_pct, float) and count_or_pct.is_integer()
        )

        # 4. Group into per-day item lists.
        per_day = {}  # date(local) -> list of items
        for it in sorted_items:
            local = TimeUtilities.convert_utc_to_local(
                it.get_start_datetime(), False
            )
            if local is None:
                continue
            per_day.setdefault(local.date(), []).append(it)

        # 5. Per-day selection. Block candidates are SLIDING-WINDOW --
        #    every starting quarter is considered (00:00, 00:15, 00:30,
        #    00:45, 01:00, ..., last possible). Each candidate is exactly
        #    block_quarters long. Greedy picks N disjoint candidates --
        #    so a 60min block can start at 14:45 and end at 15:45 if
        #    that's where the cheapest 60min run sits. Whole hours are
        #    not enforced.

        all_selected = []

        for day_date, day_items in sorted(per_day.items()):
            if len(day_items) < block_quarters:
                continue

            candidates = self._build_sliding_candidates(
                day_items, block_quarters
            )
            if not candidates:
                continue

            if is_integer_count:
                # Integer mode: user said "exactly N blocks". Take the N
                # cheapest/most-expensive disjoint sliding windows.
                candidates.sort(key=lambda c: c[0], reverse=reverse)
                target_count = max(0, int(count_or_pct))
                selected = self._greedy_disjoint(
                    candidates, target_count, block_quarters,
                    exclude_blocks=exclude_blocks
                )
            else:
                # Decimal mode: "all blocks under (or over) pct * day_avg".
                # Same sliding-window candidates, threshold-filtered, then
                # greedy disjoint -- count is computed.
                pct = float(count_or_pct)
                day_total = sum(int(it.price) for it in day_items)
                day_avg = day_total // len(day_items)
                threshold = day_avg * pct
                if reverse:
                    qualifying = [c for c in candidates if c[0] > threshold]
                else:
                    qualifying = [c for c in candidates if c[0] < threshold]
                qualifying.sort(key=lambda c: c[0], reverse=reverse)
                selected = self._greedy_disjoint(
                    qualifying, len(qualifying), block_quarters,
                    exclude_blocks=exclude_blocks
                )

            # Phase 3: fill quarter-gaps with shorter blocks (opt-in).
            # When fill_gaps is True, the user explicitly wants the day
            # filled -- so we ignore the integer count limit here and
            # cover every leftover quarter we can. The result may have
            # MORE blocks than count_or_pct asked for; the extras are
            # all shorter than block_minutes and only sit in gaps.
            if fill_gaps and selected:
                used_quarters = set()
                for _, start_idx, window in selected:
                    used_quarters.update(
                        range(start_idx, start_idx + block_quarters)
                    )
                # Excluded spans from charge blocks must also be respected
                # while filling.
                gap_extra = self._fill_gaps_with_shorter(
                    day_items, used_quarters, block_quarters,
                    reverse=reverse, exclude_blocks=exclude_blocks,
                    max_to_add=None,
                )
                selected.extend(gap_extra)

            all_selected.extend(selected)

        # 6. Wrap into PriceBlock objects, sorted by start time.
        blocks = [PriceBlock(window, block_type=block_type)
                  for (_, _, window) in all_selected]
        blocks.sort(key=lambda b: b.get_start_datetime())
        return blocks

    @staticmethod
    def _fill_gaps_with_shorter(day_items, used_quarters, max_block_quarters,
                                reverse=False, exclude_blocks=None,
                                max_to_add=None):
        """
        After the regular full-length block selection, look for remaining
        runs of unused quarters within the day and cover them with shorter
        blocks (max_block_quarters - 1 down to 1 quarter).

        For discharge this means: a 30-min gap between two charge blocks
        becomes a single 30-min discharge block, so the day chart fills
        in completely instead of leaving a white sliver.

        Returns a list of (avg_price, start_idx, window) tuples to extend
        the caller's `selected`.

        max_to_add: if not None, stop once that many extra blocks were added.
        """
        # Build excluded-spans set (similar to _greedy_disjoint).
        excluded_spans = []
        if exclude_blocks:
            from datetime import timezone as _tz
            for blk in exclude_blocks:
                start = blk.get_start_datetime()
                end = blk.get_end_datetime()
                if start is None or end is None:
                    continue
                if start.tzinfo is None:
                    start = start.replace(tzinfo=_tz.utc)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=_tz.utc)
                excluded_spans.append((start, end))

        def quarter_in_excluded_span(idx):
            if not excluded_spans:
                return False
            from datetime import timezone as _tz
            t = day_items[idx].get_start_datetime()
            if t.tzinfo is None:
                t = t.replace(tzinfo=_tz.utc)
            for (s, e) in excluded_spans:
                if s <= t < e:
                    return True
            return False

        # Mark which quarters are "boundary" -- already selected by the
        # caller (used_quarters) or in an excluded span (= the other
        # block type). The fill step must only cover free quarters that
        # sit BETWEEN such boundaries -- i.e. small slivers that
        # sliding-window placement leaves behind. A free quarter in the
        # middle of a multi-hour open region (because the user asked
        # for fewer blocks than the day fits) must stay grey.
        n = len(day_items)
        boundary = set()
        for i in range(n):
            if i in used_quarters or quarter_in_excluded_span(i):
                boundary.add(i)

        # A free window qualifies as "neighbour gap" iff a boundary
        # quarter exists within (max_block_quarters - 1) positions on
        # BOTH sides. Open edges (start-of-day, end-of-day, or large
        # free regions) are not filled.
        reach = max(1, max_block_quarters - 1)

        def is_neighbour_gap(start_idx, length):
            left_boundary = any(
                (start_idx - 1 - d) in boundary
                for d in range(reach)
                if (start_idx - 1 - d) >= 0
            )
            right = start_idx + length
            right_boundary = any(
                (right + d) in boundary
                for d in range(reach)
                if (right + d) < n
            )
            return left_boundary and right_boundary

        added = []
        # Iterate from the largest possible shorter length down to 1.
        for shorter in range(max_block_quarters - 1, 0, -1):
            if max_to_add is not None and len(added) >= max_to_add:
                break

            # Build candidates of this shorter length, but only those
            # whose quarters are all currently unused AND not in any
            # excluded span AND qualify as neighbour gaps.
            candidates = []
            for i in range(n - shorter + 1):
                idxs = range(i, i + shorter)
                # Skip if any quarter is already used.
                if any(j in used_quarters for j in idxs):
                    continue
                # Skip if any quarter falls in an excluded charge span.
                if any(quarter_in_excluded_span(j) for j in idxs):
                    continue
                # Skip large open regions -- only fill neighbour gaps.
                if not is_neighbour_gap(i, shorter):
                    continue
                window = day_items[i:i + shorter]
                if not Itemlist._is_contiguous(window):
                    continue
                avg = sum(int(it.price) for it in window) // shorter
                candidates.append((avg, i, window))

            candidates.sort(key=lambda c: c[0], reverse=reverse)

            for avg, start_idx, window in candidates:
                if max_to_add is not None and len(added) >= max_to_add:
                    break
                idxs = set(range(start_idx, start_idx + shorter))
                if idxs & used_quarters:
                    continue
                added.append((avg, start_idx, window))
                used_quarters.update(idxs)

        return added

    @staticmethod
    def _build_sliding_candidates(items, block_quarters):
        """
        Build sliding-window candidates: every starting position is
        considered (0, 1, 2, ...). Used by decimal-percentage selection
        where we want the algorithm to find the genuinely best windows
        regardless of hour alignment.

        Returns list of (avg_price, start_idx, [items]).
        """
        candidates = []
        n = len(items)
        for i in range(n - block_quarters + 1):
            window = items[i:i + block_quarters]
            if not Itemlist._is_contiguous(window):
                continue
            avg = sum(int(it.price) for it in window) // block_quarters
            candidates.append((avg, i, window))
        return candidates

    @staticmethod
    def _is_contiguous(items):
        """True if items are consecutive 15min slots with no time gaps."""
        for i in range(1, len(items)):
            prev_end = items[i - 1].get_end_datetime()
            cur_start = items[i].get_start_datetime()
            if prev_end is None or cur_start is None:
                return False
            # endtime is start + duration - 1s, so the next start should
            # be exactly endtime + 1s.
            if (cur_start - prev_end).total_seconds() not in (1, 1.0):
                return False
        return True

    @staticmethod
    def _greedy_disjoint(candidates, target_count, block_quarters,
                         exclude_blocks=None):
        """
        Greedy selection: pick the best-priced candidate, mark its
        quarter indices as used, take the next-best that doesn't overlap
        used indices, repeat. Optionally exclude time spans of pre-existing
        blocks (used to keep discharging blocks away from charging ones).
        """
        used = set()
        # Pre-mark quarters that fall inside any excluded block's span.
        # We can't compare by index directly across days, so we use the
        # item's start time as the "key": any candidate window whose
        # any item starts inside an excluded block is rejected.
        excluded_spans = []
        if exclude_blocks:
            for blk in exclude_blocks:
                start = blk.get_start_datetime()
                end = blk.get_end_datetime()
                if start is None or end is None:
                    continue
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                excluded_spans.append((start, end))

        def overlaps_excluded(window):
            if not excluded_spans:
                return False
            for it in window:
                t = it.get_start_datetime()
                if t is None:
                    continue
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                for (s, e) in excluded_spans:
                    if s <= t < e:
                        return True
            return False

        selected = []
        for avg, start_idx, window in candidates:
            if len(selected) >= target_count:
                break
            indices = set(range(start_idx, start_idx + block_quarters))
            if indices & used:
                continue
            if overlaps_excluded(window):
                continue
            selected.append((avg, start_idx, window))
            used |= indices
        return selected

    # ----------------------------------------------------------------------
    # Logging helper
    # ----------------------------------------------------------------------

    def log_items(self):
        for item in self.get_current_list():
            self._logger.log.debug(
                f"Starttime: {item.get_start_datetime(True)}, "
                f"Endtime: {item.get_end_datetime(True)}, "
                f"Price: {item.price} Millicents pro kWh, "
                f"Price: {Utils.millicent_to_cent(item.price)} Cent pro kWh."
            )

    # ----------------------------------------------------------------------
    # Market-update orchestration (mostly unchanged from before)
    # ----------------------------------------------------------------------
    # Threshold when deciding whether the current item list is "complete
    # enough" or whether we need to refetch. With quarter-resolution items,
    # one full day = 96 quarters, two days = 192. We use 97 as the trigger
    # for use_second_day (one full day done, second day's data should be
    # arriving).

    def perform_update(self, items):
        # Re-resolve the configured primary/failback market on every
        # update. Without this, an Itemlist instance constructed once
        # at startup keeps the original market names even after the
        # user switches markets in the web UI -- so the new market is
        # only picked up after a SEUSS restart.
        new_primary = next(
            (m['name'] for m in self._config.markets
             if m.get('primary', False) and m.get('enabled', False)),
            self.primary_market_name,
        )
        new_failback = next(
            (m['name'] for m in self._config.markets
             if not m.get('primary', False) and m.get('enabled', False)),
            self.failback_market_name,
        )

        market_changed = (
            new_primary != self.primary_market_name
            or new_failback != self.failback_market_name
        )
        if market_changed:
            self._logger.log.info(
                f"Market configuration changed: "
                f"primary {self.primary_market_name} -> {new_primary}, "
                f"failback {self.failback_market_name} -> {new_failback}. "
                f"Discarding cached items."
            )
            # Drop cached items so the next refresh fetches fresh data
            # from the new primary market.
            items._item_list = []

        self.primary_market_name = new_primary
        self.failback_market_name = new_failback
        self.current_market_name = self.primary_market_name

        items.remove_expired_items()
        backup_items = items

        # Trigger refresh when:
        #   - the list is empty
        #   - no item covers "now" (so get_current_price returns None)
        #   - second-day mode but we have less than ~one full day of data
        need_refresh = (
            not items.get_current_list()
            or items.get_current_price() is None
            or (self._config.use_second_day
                and len(items.get_current_list()) < 97)
        )

        if need_refresh:
            self._logger.log.info(
                f"Price update is done with {self.primary_market_name}..."
            )
            market_info = self._config.get_market_info(self.primary_market_name)
            loader = GenericLoaderFactory.create_loader("spotmarket", market_info)
            updated_items = Itemlist.create_item_list(
                loader.load_data(self._config.use_second_day)
            )

            if not updated_items.get_current_list():
                self._logger.log.warning(
                    f"Update with {self.primary_market_name} not possible"
                )
                failback_info = self._config.get_market_info(
                    self.failback_market_name
                )
                if not failback_info:
                    self._logger.log.warning(
                        "Failback market information is empty. Aborting."
                    )
                else:
                    self._logger.log.info(
                        f"Price update is done with {self.failback_market_name}..."
                    )
                    failback_loader = GenericLoaderFactory.create_loader(
                        "spotmarket", failback_info
                    )
                    updated_items = Itemlist.create_item_list(
                        failback_loader.load_data(self._config.use_second_day)
                    )
                    self.current_market_name = self.failback_market_name

            items = updated_items
            if not items.get_current_list() and backup_items.get_current_list():
                items = backup_items

        # Apply the tariff resolution: when the user is on an hourly
        # tariff (the typical Austrian Awattar/Tibber retail contract)
        # we average all four 15-minute quarter prices of an hour to a
        # single value and write that back to each quarter. This way
        # the rest of the system (cluster selection, chart, switching
        # logic) treats the data exactly like Awattar -- so a user who
        # fetches prices via ENTSO-E but pays per hour gets hour-aligned
        # clusters instead of quarter-shifted ones that don't match
        # the bill.
        if getattr(self._config, "tariff_resolution", "hourly") == "hourly":
            self._collapse_quarters_to_hourly_average(items)

        return items

    @staticmethod
    def _collapse_quarters_to_hourly_average(items_list):
        """
        For each local-time hour represented in the items, replace every
        item's price with the integer-millicent average of all items
        that fall into that hour. Operates in-place on Item.price.

        Idempotent -- if the prices in an hour are already identical
        (e.g. Awattar source), this is a no-op.
        """
        from collections import defaultdict
        items = items_list.get_current_list()
        if not items:
            return

        buckets = defaultdict(list)
        for it in items:
            local = TimeUtilities.convert_utc_to_local(
                it.get_start_datetime(), False
            )
            if local is None:
                continue
            # Tolerate string return from convert_utc_to_local
            if isinstance(local, str):
                try:
                    local = datetime.strptime(local, "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
            key = (local.date(), local.hour)
            buckets[key].append(it)

        for key, group in buckets.items():
            if len(group) < 2:
                continue
            try:
                total = sum(int(it.price) for it in group)
            except (TypeError, ValueError):
                continue
            avg = total // len(group)
            for it in group:
                it.price = avg
