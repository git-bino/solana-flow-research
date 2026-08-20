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

Neither is "the" rule: spec §1.2 defines a buy-weighted basis and says selling
leaves it alone, and says nothing about a negative balance -- which cannot occur
on-curve at all and only appears because SPL transfers are invisible to the
ledger (2.37% of wallet-token pairs, docs/audit_mechanism_prevalence.md).
Choosing between them is a spec question, so these tests PIN both behaviours
rather than assert one is right.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.oh_reference import THOUSAND, Event, LedgerConfig, WalletStateV2

CFG = LedgerConfig(basis_reset=True, fee_in_basis=True,
                   price_mode="instantaneous", transfer_mode="none")
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


def py_basis(events: list[Event]) -> Decimal | None:
    w = WalletStateV2(cfg=CFG)
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


def test_python_keeps_the_buy_made_while_still_short():
    """MEASURED Python behaviour, pinned.

    Expectation, hand-computed: the reset fires only on a sell, so event 3
    survives alongside event 4: (2e9 + 9e9) / ((5e5 + 2e6) x 1000) = 4.4 SOL/token.
    """
    assert py_basis(_buy_while_short()) == Decimal("4.4")


@pytest.mark.xfail(strict=True, reason=(
    "FINDING (2026-08-20): SQL rolls the basis segment after ANY row leaving "
    "held <= 0, including a buy that leaves the wallet short, and so discards "
    "that buy; Python resets only on a sell and keeps it.  4.5 vs 4.4 here, and "
    "0.914 SOL of oh_a on the real cohort.  spec §1.2 does not decide, so this "
    "is reported rather than repaired."))
def test_the_two_ledgers_agree_on_a_buy_made_while_short():
    """The assertion the parity check needs to pass, stated as the goal."""
    evs = _buy_while_short()
    assert sql_basis(evs) == py_basis(evs)


def test_a_sell_at_the_flat_row_itself_reads_differently():
    """Second, smaller divergence: the basis AT the flattening row.

    Expectation, hand-computed: after the sell the balance is 0.  SQL has not
    rolled the segment yet, so it still reports the old basis of 1 SOL/token;
    Python has already cleared and reports nothing.  The wallet holds nothing
    either way, so OH is unaffected -- pinned because it is the same rule seen
    one row earlier.
    """
    evs = [ev(1, True, 1_000_000_000, 1_000_000), ev(2, False, 0, 1_000_000)]
    assert sql_basis(evs) == Decimal(1)
    assert py_basis(evs) is None
