"""Label boundary at the trigger ROW — spec §4.2, decisions.md (2026-08-18).

The boundary is the trigger row, not the trigger slot: everything after it is
future, including trades in the SAME slot that execute later in
(tx_index, ix_index) order.  Before FIX 6 the two label families disagreed —
`fwd_net_flow` used `RANGE 1 FOLLOWING`, which starts at the next slot and so was
blind to same-slot successors that `x_at_plus` could already see.

The first test is the one that pins it: one synthetic case where the same three
trades must be counted by the label and ignored by every feature.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.curve import X0_LAMPORTS, Y0_UNITS
from src.features_reference import CAUSAL_FEATURES, fwd_net_flow, x_at_plus
from src.oh_reference import Event

SOL = 1_000_000_000


def ev(slot, tx, lam, vsol_sol, is_buy=True, wallet="w") -> Event:
    return Event(mint="M", slot=slot, tx_index=tx, ix_index=0, wallet=wallet,
                 is_buy=is_buy, lam=lam, units=1_000_000, vsol=vsol_sol * SOL,
                 x0_lam=X0_LAMPORTS, y0_units=Y0_UNITS)


def _trigger_plus_same_slot_successors() -> tuple[list[Event], int]:
    """Two trades before the trigger, the trigger, then three more — all one slot."""
    events = [
        ev(100, 0, 1 * SOL, 40, wallet="a"),
        ev(100, 1, 1 * SOL, 41, wallet="b"),
        ev(100, 2, 1 * SOL, 42, wallet="c"),      # <- trigger, index 2
        ev(100, 3, 2 * SOL, 44, wallet="d"),
        ev(100, 4, 2 * SOL, 46, wallet="e"),
        ev(100, 5, 2 * SOL, 48, wallet="f"),
    ]
    return events, 2


@pytest.mark.parametrize("window", [5, 12, 37])
def test_forward_flow_counts_same_slot_successors(window):
    """§4.2: the three trades after the trigger, in its own slot, ARE future."""
    events, t = _trigger_plus_same_slot_successors()
    assert fwd_net_flow(events, t, window) == 6, "6 SOL of same-slot successors"


@pytest.mark.parametrize("feature", sorted(CAUSAL_FEATURES))
def test_features_ignore_same_slot_successors(feature):
    """§6.1: the same three trades are invisible to every f1–f9 at the trigger."""
    events, t = _trigger_plus_same_slot_successors()
    fn = CAUSAL_FEATURES[feature]
    assert fn(events, t) == fn(events[: t + 1], t), (
        f"{feature} moved when same-slot successors were removed"
    )


def test_the_boundary_is_the_row_not_the_slot():
    """Both halves in one assertion: the label sees them, the feature does not."""
    events, t = _trigger_plus_same_slot_successors()
    assert fwd_net_flow(events, t, 5) == 6
    assert CAUSAL_FEATURES["net_flow_5slot"](events, t) == 3   # only the first three
    assert CAUSAL_FEATURES["net_flow_5slot"](events, t) == \
        CAUSAL_FEATURES["net_flow_5slot"](events[: t + 1], t)


def test_x_at_plus_takes_the_last_row_of_a_tied_final_slot():
    """FIX 7: with four trades in the final slot, the LAST one's x_post wins.

    `last_value` over a RANGE frame picks an arbitrary peer here; the reference
    and the SQL both resolve the tie by key order (SQL: max_by(vsol, seq)).
    """
    events = [
        ev(100, 0, SOL, 40),                       # trigger, index 0
        ev(104, 1, SOL, 50), ev(104, 2, SOL, 60),
        ev(104, 3, SOL, 70), ev(104, 4, SOL, 80),  # last row of the final slot
    ]
    assert x_at_plus(events, 0, 5) == 80
    assert x_at_plus(events, 0, 3) == 40, "no row within 3 slots -> the trigger's own"


def test_f3_optimisation_did_not_change_any_value():
    """Regression for the slot_buyers narrowing (2026-08-18).

    Values captured from the un-narrowed query before the change; the narrowing
    restricts which (mint, slot) buyer sets are built, never which ones a burst
    reads, so every one of the 88 rows must be identical.
    """
    before = json.loads((Path(__file__).resolve().parent.parent / "data" / "cache"
                         / "f3_before_narrowing.json").read_text())
    after = {f"{r['token_mint']}|{r['slot']}|{r['tx_index']}|{r['ix_index']}":
             r["n_buyers_12slot"]
             for r in json.loads((Path(__file__).resolve().parent.parent / "data" / "cache"
                                  / "parity_sql_rows_200tokens.json").read_text())}
    assert len(before) == 88 and set(before) == set(after)
    differences = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert differences == {}, f"narrowing changed f3 on {len(differences)} rows"
