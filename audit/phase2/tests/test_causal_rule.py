"""Hand-computed tests for the causal rule (was: frozen rule).

Each case states its expected value in the docstring and why, so a change in the
rule breaks a written expectation rather than a recorded output.
"""

from __future__ import annotations

import sys
from decimal import Decimal, localcontext
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import causal_rule, cost_model  # noqa: E402
from src.causal_rule import TRAJ, apply, exit_age, net_pnl, slot_flows  # noqa: E402


def nf3_of(values, fill=1.0):
    """A 75-long nf3 trajectory: `values` at ages 1.., then `fill` forever."""
    row = [fill] * TRAJ
    row[:len(values)] = values
    return row


# ------------------------------------------------------------- 1. entry gate

def test_no_trade_when_exit_fires_at_or_before_the_entry():
    """nf3 goes non-positive at age 5, the entry lands at 8, so nothing opens.

    The rule is live from age 3, so a_exit = 5 <= L = 8 and the position was
    never available.
    """
    o = apply(nf3_of([1, 1, 1, 1, -1]), 0.0, 0.0, 50.0, 50.0, L=8)
    assert o.traded is False
    assert o.exit_age_rule == 5
    assert o.pnl is None


def test_trade_opens_when_the_exit_comes_after_the_decision():
    """First non-positive nf3 is at age 9, past the decision at end(8): trades.

    Entry fills at 9 (one slot after the decision) and the exit, whose predicate
    is known at end(9), fills at 10.
    """
    o = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 50.0, 50.0, L=8)
    assert o.traded is True
    assert o.entry_slot == 9
    assert o.exit_age_rule == 9
    assert o.exit_slot == 10


def test_ages_1_and_2_never_trigger_the_exit():
    """nf3 <= 0 at ages 1 and 2 is ignored: those windows still contain slot s.

    With ages 1 and 2 negative and everything after positive, the rule never
    fires, so the burst is censored at 75 and does trade.
    """
    o = apply(nf3_of([-5, -5]), 0.0, 0.0, 50.0, 50.0, L=8)
    assert o.exit_age_rule == TRAJ
    assert o.censored is True
    assert o.traded is True


# --------------------------------------------------------------- 2. exit age

def test_zero_counts_as_a_reversal():
    """The condition is nf3(a) <= 0, so an exact zero at age 9 exits there."""
    assert exit_age(nf3_of([1] * 8 + [0]))[0] == 9


def test_censored_when_flow_never_reverses():
    a, cens = exit_age(nf3_of([]))
    assert (a, cens) == (TRAJ, True)


# ------------------------------------------------------- 3. flow recursion

def test_slot_flows_round_trip_against_a_known_series():
    """Build nf3 from a known f, then recover f.

    f(-1)=0, f(0)=0, f(1..5) = 2, 3, 5, 7, 11 gives
    nf3(1)=0+0+2=2, nf3(2)=0+2+3=5, nf3(3)=2+3+5=10, nf3(4)=3+5+7=15,
    nf3(5)=5+7+11=23, with excl1 = f(1) = 2 and excl2 = f(1)+f(2) = 5.
    """
    f_true = [2, 3, 5, 7, 11]
    nf3 = nf3_of([2, 5, 10, 15, 23], fill=0.0)
    got = slot_flows(nf3, excl1=2.0, excl2=5.0)
    assert [round(got[a], 9) for a in range(1, 6)] == f_true


def test_slot_flows_matches_the_reference_implementation():
    """Independent from `src.reconstruct_label`, so check the two agree."""
    from src.reconstruct_label import reconstruct_slot_flows
    rng = np.random.default_rng(7)
    flows = rng.standard_t(df=3, size=(4, TRAJ + 2)) * 5.0
    nf3 = np.empty((4, TRAJ))
    for a in range(1, TRAJ + 1):
        nf3[:, a - 1] = flows[:, a - 1] + flows[:, a] + flows[:, a + 1]
    e1, e2 = flows[:, 2], flows[:, 2] + flows[:, 3]
    want = reconstruct_slot_flows(nf3, e1, e2, TRAJ)
    for i in range(4):
        got = slot_flows(list(nf3[i]), float(e1[i]), float(e2[i]))
        assert np.allclose(got[1:], want[i], rtol=0, atol=1e-6)


