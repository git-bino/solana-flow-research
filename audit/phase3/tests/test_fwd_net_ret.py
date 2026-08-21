"""Unit tests for the §12.4 exit rules and the vectorised P&L.

The exit-rule cases use hand-built trajectories with the expected exit age
worked out by hand in the docstring of each test, so a change in the rule
breaks a stated expectation rather than a recorded output.
"""

from __future__ import annotations

import sys
from decimal import Decimal, getcontext
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import cost_model  # noqa: E402
from src.fwd_net_ret import (  # noqa: E402
    FIRST_AGE, K, TRAJ, Cell, combine, flow_exit, net_pnl_vec, stop_exit,
)


def traj_from(values: list[float]) -> np.ndarray:
    """One trajectory, padded with +1 (alive) out to 75 ages."""
    row = np.ones(TRAJ, dtype=np.float64)
    row[:len(values)] = values
    return row[None, :]


# ---------------------------------------------------------------- flow reversal

def test_flow_exit_ignores_ages_1_and_2():
    """nf3 <= 0 at a = 1 and 2 must not trigger: those ages still contain slot s.

    Trajectory: a=1 -5, a=2 -5, then positive forever.  With k = 1 the first
    eligible age is FIRST_AGE = 3, and nf3(3) = +1 > 0, so nothing ever fires.
    """
    t = traj_from([-5.0, -5.0])
    assert flow_exit(t, 1)[0] == 0


def test_flow_exit_k1_fires_at_first_eligible_age():
    """a=3 is the first age the rule looks at; nf3(3) = -1 <= 0 so exit age is 3."""
    t = traj_from([1.0, 1.0, -1.0])
    assert flow_exit(t, 1)[0] == FIRST_AGE == 3


def test_flow_exit_k2_needs_two_in_a_row():
    """nf3 <= 0 at a = 3 alone is not enough; a = 4 is positive, a = 6 and 7 are
    the first consecutive pair, so k = 2 exits at 7."""
    t = traj_from([1.0, 1.0, -1.0, 2.0, 3.0, -1.0, -1.0])
    assert flow_exit(t, 1)[0] == 3
    assert flow_exit(t, 2)[0] == 7


def test_flow_exit_k3_counts_the_third():
    """Ages 5, 6, 7 are the first run of three, so the exit age is 7."""
    t = traj_from([1.0, 1.0, 1.0, 2.0, -1.0, -1.0, -1.0])
    assert flow_exit(t, 3)[0] == 7


def test_flow_exit_k2_run_straddling_the_start_does_not_count_age_2():
    """a = 2 is -1 and a = 3 is -1, but a = 2 is ineligible, so k = 2 must not
    fire at 3.  a = 6, 7 is the first admissible pair."""
    t = traj_from([1.0, -1.0, -1.0, 5.0, 5.0, -2.0, -2.0])
    assert flow_exit(t, 2)[0] == 7


def test_flow_exit_zero_counts_as_reversal():
    """The rule is nf3(a) <= 0, so an exact zero fires."""
    assert flow_exit(traj_from([1.0, 1.0, 0.0]), 1)[0] == 3


# ------------------------------------------------------------------- hard stop

def _cell(f_row: list[float], depth: float, xend: float | None = None) -> Cell:
    f = np.zeros((1, TRAJ), dtype=np.float64)
    f[0, :len(f_row)] = f_row
    cumf = np.concatenate([np.zeros((1, 1)), np.cumsum(f, axis=1)], axis=1)
    return Cell(np.ones((1, TRAJ)), f, cumf, np.array([depth]),
                np.array([depth if xend is None else xend]), {}, {}, 1)


def test_stop_exit_base_true_uses_x_end_slot():
    """The two conventions differ by exactly `x_end_slot - depth_x`.

    depth 50, x_end_slot 45 (5 SOL of same-slot selling after the trigger),
    latency 1 with f(1) = 0 and q = 1.  The entry threshold is the same under
    both -- it is struck on the observable depth -- at sqrt(0.95*50*51) = 49.219.
    Under "obs" the reserve after entry is 51 and never crosses; under "true" it
    is 46 and is already below, so the stop fires at the first eligible age.
    """
    c = _cell([0.0], 50.0, xend=45.0)
    assert stop_exit(c, q=1.0, lat=1, L=0.05, base="obs")[0] == 0
    assert stop_exit(c, q=1.0, lat=1, L=0.05, base="true")[0] == FIRST_AGE


def test_stop_exit_none_never_fires():
    assert stop_exit(_cell([-10.0] * 10, 50.0), q=1.0, lat=1, L=None)[0] == 0


