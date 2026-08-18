"""Slot ordering and window boundaries — spec §2.4, §4.3, §8.2 requirement 8.

§2.4 fixes the order as (token_mint, slot, tx_index) and decisions.md extends it
with ix_index, because one transaction can carry several pump.fun trades.

The boundary tests are hand-built with exactly one event per slot so the expected
value can be written out by hand: the window is **(a − w, a]**, so slot a − w is
outside it.  An off-by-one here silently changes every flow feature, which is why
§8.2's requirement 8 names it.

The last test is a regression for the defect fixed on 2026-08-18: nf3 used to be
read off the last event in a slot and zeroed when the slot was empty, which
collapsed the window whenever trading paused for a single slot.
"""

from __future__ import annotations

import random
from decimal import Decimal

from src.features_reference import net_flow
from src.oh_reference import (
    Event,
    LAMPORTS,
    TokenState,
    _slot_flow,
    _trajectory_rolling,
    replay_token,
)
from src.curve import X0_LAMPORTS, Y0_UNITS
from tests.synthetic import SyntheticConfig, make_token

SOL = 1_000_000_000


def ev(slot, lam, is_buy=True, tx=0, ix=0, wallet="w") -> Event:
    return Event(mint="M", slot=slot, tx_index=tx, ix_index=ix, wallet=wallet,
                 is_buy=is_buy, lam=lam, units=1_000_000, vsol=50 * SOL,
                 x0_lam=X0_LAMPORTS, y0_units=Y0_UNITS)


def test_events_are_ordered_by_slot_then_tx_index_then_ix_index():
    """§2.4 + decisions.md: (slot, tx_index, ix_index) is the total order."""
    unordered = [ev(10, SOL, tx=2, ix=0), ev(10, SOL, tx=1, ix=64),
                 ev(10, SOL, tx=1, ix=0), ev(9, SOL, tx=99, ix=0)]
    keys = [e.key for e in sorted(unordered, key=lambda e: e.key)]
    assert keys == [(9, 99, 0), (10, 1, 0), (10, 1, 64), (10, 2, 0)]


def test_shuffling_the_input_does_not_change_the_result():
    """Replay sorts by the canonical key, so input order is irrelevant (§2.4)."""
    events = make_token(SyntheticConfig(n_events=60, seed=5), token_index=0)
    shuffled = list(events)
    random.Random(3).shuffle(shuffled)
    assert [r["oh"] for r in replay_token(events)] == [r["oh"] for r in replay_token(shuffled)]


def test_three_slot_window_is_half_open_below():
    """nf3 covers (a−3, a] = slots a−2, a−1, a — slot a−3 is OUTSIDE.

    One event per slot, 1 SOL each, so the answer is a count.
    """
    events = [ev(10, SOL), ev(11, SOL), ev(12, SOL), ev(13, SOL)]
    flow = _slot_flow(events)
    traj = _trajectory_rolling(flow, burst_slot=10, include_pre=True)
    # a = 3 -> target slot 13, window (10, 13] = slots 11, 12, 13 = 3 SOL.
    # If the window were [10, 13] it would be 4 SOL.
    assert traj[2] == Decimal(3)
    # a = 1 -> target 11, window (8, 11] = slots 9, 10, 11 -> only 10 and 11 exist
    assert traj[0] == Decimal(2)


def test_five_slot_flow_window_is_half_open_below():
    """f1's window is (s−5, s]; the event exactly 5 slots back is excluded (§3 f1)."""
    events = [ev(100, SOL), ev(101, SOL), ev(105, SOL)]
    # at i = 2 (slot 105) the window is (100, 105]: slot 100 is OUT, 101 and 105 are IN
    assert net_flow(events, 2, 5) == Decimal(2)
    # widen by one slot -> (99, 105] -> the slot-100 event enters too
    assert net_flow(events, 2, 6) == Decimal(3)


def test_rolling_nf3_survives_empty_slots():
    """Regression: an empty slot must not zero the window (fix of 2026-08-18).

    Slots 21 and 22 are empty; nf3 at slot 22 still sees slots 20 and 21... and
    at slot 23 the window has moved past every trade, so it is genuinely 0.
    """
    events = [ev(20, 2 * SOL)]
    flow = _slot_flow(events)
    traj = _trajectory_rolling(flow, burst_slot=20, include_pre=True)
    assert traj[0] == Decimal(2)   # a=1, slot 21, window (18,21] contains slot 20
    assert traj[1] == Decimal(2)   # a=2, slot 22, window (19,22] still contains slot 20
    assert traj[2] == Decimal(0)   # a=3, slot 23, window (20,23] excludes slot 20
    assert len(traj) == 75


def test_excl_pre_variant_drops_pre_burst_slots():
    """The two §4.3 variants differ exactly on slots at or before the burst."""
    events = [ev(20, 2 * SOL), ev(21, 1 * SOL)]
    flow = _slot_flow(events)
    incl = _trajectory_rolling(flow, 20, include_pre=True)
    excl = _trajectory_rolling(flow, 20, include_pre=False)
    assert incl[0] == Decimal(3)   # slots 20 and 21
    assert excl[0] == Decimal(1)   # slot 21 only
    assert incl[2] == excl[2]      # by a=3 the burst slot is out of both windows


def test_multiple_events_in_one_slot_all_contribute_to_slot_flow():
    """A slot's flow is the SUM over its events, not the last one (fix of 2026-08-18)."""
    events = [ev(30, SOL, tx=1), ev(30, SOL, tx=2), ev(30, SOL, tx=3, is_buy=False)]
    assert _slot_flow(events)[30] == SOL
    assert _slot_flow(events[:2])[30] == 2 * SOL


def test_state_advances_in_key_order_within_a_slot():
    """Two trades sharing a slot are applied in (tx_index, ix_index) order (§2.4)."""
    state = TokenState(X0_LAMPORTS, Y0_UNITS)
    first = ev(10, 3 * SOL, tx=1, wallet="a")
    second = ev(10, 1 * SOL, tx=2, wallet="a", is_buy=False)
    for e in sorted([second, first], key=lambda e: e.key):
        state.apply(e)
    w = state.wallets["a"]
    assert w.buy_lam == 3 * SOL and w.held_units == 0
