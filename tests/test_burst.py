"""Burst detection — spec §4.1 (v1.2, slot-based), §8.2 requirement 8.

    burst_start(t): net_flow_5slot(t) ≥ max(3 SOL, 0.10 × x(t))
                    AND түүнээс өмнөх 25 slot-д burst идэвхтэй байгаагүй

Three things get separate tests because they fail separately: the 5-slot window,
each branch of the max(), and the 25-slot quiet rule.  x(t) is read from the row
(spec §2.3), so the branch that binds is controlled by setting `vsol`.
"""

from __future__ import annotations

from src.curve import X0_LAMPORTS, Y0_UNITS
from src.oh_reference import Event, _burst_keys

SOL = 1_000_000_000


def ev(slot, lam, vsol_sol, is_buy=True, tx=0) -> Event:
    return Event(mint="M", slot=slot, tx_index=tx, ix_index=0, wallet="w",
                 is_buy=is_buy, lam=lam, units=1_000_000, vsol=vsol_sol * SOL,
                 x0_lam=X0_LAMPORTS, y0_units=Y0_UNITS)


def test_absolute_branch_binds_on_a_shallow_curve():
    """At x = 30 the threshold is max(3, 3.0) = 3 SOL — the absolute branch."""
    assert _burst_keys([ev(10, 3 * SOL, 30)]) == [0]          # exactly 3 qualifies (>=)
    assert _burst_keys([ev(10, 2_999_999_999, 30)]) == []     # a lamport short does not


def test_depth_branch_binds_on_a_deeper_curve():
    """At x = 80 the threshold is max(3, 8.0) = 8 SOL — the 0.10x branch."""
    assert _burst_keys([ev(10, 8 * SOL, 80)]) == [0]
    assert _burst_keys([ev(10, 7 * SOL, 80)]) == []           # clears 3 SOL, not 0.10x


def test_flow_is_summed_over_the_five_slot_window():
    """No single trade clears 3 SOL, but the window sums to 4 (§4.1, §3 f1)."""
    events = [ev(10, SOL, 30), ev(11, SOL, 30), ev(12, SOL, 30), ev(13, SOL, 30)]
    # the window first reaches 3 SOL at slot 12 (slots 10, 11, 12), so that is the
    # burst; slot 13 is inside the 25-slot quiet window and opens nothing further
    assert _burst_keys(events) == [2]


def test_window_is_half_open_so_an_old_trade_drops_out():
    """The trade 5 slots back is outside (s−5, s] and cannot help the sum."""
    events = [ev(10, 2 * SOL, 30), ev(15, 2 * SOL, 30)]
    assert _burst_keys(events) == []
    closer = [ev(11, 2 * SOL, 30), ev(15, 2 * SOL, 30)]
    assert _burst_keys(closer) == [1]


def test_sells_offset_buys_in_the_window():
    """net_flow is buy − sell, so an earlier sell inside the window suppresses it.

    Order matters and is causal: a sell that lands *after* the qualifying buy
    cannot un-trigger it, which is why the sell is placed first here.
    """
    events = [ev(10, 1 * SOL, 30, is_buy=False), ev(11, 3 * SOL, 30)]
    assert _burst_keys(events) == []          # 3 − 1 = 2 SOL, under the 3 SOL floor
    assert _burst_keys([ev(11, 3 * SOL, 30)]) == [0]   # same buy alone does qualify


def test_second_qualifying_event_inside_25_slots_does_not_open_a_burst():
    """The quiet rule: a qualifying event within 25 slots is the same burst (§4.1)."""
    events = [ev(10, 4 * SOL, 30), ev(30, 4 * SOL, 30)]      # 20 slots apart
    assert _burst_keys(events) == [0]


def test_qualifying_event_past_25_slots_opens_a_new_burst():
    """More than 25 slots of quiet and the next qualifying event is a new burst."""
    events = [ev(10, 4 * SOL, 30), ev(36, 4 * SOL, 30)]      # 26 slots apart
    assert _burst_keys(events) == [0, 1]


def test_quiet_rule_counts_from_the_last_qualifying_event_not_the_burst():
    """A chain of qualifying events 20 slots apart stays one burst throughout —
    this is the sessionisation approximation, stated in the reports rather than
    presented as §4.1's recursive definition."""
    events = [ev(10, 4 * SOL, 30), ev(30, 4 * SOL, 30), ev(50, 4 * SOL, 30)]
    assert _burst_keys(events) == [0]


def test_burst_uses_x_from_the_row_not_a_constant():
    """x(t) comes from virtual_sol_reserves (§2.3), so the same flow can qualify
    on a shallow curve and fail on a deep one."""
    assert _burst_keys([ev(10, 5 * SOL, 30)]) == [0]
    assert _burst_keys([ev(10, 5 * SOL, 100)]) == []