# ------------------------------------------------------------ 4. arithmetic

def test_net_pnl_matches_cost_model():
    """The re-derived path arithmetic must equal `cost_model.net_pnl` exactly."""
    with localcontext() as ctx:
        ctx.prec = 60
        want = cost_model.net_pnl(50, 5, Decimal("0.4"), Decimal(3), pf=Decimal("0.001"))
        got = net_pnl(Decimal(50), Decimal(5), Decimal("0.4"), Decimal(3),
                      Decimal("0.001"))
    assert abs(got - want) / max(abs(want), Decimal(1)) < Decimal("1e-25")


def test_k_constant_matches_cost_model():
    assert causal_rule.K == cost_model.K_DEFAULT


def test_fee_is_charged_on_both_sides():
    """A round trip with no flow either way loses exactly the fees plus impact.

    This is arithmetic, not a traded row: a burst can only stay open while
    nf3 > 0, which means flow is positive, so V = W = 0 never happens on a
    traded row.  (Written the other way round first -- the expectation was
    wrong, not the rule.)
    """
    got = net_pnl(Decimal(50), Decimal(5), Decimal(0), Decimal(0), Decimal(0))
    assert got < 0
    assert Decimal("-0.7") < got < Decimal("-0.1")


def test_traded_pnl_equals_the_hand_built_path():
    """apply() must agree with net_pnl fed the reconstruction by hand.

    Trajectory: nf3 = 3 at every age up to 8, then -1 at age 9.  With
    excl1 = excl2 = 1 the recursion gives f(1) = 1, f(2) = 0, f(3) = 3 - 1 = 2
    and f(a) = f(a-3) for a >= 4 while nf3 is flat, so the cumulative flow is
    fully determined and W follows from it.
    """
    nf3 = nf3_of([3] * 8 + [-1])
    o = apply(nf3, 1.0, 1.0, 55.0, 50.0, L=8)
    f = slot_flows(nf3, 1.0, 1.0)
    cum = [Decimal(0)]
    acc = Decimal(0)
    for a in range(1, TRAJ + 1):
        acc += Decimal(str(f[a]))
        cum.append(acc)
    x_entry = Decimal("55") + cum[8]        # end(s+8) reserve, x_end_slot base
    W = cum[10] - cum[8]                    # exit predicate at 9, fill at 10
    assert o.pnl == net_pnl(x_entry, Decimal(5), Decimal(0), W, Decimal(0))


def test_priority_fee_is_subtracted_twice():
    a = apply(nf3_of([]), 0.0, 0.0, 50.0, 50.0, pf=0)
    b = apply(nf3_of([]), 0.0, 0.0, 50.0, 50.0, pf=Decimal("0.01"))
    assert a.pnl - b.pnl == Decimal("0.02")


# ------------------------------------------------------------- 5. latencies

def test_entry_latency_changes_the_fill_and_the_gate():
    """At L = 1 a burst that reverses at age 5 does trade; at L = 8 it does not."""
    nf3 = nf3_of([1, 1, 1, 1, -1])
    assert apply(nf3, 0.0, 0.0, 50.0, 50.0, L=1).traded is True
    assert apply(nf3, 0.0, 0.0, 50.0, 50.0, L=8).traded is False


def test_exit_latency_moves_the_fill_and_is_capped_at_75():
    """A rule exit at 70 with Lx = 8 would fill at 70 + 1 + 8 = 79, held at 75."""
    o = apply(nf3_of([1] * 69 + [-1]), 0.0, 0.0, 50.0, 50.0, L=8, Lx=8)
    assert o.exit_age_rule == 70
    assert o.exit_slot == TRAJ


