"""Hand-computed tests for the frozen anchor rule, plus a mutation harness.

Every expectation below is computed by hand in the docstring or comment.  The
mutation harness at the bottom injects the opposite convention for each rule
component and asserts the canonical checks then FAIL -- a test that cannot fail
locks nothing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src import anchor_rule as ar
from src import cost_model
from src.anchor_rule import Event, Params, apply

F = ar.FIXTURE
FEE = float(cost_model.FEE_RATE)


# ------------------------------------------------------------ 1. the anchor

def test_anchor_is_the_event_that_completes_the_third_holder():
    """A, B, C buy on events 1, 2, 3 -> the count reaches 3 at index 2, and the
    condition is not knowable before that event completes."""
    assert ar.anchor_index(F, 3) == 2
    assert ar.anchor_index(F, 2) == 1
    assert ar.anchor_index(F, 4) == 3


def test_anchor_reserve_is_the_one_the_anchor_event_left():
    """Event 3 moves the reserve 33.0 -> 40.0; the anchor price is 40.0."""
    o = apply(F, creator="A")
    assert o.x_anchor == pytest.approx(40.0)
    assert o.t_anchor == pytest.approx(4.0)


# ------------------------------------------------------------- 2. filters

def test_anchor_earlier_than_three_seconds_is_rejected():
    s = [Event(1, 0.1, 31.0, "A", +100.0), Event(2, 0.2, 33.0, "B", +100.0),
         Event(3, 2.9, 40.0, "C", +100.0)] + F[3:]
    o = apply(s, creator="A")
    assert o.traded is False and o.reason == "anchor_too_early"


def test_lower_tertile_filter_rejects_above_the_cut():
    """Three equal holders -> gini exactly 0, so a cut of 0.30 admits it and a
    negative cut cannot."""
    assert apply(F, creator="A", params=Params(tertile_cut=0.30)).traded is True
    assert apply(F, creator="A",
                 params=Params(tertile_cut=-0.01)).reason == "not_lower_tertile"


def test_creator_share_is_the_creators_balance_over_the_total():
    """A holds 100 of 300 at the anchor."""
    o = apply(F, creator="A")
    assert o.creator_share == pytest.approx(1.0 / 3.0)
    assert apply(F, creator="ZZ").creator_share == pytest.approx(0.0)


# -------------------------------------------------------------- 3. delays

def test_entry_is_the_third_trade_event_after_the_anchor():
    """Indices 3, 4, 5 are the first three trades after index 2 -> x = 44.0."""
    o = apply(F, creator="A")
    assert o.entry_idx == 5 and o.x_entry == pytest.approx(44.0)
    assert apply(F, creator="A", params=Params(entry_delay=1)).x_entry == pytest.approx(41.0)


def test_exit_is_the_third_trade_event_after_the_crossing():
    """Target 40.0 * 1.76 = 70.4; the first event at or above it is index 7
    (x = 71.0); three trades later is index 10 (x = 90.0)."""
    o = apply(F, creator="A")
    assert o.exit_idx == 10 and o.x_exit == pytest.approx(90.0)
    assert o.censored is False


def test_transfers_move_the_ledger_but_do_not_count_as_delay_events():
    """A transfer (x = None) makes the third holder, and the reserve carries
    33.0 forward; the entry delay then skips it and counts trades only."""
    s = [Event(1, 0.5, 31.0, "A", +100.0), Event(2, 1.0, 33.0, "B", +100.0),
         Event(3, 4.0, None, "C", +50.0),          # transfer -> anchor
         Event(4, 4.5, 35.0, "D", +10.0),
         Event(5, 5.0, 36.0, "E", +10.0),
         Event(6, 5.5, 37.0, "F", +10.0)]
    o = apply(s, creator="A", params=Params(target_mult=None))
    assert o.anchor_idx == 2 and o.x_anchor == pytest.approx(33.0)
    assert o.entry_idx == 5 and o.x_entry == pytest.approx(37.0)


def test_no_crossing_holds_to_the_last_trade_and_is_censored():
    s = F[:6] + [Event(7, 6.0, 45.0, "G", +10.0), Event(8, 7.0, 46.0, "H", +10.0)]
    o = apply(s, creator="A")
    assert o.censored is True and o.exit_idx == 7 and o.x_exit == pytest.approx(46.0)


def test_entry_that_never_fills_is_not_a_trade():
    s = F[:4]                      # only one trade after the anchor
    o = apply(s, creator="A")
    assert o.traded is False and o.reason == "entry_never_filled"
    assert o.pnl is None and o.ret is None


# ------------------------------------------------------------ 4. economics

def test_price_is_proportional_to_x_squared_in_the_small_q_limit():
    """As q -> 0 the own impact vanishes and

        ret -> (x_exit/x_entry)^2 * (1-f)  -  1/(1-f)

    NOT `r^2 (1-f)^2 - 1`: the fee is taken OUT of the proceeds and ADDED to the
    outlay, which is not the same as squaring one multiplier.  By hand,
    (90/44)^2 = 4.1838842975, x 0.9875 = 4.1315857438, - 1.0126582278
    = 3.1189275160."""
    o = apply(F, creator="A", params=Params(q=Decimal("1e-9")))
    expect = (90.0 / 44.0) ** 2 * (1 - FEE) - 1 / (1 - FEE)
    assert expect == pytest.approx(3.1189275160, abs=1e-9)
    assert float(o.ret) == pytest.approx(expect, rel=1e-7)


def test_fee_is_charged_per_side_on_a_flat_round_trip():
    """Exit at the entry price: ret -> (1-f) - 1/(1-f) = -0.02515822784810126."""
    s = [Event(1, 0.5, 31.0, "A", +100.0), Event(2, 1.0, 33.0, "B", +100.0),
         Event(3, 4.0, 40.0, "C", +100.0),
         Event(4, 4.5, 44.0, "D", +10.0), Event(5, 5.0, 44.0, "E", +10.0),
         Event(6, 5.5, 44.0, "F", +10.0), Event(7, 6.0, 44.0, "G", +10.0)]
    o = apply(s, creator="A", params=Params(target_mult=None, q=Decimal("1e-9")))
    assert float(o.ret) == pytest.approx((1 - FEE) - 1 / (1 - FEE), abs=1e-9)


def test_slippage_matches_cost_model_exactly():
    """Hand path: dy = k/44 - k/45, x2 = 44 + 1 + 46 = 91,
    out = dy*x2^2/(k + dy*x2), pnl = out*(1-f) - 1/(1-f) = 2.935911304..."""
    o = apply(F, creator="A")
    ref = cost_model.net_pnl(Decimal("44"), Decimal(1), V=0, W=Decimal("46"))
    assert o.pnl == ref
    assert float(o.pnl) == pytest.approx(2.935911304, abs=1e-9)


def test_fixed_cost_is_charged_once_per_leg_so_twice_per_round_trip():
    """Research lead, 2026-08-21: the cost is PER LEG.  0.002 SOL a leg is
    0.004 SOL on the round trip, which at q = 1 is 0.4% of return."""
    a = apply(F, creator="A", params=Params(fixed_cost=Decimal("0.002")))
    b = apply(F, creator="A")
    assert b.pnl - a.pnl == Decimal("0.004")
    assert float(b.ret - a.ret) == pytest.approx(0.004, abs=1e-12)


def test_bigger_q_costs_more_on_the_same_path():
    r = [float(apply(F, creator="A", params=Params(q=Decimal(str(q)))).ret)
         for q in (0.05, 0.1, 0.5, 1, 5)]
    assert r == sorted(r, reverse=True), r


# ------------------------------------------------------- 5. mutation harness

def _canonical(mod=ar) -> None:
    """The checks a correct implementation must pass, in one callable."""
    assert mod.anchor_index(F, 3) == 2
    o = mod.apply(F, creator="A")
    assert o.x_anchor == pytest.approx(40.0)
    assert o.entry_idx == 5 and o.x_entry == pytest.approx(44.0)
    assert o.exit_idx == 10 and o.x_exit == pytest.approx(90.0)
    assert float(o.pnl) == pytest.approx(2.935911304, abs=1e-9)
    assert mod.apply(F, creator="A", params=Params(tertile_cut=-0.01)).traded is False


MUTATIONS = {
    "anchor excludes its own event":
        lambda m: setattr(m, "anchor_index",
                          lambda ev, n: (lambda i: None if i in (None, 0) else i - 1)(
                              _orig_anchor(ev, n))),
    "entry priced one event early":
        lambda m: setattr(m, "_nth_trade_after",
                          lambda ev, i, n: _orig_nth(ev, i, max(n - 1, 1))),
    "reserve taken before the event":
        lambda m: setattr(m, "reserve_after",
                          lambda ev, i: _orig_reserve(ev, max(i - 1, 0))),
    "gini forced below any cut (filter never bites)":
        lambda m: setattr(m, "_gini", lambda vals: -1.0),
}
_orig_anchor = ar.anchor_index
_orig_nth = ar._nth_trade_after
_orig_reserve = ar.reserve_after
_orig_gini = ar._gini


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_each_mutation_breaks_the_canonical_checks(name, monkeypatch):
    monkeypatch.setattr(ar, "anchor_index", _orig_anchor)
    monkeypatch.setattr(ar, "_nth_trade_after", _orig_nth)
    monkeypatch.setattr(ar, "reserve_after", _orig_reserve)
    monkeypatch.setattr(ar, "_gini", _orig_gini)
    _canonical()                       # sane before the mutation
    MUTATIONS[name](ar)
    try:
        with pytest.raises(AssertionError):
            _canonical()
    finally:
        ar.anchor_index = _orig_anchor
        ar._nth_trade_after = _orig_nth
        ar.reserve_after = _orig_reserve
        ar._gini = _orig_gini
