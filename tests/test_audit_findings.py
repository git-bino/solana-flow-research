"""Regression tests for the four defect classes the external audit found.

decisions.md, 2026-08-19.  None of the 157 tests that existed before this file
could catch any of them, and the tests were not at fault: `tests/synthetic.py`
never produced the conditions, so nothing could look at them.  The generator was
extended first; these are the tests that extension makes possible.

Two kinds of test live here and they are labelled differently on purpose:

  * `xfail(strict=True)` — the behaviour is wrong and the correct expectation is
    written down.  Not repaired here; the brief says to report, not to fix.
  * `..._documents_current_incorrect_behavior` — the behaviour is also wrong, but
    the test asserts what the code does TODAY so that any change to it is
    visible.  Deleting one of these without a decision would erase the evidence.

Every expectation below is hand-computed or quoted from the spec.  None is read
back from the code's own output.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from src.features_reference import fwd_net_flow, n_buyers, net_flow
from src.oh_reference import THOUSAND, TOKEN_UNITS, TokenState, WalletState
from tests.synthetic import (
    IX_PACK_BASE,
    SyntheticConfig,
    config_field_names,
    exit_then_rebuy,
    mayhem_reparameterised,
    packing_collision_pair,
    packing_null_inner,
    same_slot_stream,
    transfer_then_sell,
    trigger_with_same_slot_neighbours,
)

TESTS_DIR = Path(__file__).resolve().parent


# ===========================================================================
# A. Label boundary — the window is (s, s+τ]
# ===========================================================================

def _boundary_case():
    raws, trigger = trigger_with_same_slot_neighbours(n_before=2, n_after=3,
                                                      slot=1000, lam=500_000_000)
    return [r.to_event() for r in raws], trigger


@pytest.mark.xfail(strict=True, reason=(
    "FINDING (decisions.md 2026-08-19): fwd_net_flow uses the trigger ROW as the "
    "boundary, so it counts trades that share the trigger's slot.  The window is "
    "(s, s+tau], which excludes them."))
def test_forward_flow_excludes_trades_in_the_triggers_own_slot():
    """Audit finding: label boundary.  spec §4.2, window (s, s+τ].

    Expectation, hand-computed: the three later trades all sit in slot 1000, the
    same slot as the trigger, and nothing lands in slots 1001..1012.  A window
    open at s therefore contains no flow at all, so fwd_net_flow(12) = 0 SOL.
    The current row-based boundary returns 3 × 0.5 = 1.5 SOL instead.
    """
    events, i = _boundary_case()
    assert fwd_net_flow(events, i, 12) == Decimal(0)


def test_trailing_features_exclude_trades_after_the_trigger_in_its_slot():
    """Audit finding: label boundary, causal half.  spec §3, §6.1.

    Expectation, hand-computed: five buys of 0.5 SOL share slot 1000 — two before
    the trigger, the trigger, three after.  A trailing 5-slot window at the
    trigger may see only the first three, so net_flow_5slot = 3 × 0.5 = 1.5 SOL.
    """
    events, i = _boundary_case()
    assert net_flow(events, i, 5) == Decimal("1.5")


def test_trailing_features_include_trades_before_the_trigger_in_its_slot():
    """Audit finding: label boundary, the other half.  spec §3.

    Expectation, hand-computed: the two earlier trades in slot 1000 are real
    history and must stay in the window.  Their wallet is W_B and the trigger's is
    W_A, so n_buyers_12slot = 2 distinct buyers.  The three later trades are W_C
    and must not appear, which would have made it 3.
    """
    events, i = _boundary_case()
    assert n_buyers(events, i, 12) == 2


def test_generator_can_put_several_transactions_in_one_slot():
    """Coverage guard for the generator itself, not for the reference code.

    Expectation, hand-computed: 3 transactions x 2 legs = 6 events, all in slot
    500, transaction indices 0..2, and two distinct packed ix values per
    transaction (1 and 2, since legs are numbered from 1).
    """
    raws = same_slot_stream(n_tx_per_slot=3, n_events_per_tx=2, slot=500)
    assert len(raws) == 6
    assert {r.slot for r in raws} == {500}
    assert sorted({r.tx_index for r in raws}) == [0, 1, 2]
    assert sorted({r.packed_ix for r in raws}) == [1, 2]


# ===========================================================================
# B. SPL transfer — negative inventory
# ===========================================================================

def _transfer_case():
    raws, transfers = transfer_then_sell(buy_units=100_000_000,
                                         transfer_units=60_000_000)
    events = [r.to_event() for r in raws]
    state = TokenState(events[0].x0_lam, events[0].y0_units)
    for e in events:
        state.apply(e)
    return events, transfers, state


def test_transfer_leaves_sender_inventory_untouched_documents_current_incorrect_behavior():
    """Audit finding: SPL transfers are invisible to the ledger.  spec §1.2.

    Expectation, hand-computed: A buys 100_000_000 base units (100 tokens) and
    transfers 60_000_000 away.  A really holds 40 tokens afterwards, but the
    transfer emits no TradeEvent, so `held_units` still reads the full
    100_000_000.  Asserted as-is to keep the error visible.
    """
    events, transfers, state = _transfer_case()
    assert transfers[0].units == 60_000_000
    a = state.wallets[events[0].wallet]
    assert a.held_units == 100_000_000                 # truth is 40_000_000


def test_transfer_recipient_goes_negative_documents_current_incorrect_behavior():
    """Audit finding: SPL transfers, receiving side.  spec §1.2.

    Expectation, hand-computed: B never buys and sells 60_000_000 units, so the
    ledger records held_units = 0 − 60_000_000 = −60_000_000.  This is the only
    trace a transfer leaves, and only when the recipient sells — which is why
    docs/audit_mechanism_prevalence.md calls its count a lower bound.
    """
    events, _, state = _transfer_case()
    b = state.wallets[events[1].wallet]
    assert b.held_units == -60_000_000


def test_overhead_credits_the_sender_for_transferred_tokens_documents_current_incorrect_behavior():
    """Audit finding: transfers inflate OH.  spec §1.2 OH(t).

    Expectation, hand-computed: OH sums held_units/1e6 × (P − cb) over wallets
    with held_units > 0.  B is negative and drops out, so OH is A alone, priced on
    100 tokens rather than the 40 it still owns — exactly 100/40 = 2.5× the honest
    figure.  The ratio is asserted rather than an absolute SOL amount, since it is
    the part that does not depend on the curve constants.
    """
    events, _, state = _transfer_case()
    last = events[-1]
    oh, _, _, n_wallets = state.overhead(last.vsol)
    a = state.wallets[events[0].wallet]
    price = state.spot_price(last.vsol)
    cb = a.cost_basis()
    assert cb is not None and cb < price
    honest = (Decimal(40_000_000) / TOKEN_UNITS) * (price - cb)
    assert oh == (Decimal(100_000_000) / TOKEN_UNITS) * (price - cb)
    assert oh / honest == Decimal("2.5")
    assert n_wallets == 1                              # B excluded by held > 0


# ===========================================================================
# C. Cost basis across a full exit
# ===========================================================================

def _rebuy_states() -> tuple[WalletState, Decimal]:
    """Replays buy → full sell → buy under the spec's basis and a reset basis."""
    events = [r.to_event() for r in exit_then_rebuy()]
    spec_state = WalletState()
    seg_lam, seg_units, held = 0, 0, 0
    for e in events:
        spec_state.apply(e)
        if e.is_buy:
            seg_lam, seg_units, held = seg_lam + e.lam, seg_units + e.units, held + e.units
        else:
            held -= e.units
            if held <= 0:
                seg_lam, seg_units = 0, 0
    reset_basis = Decimal(seg_lam) / (Decimal(seg_units) * THOUSAND)
    return spec_state, reset_basis


