"""Counter-tests for the fill-timing convention.

Every test here FAILS if entry or exit is priced on the reserve BEFORE the event
that produced the signal.  That is the defect class that killed the previous
candidate (expectancy +0.450435 -> -0.168718; 134.73% of the old gross P&L).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.fill_timing import (Ev, entry_reserve, exit_reserve, first_crossing,
                             gross_price_ratio, holder_anchor, reserve_after)

REPO = Path(__file__).resolve().parent.parent

#: anchor event moves the reserve hard: 33.0 -> 40.0
STREAM = [
    Ev(1, 31.0, "A", +100.0),
    Ev(2, 33.0, "B", +100.0),
    Ev(3, 40.0, "C", +100.0),   # <- third holder; the anchor
    Ev(4, 45.0, "D", +50.0),
    Ev(5, 72.0, "E", +50.0),    # <- first crossing of 1.76 x 40 = 70.4; 45 -> 72
    Ev(6, 68.0, "F", +10.0),
]


def test_holder_count_includes_the_anchor_event():
    assert holder_anchor(STREAM, 3) == 2


def test_entry_is_priced_after_the_anchor_event_not_before():
    a = holder_anchor(STREAM, 3)
    assert entry_reserve(STREAM, a) == pytest.approx(40.0)
    assert entry_reserve(STREAM, a) != pytest.approx(33.0)


def test_exit_is_priced_after_the_crossing_event_not_before():
    a = holder_anchor(STREAM, 3)
    i = first_crossing(STREAM, a, 1.76 * entry_reserve(STREAM, a), +1)
    assert i == 4
    assert exit_reserve(STREAM, i) == pytest.approx(72.0)
    assert exit_reserve(STREAM, i) != pytest.approx(45.0)


def test_the_pre_event_pricing_would_inflate_the_return_and_does_not():
    """Hand-computed.  Correct: (72/40)^2 = 3.24.  Pricing entry on the
    pre-anchor reserve would give (72/33)^2 = 4.7603, and pricing exit on the
    pre-crossing reserve would give (45/40)^2 = 1.2656.  Neither may appear."""
    a = holder_anchor(STREAM, 3)
    xe = entry_reserve(STREAM, a)
    i = first_crossing(STREAM, a, 1.76 * xe, +1)
    r = gross_price_ratio(xe, exit_reserve(STREAM, i))
    assert r == pytest.approx(3.24, abs=1e-9)
    assert r != pytest.approx((72.0 / 33.0) ** 2, abs=1e-6)
    assert r != pytest.approx((45.0 / 40.0) ** 2, abs=1e-6)


def test_forward_search_starts_strictly_after_the_anchor():
    """The anchor event cannot be its own crossing, even when its own reserve
    already satisfies the barrier."""
    a = holder_anchor(STREAM, 3)
    assert first_crossing(STREAM, a, 40.0, +1) == 3      # not 2


def test_downside_crossing_uses_the_post_event_reserve():
    s = [Ev(1, 31.0, "A", +100.0), Ev(2, 33.0, "B", +100.0),
         Ev(3, 40.0, "C", +100.0), Ev(4, 36.0, "D", -10.0),
         Ev(5, 19.0, "E", -80.0)]      # first event <= 0.50 x 40 = 20; 36 -> 19
    a = holder_anchor(s, 3)
    i = first_crossing(s, a, 0.50 * entry_reserve(s, a), -1)
    assert i == 4
    assert exit_reserve(s, i) == pytest.approx(19.0)
    assert exit_reserve(s, i) != pytest.approx(36.0)


def test_a_transfer_anchor_carries_the_last_trade_reserve_forward():
    """Transfers move units, not reserves; the reserve after a transfer is the
    reserve the last trade left."""
    s = [Ev(1, 31.0, "A", +100.0), Ev(2, 33.0, "B", +100.0),
         Ev(3, None, "C", +100.0)]
    a = holder_anchor(s, 3)
    assert a == 2
    assert reserve_after(s, a) == pytest.approx(33.0)


# --------------------------------------------------------------- SQL guards

def _sql(name: str) -> str:
    return (REPO / "sql" / name).read_text()


def test_sql_holder_count_window_includes_the_current_row():
    """`ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` on BOTH the per-wallet
    balance and the holder-count running sum.  Changing either to exclude the
    current row would make the anchor fire one event early."""
    s = _sql("holder_anchor.sql")
    n = len(re.findall(r"ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW", s))
    assert n >= 2, f"expected >= 2 inclusive windows, found {n}"
    assert "PRECEDING AND 1 PRECEDING" not in s


def test_sql_anchor_reserve_is_the_carried_forward_post_event_reserve():
    s = _sql("holder_anchor.sql")
    assert "last_value(x) IGNORE NULLS OVER" in s
    assert "min_by(x_ff, seq)" in s


def test_sql_barrier_forward_set_is_strictly_after_the_anchor():
    s = _sql("asymmetric_barriers.sql")
    assert "e.seq > a.seq_a" in s
    assert "e.seq >= a.seq_a" not in s


def test_sql_overshoot_takes_the_reserve_on_the_crossing_event():
    """`min_by(x, if(cond, seq))` is the x OF the earliest event satisfying the
    barrier -- its post-trade reserve.  A `lag(x)` there would be the defect."""
    s = _sql("asymmetric_barriers.sql")
    assert re.search(r"min_by\(x,\s*if\(x\s*[<>]=", s)
    assert "lag(x)" not in s