def test_stop_exit_fires_when_price_falls_by_L():
    """depth 50, latency 1 slot with f(1) = 0, so x_eff = 50 and q = 1.

    Entry price x k = 50 * 51 = 2550.  A 20% stop needs x(a) <= sqrt(0.8*2550)
    = sqrt(2040) = 45.166.  x after entry is 51, and f(2) = -6 takes it to 45,
    which is below the threshold, so the exit age is 3 -- the first eligible age
    at or after the crossing (f(2) lands by age 2, but ages below 3 are ignored).
    """
    c = _cell([0.0, -6.0], 50.0)
    assert stop_exit(c, q=1.0, lat=1, L=0.20)[0] == 3


def test_stop_exit_respects_first_age():
    """A crossing at age 2 is held back to age 3.

    depth 50, latency 1 slot, f(1) = 0 so V = 0 and x_eff = 50.  Entry price x k
    is 50 * 51 = 2550, and a 5% stop needs x(a) <= sqrt(0.95 * 2550) = 49.219.
    f(2) = -5 puts x(2) at 51 - 5 = 46, already below it, but ages under 3 are
    ignored; x(3) is still 46, so the reported exit age is 3.
    """
    c = _cell([0.0, -5.0], 50.0)
    assert stop_exit(c, q=1.0, lat=1, L=0.05)[0] == FIRST_AGE


def test_latency_flow_is_absorbed_into_entry_not_treated_as_a_loss():
    """Flow inside the latency window moves the fill, it does not move the stop.

    With latency 1 slot and f(1) = -30, the entry is struck at x_eff = 20 rather
    than 50, and x stays at 21 afterwards -- above sqrt(0.95 * 20 * 21) = 19.975 --
    so a 5% stop never fires.  (This case was written the other way round first;
    the expectation was wrong, not the rule.)
    """
    c = _cell([-30.0], 50.0)
    assert stop_exit(c, q=1.0, lat=1, L=0.05)[0] == 0


# ----------------------------------------------------------------- combination

def test_combine_takes_the_earliest_and_marks_never_as_censored():
    flow = np.array([7, 0, 40])
    age = np.array([13, 13, 13])
    stop = np.array([0, 0, 5])
    a_exit, censored = combine(flow, age, stop)
    assert list(a_exit) == [7, 13, 5]
    assert list(censored) == [False, False, False]


def test_combine_censors_when_nothing_fires():
    a_exit, censored = combine(np.array([0]), np.array([0]), np.array([0]))
    assert a_exit[0] == TRAJ and censored[0]


# -------------------------------------------------------------- P&L arithmetic

@pytest.mark.parametrize("x_obs,q,V,W,pf", [
    (50.0, 1.0, 0.0, 0.0, 0.0),
    (50.0, 1.0, 0.409886, 2.0, 0.001),
    (35.0, 0.5, -1.0, -3.0, 0.01),
    (100.0, 5.0, 1.5, 10.0, 0.001),
    (70.0, 2.0, 0.0, -5.0, 0.0),
])
def test_net_pnl_vec_matches_decimal(x_obs, q, V, W, pf):
    """The float64 path must agree with the exact Decimal path to 1e-12 relative."""
    from decimal import localcontext
    with localcontext() as ctx:
        ctx.prec = 60
        want = cost_model.net_pnl(x_obs, q, V, W, pf=pf)
    got = float(net_pnl_vec(np.array([x_obs]), q, np.array([V]),
                            np.array([W]), pf)[0])
    denom = max(abs(float(want)), abs(got), 1.0)
    assert abs(got - float(want)) / denom < 1e-12


def test_net_pnl_vec_is_vectorised_elementwise():
    x = np.array([50.0, 35.0, 70.0])
    V = np.array([0.0, 1.0, -1.0])
    W = np.array([0.0, 2.0, -2.0])
    got = net_pnl_vec(x, 1.0, V, W, 0.001)
    for i in range(3):
        one = net_pnl_vec(x[i:i + 1], 1.0, V[i:i + 1], W[i:i + 1], 0.001)[0]
        assert got[i] == one


def test_zero_flow_loses_exactly_the_round_trip_cost():
    """With V = W = 0 the position is closed at the price it opened, so the loss
    is the fee round trip plus priority fees and nothing else."""
    got = float(net_pnl_vec(np.array([50.0]), 1.0, np.array([0.0]),
                            np.array([0.0]), 0.0)[0])
    assert got < 0
    # buy pays q/(1-f), sell returns roughly q(1-f) less own impact
    assert -0.06 < got < -0.02