def test_cost_basis_after_full_exit_keeps_the_old_buys_documents_current_incorrect_behavior():
    """Audit finding: no reset on a full exit.  spec §1.2 cb(w).

    Expectation, hand-computed.  Two buys, each taking exactly 1_000_000 base
    units (1 token): 1 SOL then 10 SOL, with the whole balance sold in between.
    §1.2 averages every historical buy and never resets, so

        cb = (1e9 + 1e10) / ((1e6 + 1e6) × 1000) = 1.1e10 / 2e9 = 5.5 SOL/token

    while a basis reset at held ≤ 0 would price only the surviving position,

        cb = 1e10 / (1e6 × 1000) = 10 SOL/token.

    The wallet actually paid 10 for the token it holds, so 5.5 understates it and
    OH is overstated by the difference.
    """
    spec_state, reset_basis = _rebuy_states()
    assert spec_state.cost_basis() == Decimal("5.5")
    assert reset_basis == Decimal(10)
    assert reset_basis - spec_state.cost_basis() == Decimal("4.5")


def test_buy_fee_is_not_part_of_the_cost_basis():
    """Audit-adjacent: what the basis is denominated in.  spec §1.1 fee note.

    §1.1 states fees sit OUTSIDE the curve — `sol_amount` is net, with fee and
    creator_fee carried separately.  So cb is built from the amount that reached
    the curve, not from what the wallet spent.

    Expectation, hand-computed: the first buy sends 1e9 lamports through the curve
    for 1e6 base units, giving cb = 1e9/(1e6 × 1000) = 1 SOL/token exactly.  Had
    the 1.25% entry fee been folded in, it would read 1/(1 − 0.0125) = 1.0126582…
    The real outlay is the larger number, so every cost basis in this study is
    low by one fee, and OH correspondingly high.
    """
    first = [r.to_event() for r in exit_then_rebuy()][0]
    w = WalletState()
    w.apply(first)
    assert w.cost_basis() == Decimal(1)
    assert w.cost_basis() != Decimal(1) / (Decimal(1) - Decimal("0.0125"))