# ----------------------------------------------------- 6. causal execution clock
#
# The test that used to sit here -- "raising x_end_slot while depth_x stays put
# must raise the P&L" -- was REMOVED on 2026-08-20.  It asserted exactly the
# defect the audit found: it locked in `x_end_slot - depth_x`, flow that landed
# in the trigger slot before any order could exist, as post-entry profit.  The
# counter-tests below replace it.


def test_entry_reserve_is_not_depth_x():
    """With a gap between the two bases, pricing must NOT use depth_x.

    depth_x = 50, x_end_slot = 55, nf3 = 1 through age 8 with excl1 = excl2 = 0
    so f(1) = f(2) = 0 and f(3) = 1 - 0 = 1, f(a) = f(a-3) after that; the entry
    is struck at x_end_slot + cum[8], never at depth_x + cum[8].  Feeding a
    different depth_x therefore cannot move the answer at all.
    """
    a = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 55.0, 50.0)
    b = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 55.0, 10.0)
    c = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 55.0, None)
    assert a.pnl == b.pnl == c.pnl


def test_the_old_gap_no_longer_creates_profit():
    """Two bursts identical except for the trigger-slot gap must price the same.

    Burst A: depth_x = 50, x_end_slot = 50 (no gap).
    Burst B: depth_x = 30, x_end_slot = 50 (20 SOL landed in the trigger slot
    before any order could exist).  Under the old rule B booked that 20 SOL as
    profit; under the causal clock both are struck at 50 + cum[8] and the P&L is
    identical.
    """
    a = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 50.0, 50.0)
    b = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 50.0, 30.0)
    assert a.pnl == b.pnl


def test_entry_fills_one_slot_after_the_decision():
    """nf3(8) is only complete at end(s+8), so the fill age is 9, not 8."""
    o = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 50.0, 50.0, L=8)
    assert o.entry_slot == 9


def test_exit_fills_one_slot_after_its_predicate():
    """The exit predicate at age 9 is known at end(s+9); the fill is age 10."""
    o = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 50.0, 50.0, L=8, Lx=0)
    assert o.exit_age_rule == 9
    assert o.exit_slot == 10


def test_exit_latency_stacks_on_top_of_the_unavoidable_slot():
    """Lx is EXTRA latency: predicate at 9, fill at 9 + 1 + Lx."""
    for lx, want in ((0, 10), (1, 11), (3, 13)):
        o = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 50.0, 50.0, L=8, Lx=lx)
        assert o.exit_slot == want


def test_slot_boundary_predicate_at_L_plus_one():
    """Exit predicate at exactly age 9 with L = 8 still trades (gate is a>L).

    The decision at end(s+8) sees nf3(8) = 1 > 0 and no earlier break, so the
    order goes; nf3(9) <= 0 only becomes known at end(s+9), by which time the
    entry has filled at age 9.  Exit then fills at age 10.
    """
    o = apply(nf3_of([1] * 8 + [-1]), 0.0, 0.0, 50.0, 50.0, L=8)
    assert o.traded is True and o.entry_slot == 9 and o.exit_slot == 10


def test_migration_before_exit_is_priced_not_dropped():
    """A burst whose reserve crosses the 115 SOL migration level still prices.

    curve_progress = (x - 30) / 85, so progress = 1 at x = 115.  Starting at
    x_end_slot = 100 and adding nf3 = 30 per age drives f, and cum[8] carries the
    reserve past 115 well before the exit.  The rule has no migration branch, so
    the row must still return a number -- it is counted separately in the
    analysis, never dropped.
    """
    o = apply(nf3_of([30] * 12 + [-1]), 10.0, 20.0, 100.0, 100.0, L=8)
    assert o.traded is True
    assert o.pnl is not None


@pytest.mark.parametrize("L,expected_traded", [(1, True), (3, True), (8, False)])
def test_sensitivity_band_entry_latencies(L, expected_traded):
    """Reversal at age 6: opens under L = 1 and 3, not under L = 8."""
    o = apply(nf3_of([1] * 5 + [-1]), 0.0, 0.0, 50.0, 50.0, L=L)
    assert o.traded is expected_traded
