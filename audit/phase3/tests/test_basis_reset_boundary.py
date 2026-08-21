"""Where the SQL and Python basis-reset rules part company.

Diagnosis of the `oh_a` parity gap (docs/oh_parity_diagnosis.md, 2026-08-20).
A local emulation of `sql/extract_v2.sql`'s ledger reproduces its `oh_a` to
1e-9 on both differing bursts, so the SQL semantics below are measured, not
assumed:

    SQL      seg_id = count of EARLIER rows with held <= 0, so the segment rolls
             on the row AFTER the balance goes non-positive -- whatever the side
             of the trade that left it there.
    Python   WalletStateV2.apply_trade checks `held <= 0` only in the SELL
             branch, so a buy that leaves the wallet still short does not reset.

spec §1.2 defines a buy-weighted basis and says selling leaves it alone, and says
nothing about a negative balance -- which cannot occur on-curve at all and only
appears because SPL transfers are invisible to the ledger (2.37% of wallet-token
pairs, docs/audit_mechanism_prevalence.md).  decisions.md settled it on
2026-08-20: a buy made while short opens a NEW position, which is what the SQL
ledger already did, so the Python reference was aligned to it.  The old rule
survives behind `legacy_negative_held` and is pinned below.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.oh_reference import THOUSAND, Event, LedgerConfig, WalletStateV2

CFG = LedgerConfig(basis_reset=True, fee_in_basis=True,
                   price_mode="instantaneous", transfer_mode="none")
LEGACY = LedgerConfig(basis_reset=True, fee_in_basis=True,
                      price_mode="instantaneous", transfer_mode="none",
                      legacy_negative_held=True)
MINT = "M" + "z" * 43
W = "W" + "y" * 43


def ev(n: int, buy: bool, lam: int, units: int) -> Event:
    return Event(mint=MINT, slot=500 + n, tx_index=0, ix_index=1, wallet=W,
                 is_buy=buy, lam=lam, units=units, vsol=31_000_000_000,
                 x0_lam=30_000_000_000, y0_units=1_073_000_000_000_000)


def sql_basis(events: list[Event]) -> Decimal | None:
    """The SQL ledger's basis after `events`, emulated exactly.

    `flats_before` is the running count of earlier rows with held <= 0, which is
    what `seg_id` computes with `ROWS BETWEEN UNBOUNDED PRECEDING AND 1
    PRECEDING`.  The segment sums restart when that count changes.
    """
    held = flats_before = cur_seg = seg_lam = seg_units = 0
    for e in events:
        if flats_before != cur_seg:
            cur_seg, seg_lam, seg_units = flats_before, 0, 0
        if e.is_buy:
            held += e.units
            seg_lam += e.lam
            seg_units += e.units
        else:
            held -= e.units
        if held <= 0:
            flats_before += 1
    return Decimal(seg_lam) / (Decimal(seg_units) * THOUSAND) if seg_units else None


def py_basis(events: list[Event], cfg: LedgerConfig = CFG) -> Decimal | None:
    w = WalletStateV2(cfg=cfg)
    for e in events:
        w.apply_trade(e)
    return w.cost_basis()


# --- cases where the two agree ---------------------------------------------

def test_plain_buys_agree():
    """No flat point: both average every buy.

    Expectation, hand-computed: 1e9 + 3e9 lamports over 2e6 base units gives
    4e9 / (2e6 x 1000) = 2 SOL/token.
    """
    evs = [ev(1, True, 1_000_000_000, 1_000_000), ev(2, True, 3_000_000_000, 1_000_000)]
    assert sql_basis(evs) == py_basis(evs) == Decimal(2)


def test_exact_flat_then_rebuy_agrees():
    """held lands exactly on 0, then a buy: both start a fresh basis.

    Expectation, hand-computed: the surviving position is the 10 SOL buy for
    1e6 units, so 1e10 / (1e6 x 1000) = 10 SOL/token, whichever rule applies.
    """
    evs = [ev(1, True, 1_000_000_000, 1_000_000),
           ev(2, False, 1_000_000_000, 1_000_000),
           ev(3, True, 10_000_000_000, 1_000_000)]
    assert sql_basis(evs) == py_basis(evs) == Decimal(10)


def test_two_consecutive_sells_to_zero_then_buy_agrees():
    """Several flat points in a row still leave one surviving segment."""
    evs = [ev(1, True, 2_000_000_000, 2_000_000),
           ev(2, False, 0, 1_000_000),
           ev(3, False, 0, 1_000_000),
           ev(4, True, 7_000_000_000, 1_000_000)]
    assert sql_basis(evs) == py_basis(evs) == Decimal(7)


def test_held_is_integer_on_both_sides():
    """Balances are base units; neither side may drift into float."""
    w = WalletStateV2(cfg=CFG)
    w.apply_trade(ev(1, True, 1_000_000_000, 1_000_003))
    w.apply_trade(ev(2, False, 0, 3))
    assert isinstance(w.held, int) and w.held == 1_000_000


# --- the case that differs --------------------------------------------------

def _buy_while_short() -> list[Event]:
    """Sell into a negative balance, buy while still short, then buy back to positive.

    This is the shape found on both diverging bursts.  A negative balance is
    itself an artefact: on-curve it is impossible, and it appears only where an
    SPL transfer moved tokens the ledger never saw.
    """
    return [ev(1, True, 1_000_000_000, 1_000_000),    # held +1e6
            ev(2, False, 0, 3_000_000),               # held -2e6, flat point
            ev(3, True, 2_000_000_000, 500_000),      # held -1.5e6, STILL short
            ev(4, True, 9_000_000_000, 2_000_000)]    # held +5e5, positive again


def test_sql_drops_the_buy_made_while_still_short():
    """MEASURED SQL behaviour, pinned.

    Expectation, hand-computed from the emulation: event 3 leaves held at
    -1.5e6, so it counts as a flat point and event 4 opens a new segment.  Only
    event 4 survives in the basis: 9e9 / (2e6 x 1000) = 4.5 SOL/token.
    """
    assert sql_basis(_buy_while_short()) == Decimal("4.5")


def test_legacy_flag_keeps_the_buy_made_while_still_short():
    """The pre-2026-08-20 Python rule, retained behind `legacy_negative_held`.

    Expectation, hand-computed: with the reset firing only on a sell, event 3
    survives alongside event 4: (2e9 + 9e9) / ((5e5 + 2e6) x 1000) = 4.4 SOL/token.
    Kept so the old numbers stay reproducible, not because they are right.
    """
    assert py_basis(_buy_while_short(), LEGACY) == Decimal("4.4")


def test_the_two_ledgers_agree_on_a_buy_made_while_short():
    """Was xfail(strict) on 2026-08-20; passes since the Python rule was aligned.

    decisions.md settled that a buy made while short opens a new position, which
    is what the SQL ledger already did.  Both now return 4.5 SOL/token.
    """
    evs = _buy_while_short()
    assert sql_basis(evs) == py_basis(evs) == Decimal("4.5")


def test_the_basis_at_the_flattening_row_now_agrees_too():
    """The second, smaller divergence, closed by the same change.

    Expectation, hand-computed: after the sell the balance is 0.  The reset it
    implies belongs to the NEXT row, so both sides still report the old basis of
    1 SOL/token at this row.  The wallet holds nothing, so OH is unaffected
    either way -- pinned because it is the same rule one row earlier.
    """
    evs = [ev(1, True, 1_000_000_000, 1_000_000), ev(2, False, 0, 1_000_000)]
    assert sql_basis(evs) == py_basis(evs) == Decimal(1)
    assert py_basis(evs, LEGACY) is None