# ===========================================================================
# D. ix_index packing
# ===========================================================================

def test_packing_collides_for_inner_at_least_64():
    """Audit finding: ix_index = outer×64 + inner is not injective.  spec §2.3.

    Expectation, hand-computed: (outer=0, inner=64) packs to 0×64 + 64 = 64 and
    (outer=1, inner=0) packs to 1×64 + 0 = 64.  Two distinct instruction
    positions, one key.  Anything that orders or de-duplicates on the packed
    value treats them as the same row.
    """
    a, b = packing_collision_pair()
    assert (a.outer, a.inner) != (b.outer, b.inner)
    assert a.packed_ix == b.packed_ix == IX_PACK_BASE
    assert (a.slot, a.tx_index, a.packed_ix) == (b.slot, b.tx_index, b.packed_ix)


def test_raw_outer_inner_pair_still_orders_the_colliding_events():
    """Audit finding: the information exists upstream.  spec §2.3.

    Expectation, hand-computed: as raw pairs the two are (…,0,64) and (…,1,0), so
    tuple order puts outer=0 first.  The packed column cannot express that, which
    is why docs/audit_mechanism_prevalence.md leaves the outer/inner census to a
    Dune query rather than the local cache.
    """
    a, b = packing_collision_pair()
    assert a.raw_order_key < b.raw_order_key
    assert sorted([b, a], key=lambda r: r.raw_order_key) == [a, b]


def test_null_inner_is_coalesced_to_zero():
    """Audit finding: NULL handling in the packing.  spec §2.3.

    Expectation, hand-computed: the extract writes
    `coalesce(outer,0)*64 + coalesce(inner,0)`, so (outer=3, inner=NULL) packs to
    3 × 64 = 192 — indistinguishable from a genuine (3, 0).
    """
    r = packing_null_inner()
    assert r.inner is None
    assert r.packed_ix == 192


# ===========================================================================
# E. mayhem reparameterisation
# ===========================================================================

def test_launch_k_and_instantaneous_k_disagree_after_mayhem_documents_current_incorrect_behavior():
    """Audit finding: P(t) uses launch k.  spec §1.1 vs §1.2 line 128.

    Expectation, derived algebraically, not read off the code:

        P_launch = x²/k₀      P_instantaneous = x/y
        P_launch / P_inst = x·y / k₀ = k_now / k₀

    The fixture jumps the SOL reserve by 1.5× while leaving the token reserve
    alone, exactly the pattern the KILL gate measured on mayhem pairs (Δvtok
    100%, Δvsol 39–41%).  So the ratio must be the jump factor, 1.5, and
    `spot_price` — which divides by x₀·y₀ — is high by that factor.
    """
    raws = mayhem_reparameterised(jump_factor=1.5)
    r = raws[-1]
    assert r.mayhem
    state = TokenState(r.x0_lam, r.y0_units)
    p_launch = state.spot_price(r.vsol)

    x_sol = Decimal(r.vsol) / Decimal(10) ** 9
    y_tok = Decimal(r.vtok) / TOKEN_UNITS
    p_inst = x_sol / y_tok
    k_now, k0 = x_sol * y_tok, (Decimal(r.x0_lam) / Decimal(10) ** 9) * (
        Decimal(r.y0_units) / TOKEN_UNITS)

    assert abs(p_launch / p_inst - k_now / k0) < Decimal("1e-30")
    assert Decimal("1.4") < p_launch / p_inst < Decimal("1.6")


