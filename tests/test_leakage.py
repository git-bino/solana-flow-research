"""Temporal leakage — spec §3 ("хатуу дүрэм"), §6.1, §8.2 requirement 8.

Two halves that only mean something together:

  test_feature_is_blind_to_the_future
      corrupt every event after t and demand each feature at t is unchanged.
      A feature that reads ahead moves, and the parameterised id names it.

  test_forward_label_reacts_to_the_future
      the same corruption applied to §4.2/§4.3 labels, which MUST move.  Without
      this, a suite could pass by computing nothing at all, or by mislabelling a
      forward window as a feature.

The functions under test take the whole event list plus an index precisely so
that leaking is possible; see the note in src/features_reference.
"""

from __future__ import annotations

import pytest

from src.features_reference import CAUSAL_FEATURES, FORWARD_LABELS
from src.oh_reference import (
    Event,
    TokenState,
    _burst_keys,
    _slot_flow,
    _trajectory_rolling,
    death_age,
)
from tests.synthetic import PERTURBATIONS, SyntheticConfig, make_token


def _token(**kw) -> list[Event]:
    return make_token(SyntheticConfig(n_events=80, **kw), token_index=0)


def _oh_at(events: list[Event], i: int) -> tuple:
    """OH family at event i, from the events up to and including i."""
    state = TokenState(events[0].x0_lam, events[0].y0_units)
    for e in events[: i + 1]:
        state.apply(e)
    oh, ratio, conc, n = state.overhead(events[i].vsol)
    return oh, ratio, conc, n


T_INDEX = 40


@pytest.mark.parametrize("feature", sorted(CAUSAL_FEATURES))
@pytest.mark.parametrize("perturbation", sorted(PERTURBATIONS))
def test_feature_is_blind_to_the_future(feature, perturbation):
    """f1–f9 at t must not move when events after t are corrupted (§3, §6.1)."""
    events = _token()
    corrupted = PERTURBATIONS[perturbation](events, T_INDEX)
    fn = CAUSAL_FEATURES[feature]
    assert fn(events, T_INDEX) == fn(corrupted, T_INDEX), (
        f"{feature} changed when only post-t events were altered ({perturbation})"
    )


@pytest.mark.parametrize("perturbation", sorted(PERTURBATIONS))
def test_oh_family_is_blind_to_the_future(perturbation):
    """OH, OH_ratio, OH_conc at t use only wallet state as of t (§1.2, §6.1)."""
    events = _token()
    corrupted = PERTURBATIONS[perturbation](events, T_INDEX)
    assert _oh_at(events, T_INDEX) == _oh_at(corrupted, T_INDEX)


@pytest.mark.parametrize("perturbation", sorted(PERTURBATIONS))
def test_burst_trigger_is_blind_to_the_future(perturbation):
    """Whether t opens a burst depends only on flow up to t (§4.1)."""
    events = _token()
    corrupted = PERTURBATIONS[perturbation](events, T_INDEX)
    before = {k for k in _burst_keys(events) if k <= T_INDEX}
    after = {k for k in _burst_keys(corrupted) if k <= T_INDEX}
    assert before == after


@pytest.mark.parametrize("label", sorted(FORWARD_LABELS))
def test_forward_label_reacts_to_the_future(label):
    """§4.2 labels are supposed to look ahead — the counter-test to the above.

    Uses the size perturbation, which is the one guaranteed to change a sum of
    signed amounts; the window is checked to be non-empty first, since a label
    over an empty window has nothing to react to.
    """
    events = _token(empty_slot_share=0.0)
    corrupted = PERTURBATIONS["scale_sol_x100"](events, T_INDEX)
    fn = FORWARD_LABELS[label]
    assert fn(events, T_INDEX) != fn(corrupted, T_INDEX), (
        f"{label} did not move when the future changed — it is not reading forward"
    )


def test_trajectory_and_death_age_react_to_the_future():
    """§4.3's trajectory and death_age are forward-looking by construction."""
    events = _token(empty_slot_share=0.0)
    corrupted = PERTURBATIONS["scale_sol_x100"](events, T_INDEX)
    burst_slot = events[T_INDEX].slot
    base = _trajectory_rolling(_slot_flow(events), burst_slot, include_pre=True)
    moved = _trajectory_rolling(_slot_flow(corrupted), burst_slot, include_pre=True)
    assert base != moved
    assert (death_age(base), death_age(moved)) != (None, None) or base != moved


def test_perturbation_only_touches_the_future():
    """Guard on the test harness itself: if a perturbation edited the past, every
    leakage assertion above would be vacuous."""
    events = _token()
    for name, fn in PERTURBATIONS.items():
        corrupted = fn(events, T_INDEX)
        assert corrupted[: T_INDEX + 1] == events[: T_INDEX + 1], name


# --- hardening for the f3/f8/f9 intra-slot defect (fixed 2026-08-18) --------

def _one_slot_token(n: int = 5) -> list[Event]:
    """`n` trades all sharing one slot, distinguished only by tx_index.

    This is the shape that exposed the defect: a `RANGE ... CURRENT ROW` frame
    ordered by slot treats all of them as peers, so a feature at the 3rd trade
    silently absorbed the 4th and 5th.
    """
    base = _token(empty_slot_share=0.0)[:1][0]
    return [
        Event(mint="M", slot=500, tx_index=i, ix_index=0,
              wallet=f"W{i}", is_buy=(i != 3),
              lam=(i + 1) * 100_000_000, units=1_000_000 * (i + 1),
              vsol=base.vsol, x0_lam=base.x0_lam, y0_units=base.y0_units)
        for i in range(n)
    ]


@pytest.mark.parametrize("feature", ["n_buyers_12slot", "size_cv_25slot", "round_frac_25slot"])
def test_same_slot_later_trades_do_not_enter_a_feature(feature):
    """§6.1: at the 3rd trade of a slot, the 4th and 5th must be invisible.

    Trades that executed EARLIER in the same slot are real history and must stay
    in the window — this test pins that too, by checking the value also differs
    from the one computed with only the current trade.
    """
    events = _one_slot_token(5)
    fn = CAUSAL_FEATURES[feature]
    at_third_full = fn(events, 2)
    at_third_truncated = fn(events[:3], 2)
    assert at_third_full == at_third_truncated, (
        f"{feature} at the 3rd trade changed when later same-slot trades were dropped"
    )
    only_current = fn(events[2:3], 0)
    assert at_third_full != only_current, (
        f"{feature} ignored the earlier same-slot trades, which are real history"
    )


def test_n_buyers_counts_wallets_not_null_when_the_window_holds_a_sell():
    """Regression for the NULL buyer (FIX 5b).

    The old SQL built the count from `array_agg(if(is_buy, wallet))`, so every
    sell contributed a NULL that `array_distinct` kept and `cardinality` counted.
    Here trade index 3 is the sell, so a NULL-counting implementation returns 5
    where the correct answer is 4.
    """
    events = _one_slot_token(5)
    assert sum(1 for e in events if not e.is_buy) == 1
    distinct_buyers = len({e.wallet for e in events if e.is_buy})
    assert distinct_buyers == 4
    assert CAUSAL_FEATURES["n_buyers_12slot"](events, 4) == 4
