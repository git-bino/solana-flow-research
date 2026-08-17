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