def test_overhead_differs_between_the_two_price_conventions_documents_current_incorrect_behavior():
    """Audit finding: OH inherits the launch-k error.  spec §1.2 OH(t).

    Expectation, derived: OH is linear in P above each wallet's basis, so a price
    that is 1.5× too high cannot leave OH unchanged.  Asserted as a strict
    inequality plus a floor on the gap rather than a fitted number, because the
    exact OH depends on the fixture's basis, which is not the point being made.
    """
    raws = mayhem_reparameterised(jump_factor=1.5)
    events = [r.to_event() for r in raws]
    state = TokenState(events[0].x0_lam, events[0].y0_units)
    for e in events:
        state.apply(e)
    last = raws[-1]

    oh_launch, _, _, _ = state.overhead(last.vsol)
    p_launch = state.spot_price(last.vsol)
    p_inst = (Decimal(last.vsol) / Decimal(10) ** 9) / (Decimal(last.vtok) / TOKEN_UNITS)
    oh_inst = sum(
        ((Decimal(w.held_units) / TOKEN_UNITS) * (p_inst - w.cost_basis())
         for w in state.wallets.values()
         if w.held_units > 0 and w.cost_basis() is not None and w.cost_basis() < p_inst),
        Decimal(0),
    )
    assert p_launch > p_inst
    assert oh_launch > oh_inst > 0


# ===========================================================================
# F. coverage meta-test
# ===========================================================================

#: Parameters no test varies.  Empty since 2026-08-19: the six that were listed
#: here — mayhem_share, n_tokens, n_wallets, round_share, sell_share,
#: slot_density — are covered by tests/test_generator_parameters.py.  Two of them
#: (mayhem_share, n_wallets) needed a generator builder first, because the config
#: declared them without anything reading them.
UNEXERCISED_PARAMETERS: set[str] = set()


def _parameters_varied_by_tests() -> dict[str, list[str]]:
    """Which test files pass each parameter as a keyword argument.

    Keyword form (`name=`) rather than a bare mention, so that this module's own
    string literals and unpackings like `oh, _, _, n_wallets = ...` do not count
    themselves as coverage.  A self-certifying meta-test would be worthless.

    Measured, never hand-maintained: a parameter added to SyntheticConfig with no
    test moving it shows up here on the next run without anyone updating a map.
    """
    out: dict[str, list[str]] = {}
    for name in sorted(config_field_names()):
        hits = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            body = "\n".join(line for line in path.read_text().splitlines()
                              if f'"{name}"' not in line)
            if re.search(rf"\b{name}=", body):
                hits.append(path.name)
        out[name] = hits
    return out


def test_every_generator_parameter_is_exercised_by_some_test():
    """Meta-test: generator coverage bounds test power.

    The audit's lesson was that a condition the generator cannot build is a
    condition no test can check.  The same holds one step further in: a parameter
    no test moves is a condition no test explores.

    This was xfail(strict) when written on 2026-08-19 — six of eleven parameters
    were never varied.  The xfail is gone because the gap was closed, not because
    the assertion was weakened.
    """
    varied = _parameters_varied_by_tests()
    missing = sorted(name for name, hits in varied.items() if not hits)
    assert not missing, f"never varied: {missing}"


def test_measured_generator_parameter_coverage_is_pinned():
    """Companion to the assertion above: records the coverage so it cannot rot.

    Expectation source: measured by the helper, not guessed.  An earlier draft of
    this file hand-wrote a parameter-to-file map and asserted it; the map was
    wrong (it claimed test_parity.py exercised n_tokens, which it never has, since
    parity runs on cached real data), and this test exists because that draft
    failed.
    """
    varied = _parameters_varied_by_tests()
    assert set(varied) == config_field_names()
    assert {name for name, hits in varied.items() if not hits} == UNEXERCISED_PARAMETERS
    for required in ("n_events_per_tx", "n_tx_per_slot"):
        assert varied[required] == ["test_audit_findings.py"], (
            f"{required} was added for the audit findings and must stay exercised")


def test_generator_builds_every_audited_condition():
    """The five conditions the audit needed, each constructible in one call."""
    assert len(same_slot_stream(2, 2)) == 4
    assert mayhem_reparameterised()[-1].mayhem
    events, transfers = transfer_then_sell()
    assert len(events) == 2 and len(transfers) == 1
    assert len(exit_then_rebuy()) == 3
    assert packing_collision_pair()[0].inner == 64
    assert SyntheticConfig(n_events_per_tx=3, n_tx_per_slot=2).n_events_per_tx == 3
