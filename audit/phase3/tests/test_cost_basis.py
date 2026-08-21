"""Cost basis and the OH invariants — spec §1.2, §7 Phase 2, §8.2 requirement 8.

§1.2 is explicit and easy to get subtly wrong:

    cb(w) = Σ(SOL_in) / Σ(tokens_received)   [FIFO биш, weighted average]
    Sell гарвал tokens_received-ээс хасаж, cost basis-ийг хэвээр үлдээнэ.

so selling moves the holding and nothing else, and a wallet that sold everything
and bought back still averages over *all* its buys.  §7 Phase 2 adds the
invariants: OH ≥ 0 always, 0 ≤ OH_conc ≤ 1.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.curve import X0_LAMPORTS, Y0_UNITS
from src.oh_reference import Event, TokenState, WalletState
from tests.synthetic import SyntheticConfig, make_token

SOL = 1_000_000_000
TOK = 1_000_000


def ev(wallet, is_buy, lam, units, slot=1, tx=0, ix=0, vsol=X0_LAMPORTS) -> Event:
    return Event(mint="M", slot=slot, tx_index=tx, ix_index=ix, wallet=wallet,
                 is_buy=is_buy, lam=lam, units=units, vsol=vsol,
                 x0_lam=X0_LAMPORTS, y0_units=Y0_UNITS)


def test_sell_leaves_cost_basis_untouched_and_reduces_holding():
    """§1.2: 'Sell гарвал tokens_received-ээс хасаж, cost basis-ийг хэвээр үлдээнэ.'"""
    w = WalletState()
    w.apply(ev("a", True, 2 * SOL, 1000 * TOK))
    cb_before, held_before = w.cost_basis(), w.held_units
    w.apply(ev("a", False, 1 * SOL, 400 * TOK))
    assert w.cost_basis() == cb_before
    assert w.held_units == held_before - 400 * TOK
    assert w.buy_lam == 2 * SOL and w.buy_units == 1000 * TOK


def test_repeat_buys_average_by_weight():
    """§1.2: weighted average over buys, not FIFO and not last-price."""
    w = WalletState()
    w.apply(ev("a", True, 1 * SOL, 1000 * TOK))     # 0.001 SOL/token
    w.apply(ev("a", True, 3 * SOL, 1000 * TOK))     # 0.003 SOL/token
    # (1 + 3) SOL over 2000 tokens = 0.002 SOL/token
    assert w.cost_basis() == Decimal(4 * SOL) / (Decimal(2000 * TOK) * 1000)
    assert w.cost_basis() == Decimal("0.002")


def test_cost_basis_after_sell_then_rebuy_uses_all_buys():
    """A wallet that sold out and bought back averages over *every* buy (§1.2)."""
    w = WalletState()
    w.apply(ev("a", True, 1 * SOL, 1000 * TOK))
    w.apply(ev("a", False, 1 * SOL, 1000 * TOK))    # fully out
    assert w.held_units == 0
    w.apply(ev("a", True, 2 * SOL, 1000 * TOK))
    assert w.held_units == 1000 * TOK
    assert w.cost_basis() == Decimal(3 * SOL) / (Decimal(2000 * TOK) * 1000)


def test_fully_sold_wallet_is_excluded_from_oh():
    """OH sums over holders; a wallet at zero contributes nothing (§1.2)."""
    # amounts sized to this curve: at x = 30 the spot price is ~2.8e-8 SOL/token,
    # so 1 SOL buys ~35M tokens.  Using round numbers like 1000 tokens/SOL would
    # put the cost basis four orders of magnitude above any price and no wallet
    # would ever qualify -- the test would pass for the wrong reason.
    state = TokenState(X0_LAMPORTS, Y0_UNITS)
    state.apply(ev("holder", True, 1 * SOL, 35_000_000 * TOK))
    state.apply(ev("gone", True, 1 * SOL, 35_000_000 * TOK))
    with_both = state.overhead(60 * SOL)
    state.apply(ev("gone", False, 1 * SOL, 35_000_000 * TOK))
    with_one = state.overhead(60 * SOL)
    assert with_both[3] == 2 and with_one[3] == 1
    assert with_one[0] < with_both[0]


def test_wallet_that_only_sold_has_no_cost_basis_and_is_skipped():
    """buy_units = 0 means cb is undefined; such a wallet cannot enter OH (§1.2)."""
    w = WalletState()
    w.apply(ev("a", False, 1 * SOL, 500 * TOK))
    assert w.cost_basis() is None
    state = TokenState(X0_LAMPORTS, Y0_UNITS)
    state.apply(ev("a", False, 1 * SOL, 500 * TOK))
    assert state.overhead(60 * SOL)[3] == 0


def test_oh_is_never_negative_and_conc_is_a_share():
    """§7 Phase 2: OH ≥ 0 үргэлж, 0 ≤ OH_conc ≤ 1."""
    events = make_token(SyntheticConfig(n_events=120, seed=99), token_index=2)
    state = TokenState(events[0].x0_lam, events[0].y0_units)
    for e in events:
        state.apply(e)
        oh, ratio, conc, _ = state.overhead(e.vsol)
        assert oh >= 0
        assert ratio >= 0
        assert 0 <= conc <= 1


def test_oh_zero_gives_conc_zero():
    """OH = 0 leaves concentration undefined; §1.2's bound forces 0, and the SQL
    was changed to match this (docs/phase0_extract_schema.md, FIX 2)."""
    state = TokenState(X0_LAMPORTS, Y0_UNITS)
    # one wallet, bought far above the price at which OH is evaluated
    state.apply(ev("a", True, 100 * SOL, 1 * TOK))
    oh, ratio, conc, n = state.overhead(X0_LAMPORTS)
    assert (oh, ratio, conc, n) == (0, 0, 0, 0)


def test_holdings_never_exceed_what_was_bought():
    """§7 Phase 2 sanity: Σ tokens_held ≤ total bought, per wallet and in total."""
    events = make_token(SyntheticConfig(n_events=150, seed=7), token_index=1)
    state = TokenState(events[0].x0_lam, events[0].y0_units)
    for e in events:
        state.apply(e)
    for wallet in state.wallets.values():
        assert 0 <= wallet.held_units <= wallet.buy_units
