"""Inverting the nf3 trajectory back to per-slot flow — src/reconstruct_label.

The recursion is exact in real arithmetic, so these tests check two separate
things: that the algebra is right (a hand-checkable case must come back exactly),
and that float64 does not spoil it over 75 steps of an undamped chain.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.reconstruct_label import (
    TAU,
    TRAJ_LEN,
    forward_flow,
    measure_error_growth,
    reconstruct_slot_flows,
    trajectory_from_slot_flows,
)


def test_hand_checkable_case_round_trips_exactly():
    """Expectation computed by hand from the definitions in §4.3.

    With f(−1)=1, f(0)=2 and f(a)=a for a = 1..75:
        nf3(1) = f(−1)+f(0)+f(1) = 1+2+1 = 4
        excl_1 = f(1) = 1
        excl_2 = f(1)+f(2) = 1+2 = 3
        nf3(3) = f(1)+f(2)+f(3) = 1+2+3 = 6
    and the inverse must return f exactly, with no float slack at all on integers.
    """
    flows = np.array([[1.0, 2.0] + [float(a) for a in range(1, TRAJ_LEN + 1)]])
    nf3, e1, e2 = trajectory_from_slot_flows(flows)
    assert nf3[0, 0] == 4.0
    assert e1[0] == 1.0 and e2[0] == 3.0
    assert nf3[0, 2] == 6.0
    got = reconstruct_slot_flows(nf3, e1, e2, TRAJ_LEN)
    assert np.array_equal(got, flows[:, 2:])


def test_random_streams_round_trip_within_tolerance():
    """Brief's requirement: reconstruction must agree to 1e-9 SOL.

    Amounts are heavy-tailed (Student t, df = 3, scaled to tens of SOL) so the
    check runs on the scale flow.burst actually holds rather than on well-behaved
    numbers.
    """
    stats = measure_error_growth(rows=5_000, seed=99)
    assert stats["max_abs_error_overall"] < 1e-9
    assert stats["label_max_abs_error"] < 1e-9


def test_error_does_not_grow_materially_along_the_recursion():
    """The recursion has no damping, so drift is the thing to watch.

    Expectation: each step adds one subtraction and one addition, so error grows
    at worst like the number of steps — nowhere near the eight orders of magnitude
    that would matter at 1e-9.  Asserted as a ratio between a = 75 and a = 12 so
    the test says something about growth rather than about absolute size.
    """
    stats = measure_error_growth(rows=5_000, seed=101)
    assert stats["max_abs_error_at_a12"] < 1e-9
    assert stats["max_abs_error_at_a75"] < 1e-9
    assert stats["max_abs_error_at_a75"] < 100 * stats["max_abs_error_at_a12"]


@pytest.mark.parametrize("tau", [3, 5, 12, 37])
def test_forward_flow_equals_the_sum_of_reconstructed_slots(tau):
    """`forward_flow` is only a sum; this pins that it sums the right window."""
    rng = np.random.default_rng(7)
    flows = rng.normal(scale=3.0, size=(200, TRAJ_LEN + 2))
    nf3, e1, e2 = trajectory_from_slot_flows(flows)
    got = forward_flow(nf3, e1, e2, tau)
    want = flows[:, 2:2 + tau].sum(axis=1)
    assert np.abs(got - want).max() < 1e-9


def test_seed_slots_come_from_the_closed_form_not_the_recursion():
    """f(1), f(2), f(3) must be exact regardless of the trajectory beyond them.

    Expectation from the derivation: they use only excl_1, excl_2 and nf3(3), so
    corrupting nf3 from index 4 onward cannot move them.
    """
    rng = np.random.default_rng(13)
    flows = rng.normal(scale=3.0, size=(50, TRAJ_LEN + 2))
    nf3, e1, e2 = trajectory_from_slot_flows(flows)
    clean = reconstruct_slot_flows(nf3, e1, e2, TAU)
    dirty_nf3 = nf3.copy()
    dirty_nf3[:, 3:] += 1000.0
    dirty = reconstruct_slot_flows(dirty_nf3, e1, e2, TAU)
    assert np.array_equal(clean[:, :3], dirty[:, :3])
    assert not np.array_equal(clean[:, 3:], dirty[:, 3:])


def test_upto_below_three_is_rejected():
    """The seed covers a = 1..3; asking for less is a programming error."""
    with pytest.raises(ValueError):
        reconstruct_slot_flows(np.zeros((1, 12)), np.zeros(1), np.zeros(1), upto=2)
