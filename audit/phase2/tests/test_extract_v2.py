"""v2 conventions: the behaviour `sql/extract_v2.sql` is written to produce.

Paired with `tests/test_audit_findings.py`, which pins what v1 does today.  Those
tests are NOT deleted and NOT edited: v1 is what produced `flow.burst`, and the
audit trail needs both readings side by side until the re-extract lands.

The SQL is never executed here — the API has been returning 402 since
2026-08-19.  What is tested is the SEMANTICS the SQL encodes, expressed in
`src/oh_reference`'s v2 path and in `src/features_reference`, so that a later
parity run has something to disagree with.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.extract_schema import CANON, CANON_V2, KEY_V2, V2_COLUMNS
from src.oh_reference import (
    TOKEN_UNITS,
    Event,
    LedgerConfig,
    TokenStateV2,
    TransferIn,
)
from tests.synthetic import (
    exit_then_rebuy,
    mayhem_reparameterised,
    transfer_then_sell,
    trigger_with_same_slot_neighbours,
)

V2_A = LedgerConfig(basis_reset=True, fee_in_basis=True,
                    price_mode="instantaneous", transfer_mode="exclude")
V2_B = LedgerConfig(basis_reset=True, fee_in_basis=True,
                    price_mode="instantaneous", transfer_mode="inherit")


# ===========================================================================
# A1 — label boundary, the v2 side
# ===========================================================================

def _forward_slot_window(events, i, tau):
    """§4.2 under v2: the window is (s, s+tau], so slot s contributes nothing.

    Written out rather than imported because this is the definition the SQL's
    `RANGE BETWEEN 1 FOLLOWING AND tau FOLLOWING` encodes, and the point of the
    test is to state it independently of the v1 reference.
    """
    s = events[i].slot
    return sum(e.signed_lam for e in events if s < e.slot <= s + tau)


def test_v2_forward_flow_excludes_the_triggers_own_slot_correct_behavior():
    """Fix 1.  spec §4.2 (v1.4), window (s, s+τ].

    Expectation, hand-computed: the fixture puts two trades before the trigger,
    the trigger, and three after — all in slot 1000, nothing in 1001..1012.  A
    window that opens at s+1 therefore sees nothing, so the label is 0 SOL.  The
    v1 row boundary returns 3 × 0.5 = 1.5, which
    test_audit_findings.py::test_forward_flow_excludes_trades_in_the_triggers_own_slot
    still records as an xfail.
    """
    raws, i = trigger_with_same_slot_neighbours(n_before=2, n_after=3,
                                                slot=1000, lam=500_000_000)
    events = [r.to_event() for r in raws]
    assert _forward_slot_window(events, i, 12) == 0


def test_v2_forward_window_still_sees_a_later_slot():
    """Guard on the test above: the window is empty by content, not by definition.

    Expectation, hand-computed: append one 0.7 SOL buy in slot 1003, three slots
    past the trigger and inside a 12-slot window, and the label must become
    exactly 700,000,000 lamports.  Without this, a window function that returned
    zero unconditionally would pass the previous test.
    """
    raws, i = trigger_with_same_slot_neighbours(n_before=1, n_after=1,
                                                slot=1000, lam=500_000_000)
    events = [r.to_event() for r in raws]
    assert _forward_slot_window(events, i, 12) == 0
    tail = events[-1]
    later = events + [Event(mint=tail.mint, slot=1003, tx_index=99, ix_index=1,
                            wallet="Wlater", is_buy=True, lam=700_000_000, units=1,
                            vsol=tail.vsol, x0_lam=tail.x0_lam,
                            y0_units=tail.y0_units)]
    assert _forward_slot_window(later, i, 12) == 700_000_000
    assert _forward_slot_window(later, i, 2) == 0            # 1003 is outside (s, s+2]


# ===========================================================================
# B — transfers, the v2 side
# ===========================================================================

def _transfer_state(cfg: LedgerConfig) -> TokenStateV2:
    raws, transfers = transfer_then_sell(buy_units=100_000_000,
                                         transfer_units=60_000_000)
    events = [r.to_event() for r in raws]
    st = TokenStateV2(events[0].x0_lam, events[0].y0_units, cfg=cfg)
    st.apply(events[0])                                   # A buys 100
    xf = transfers[0]
    st.apply_transfer(TransferIn(xf.mint, xf.slot, xf.tx_index, 0, 1,
                                 xf.sender, xf.recipient, xf.units))
    st.apply(events[1])                                   # B sells 60
    return st, events, raws


@pytest.mark.parametrize("cfg", [V2_A, V2_B], ids=["variant_a", "variant_b"])
def test_v2_transfer_moves_the_balance_off_the_sender_correct_behavior(cfg):
    """Fix 3.  spec §1.2 — the sender's balance falls, its basis does not.

    Expectation, hand-computed: A buys 100_000_000 units and sends 60_000_000
    away, so A holds 40_000_000 — the truth v1 could not see, where `held_units`
    stayed at 100_000_000.
    """
    st, events, _ = _transfer_state(cfg)
    a = st.wallets[events[0].wallet]
    assert a.held == 40_000_000


@pytest.mark.parametrize("cfg", [V2_A, V2_B], ids=["variant_a", "variant_b"])
def test_v2_transfer_recipient_does_not_go_negative_correct_behavior(cfg):
    """Fix 3, receiving side.

    Expectation, hand-computed: B receives 60_000_000 and sells exactly that, so
    it ends at 0 rather than v1's −60_000_000.
    """
    st, events, _ = _transfer_state(cfg)
    b = st.wallets[events[1].wallet]
    assert b.held == 0


def test_v2_variant_a_keeps_transferred_tokens_out_of_overhead():
    """Fix 3, variant (a).

    Expectation, hand-computed: A bought 100_000_000 and transferred 60_000_000
    away.  Under (a) only bought-and-still-held tokens are priced; a sell retires
    the bought part first, and A never sold, so A's OH-eligible balance is
    100_000_000 − 60_000_000 = 40_000_000 — the honest number.  B holds nothing.
    """
    st, events, raws = _transfer_state(V2_A)
    a = st.wallets[events[0].wallet]
    assert a.oh_units() == 40_000_000
    assert st.wallets[events[1].wallet].oh_units() == 0
    last = raws[-1]
    oh, _, _, n = st.overhead(last.vsol, last.vtok)
    price = st.spot_price(last.vsol, last.vtok)
    cb = a.cost_basis()
    assert n == 1
    assert oh == (Decimal(40_000_000) / TOKEN_UNITS) * (price - cb)


def test_v2_variant_b_prices_transferred_tokens_at_the_senders_basis():
    """Fix 3, variant (b).

    Expectation, hand-computed: B receives 60_000_000 units carrying A's basis
    and immediately sells all of them, so B ends flat and contributes nothing.
    A holds 40_000_000 at its own basis.  The two variants therefore agree on
    THIS fixture, which is the point: they differ only while transferred tokens
    are still held.
    """
    st_b, events, raws = _transfer_state(V2_B)
    st_a, _, _ = _transfer_state(V2_A)
    last = raws[-1]
    oh_b = st_b.overhead(last.vsol, last.vtok)[0]
    oh_a = st_a.overhead(last.vsol, last.vtok)[0]
    assert st_b.wallets[events[1].wallet].held == 0
    assert oh_a == oh_b


def test_v2_variants_diverge_while_transferred_tokens_are_held():
    """The fixture above cannot separate (a) from (b); this one can.

    Expectation, hand-computed: if B never sells, variant (a) prices B's
    60_000_000 at nothing (they were not bought) while variant (b) prices them at
    A's basis.  So OH under (b) must exceed OH under (a) by exactly B's share.
    """
    raws, transfers = transfer_then_sell(buy_units=100_000_000,
                                         transfer_units=60_000_000)
    events = [r.to_event() for r in raws]
    xf = transfers[0]
    out = {}
    for tag, cfg in (("a", V2_A), ("b", V2_B)):
        st = TokenStateV2(events[0].x0_lam, events[0].y0_units, cfg=cfg)
        st.apply(events[0])
        st.apply_transfer(TransferIn(xf.mint, xf.slot, xf.tx_index, 0, 1,
                                     xf.sender, xf.recipient, xf.units))
        out[tag] = st.overhead(raws[0].vsol, raws[0].vtok)[0]
    assert out["b"] > out["a"] > 0


# ===========================================================================
# C — cost basis, the v2 side
# ===========================================================================

def test_v2_cost_basis_resets_after_a_full_exit_correct_behavior():
    """Fix 4.  spec §1.2 as amended.

    Expectation, hand-computed and identical to the v1 pair's arithmetic: buy 1
    SOL for one token, sell it all, buy again for 10 SOL.  With a reset the basis
    prices only the surviving position, 1e10/(1e6 × 1000) = 10 SOL/token.
    Without one it averages to 5.5, which
    test_audit_findings.py::test_cost_basis_after_full_exit_keeps_the_old_buys...
    still records.
    """
    events = [r.to_event() for r in exit_then_rebuy()]
    cfg = LedgerConfig(basis_reset=True)
    st = TokenStateV2(events[0].x0_lam, events[0].y0_units, cfg=cfg)
    for e in events:
        st.apply(e)
    assert st.wallets[events[0].wallet].cost_basis() == Decimal(10)


def test_v2_buy_fee_enters_the_cost_basis_correct_behavior():
    """Fix 5.  spec §1.1 fee note, applied to §1.2's cb(w).

    Expectation, hand-computed: 1e9 lamports through the curve plus a 12_500_000
    lamport fee (1.25%) over 1e6 base units gives
    (1e9 + 1.25e7) / (1e6 × 1000) = 1.0125 SOL/token, against v1's 1.0 exactly.
    """
    first = [r.to_event() for r in exit_then_rebuy()][0]
    st = TokenStateV2(first.x0_lam, first.y0_units,
                      cfg=LedgerConfig(fee_in_basis=True))
    st.apply(first, fee_lam=12_500_000)
    assert st.wallets[first.wallet].cost_basis() == Decimal("1.0125")

    st_net = TokenStateV2(first.x0_lam, first.y0_units, cfg=LedgerConfig())
    st_net.apply(first, fee_lam=12_500_000)
    assert st_net.wallets[first.wallet].cost_basis() == Decimal(1)


# ===========================================================================
# E — pricing, the v2 side
# ===========================================================================

def test_v2_price_uses_the_live_reserves_correct_behavior():
    """Fix 6.  spec §1.1 as amended: P = x/y.

    Expectation, derived: after a reparameterisation that multiplies the SOL
    reserve by 1.5 and leaves the token reserve, x·y is 1.5·k₀.  The launch-k
    price is therefore 1.5× the live one, and only the live one reflects what a
    trade on that curve would pay.
    """
    raws = mayhem_reparameterised(jump_factor=1.5)
    last = raws[-1]
    st_inst = TokenStateV2(last.x0_lam, last.y0_units,
                           cfg=LedgerConfig(price_mode="instantaneous"))
    st_launch = TokenStateV2(last.x0_lam, last.y0_units,
                             cfg=LedgerConfig(price_mode="launch"))
    p_inst = st_inst.spot_price(last.vsol, last.vtok)
    p_launch = st_launch.spot_price(last.vsol)
    assert Decimal("1.4") < p_launch / p_inst < Decimal("1.6")


def test_v2_launch_price_is_still_available_for_the_mayhem_gap():
    """`p_launch` survives as a column so the gap stays measurable, not lost."""
    assert "p_launch" in V2_COLUMNS and "p_t" in V2_COLUMNS


# ===========================================================================
# Schema
# ===========================================================================

def test_v2_schema_drops_only_the_packed_index_and_renames_the_oh_family():
    """The brief: start from v1's 60 columns, remove `ix_index`, add the rest.

    The four `oh*` columns are not dropped but split per transfer variant, which
    is why they show up as removals against v1's names.
    """
    removed = set(CANON.names) - set(V2_COLUMNS)
    assert removed == {"ix_index", "oh", "oh_ratio", "oh_conc", "oh_n_wallets"}
    for base in ("oh", "oh_ratio", "oh_conc", "oh_n_wallets"):
        assert f"{base}_a" in V2_COLUMNS and f"{base}_b" in V2_COLUMNS
    assert len(CANON_V2.names) == 80


def test_v2_key_is_the_raw_instruction_pair():
    """Fix 2: nothing downstream may key on a packed index."""
    assert KEY_V2 == ["token_mint", "slot", "tx_index",
                      "outer_ix_index", "inner_ix_index"]
    assert "ix_index" not in CANON_V2.names


def test_v2_schema_matches_the_sql_it_documents():
    """The column list is derived from sql/extract_v2.sql, not maintained beside it.

    Parsed with comments stripped BEFORE splitting — the defect that once made a
    parser miss five columns and once cut a query in half at a semicolon inside a
    comment.
    """
    import re
    from pathlib import Path
    sql = Path(__file__).resolve().parent.parent / "sql" / "extract_v2.sql"
    text = sql.read_text()
    body = text[text.rindex("\nSELECT\n") + 8: text.rindex("\nFROM bursts b")]
    body = "\n".join(re.sub(r"--.*$", "", line) for line in body.split("\n"))
    cols, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            cols.append(cur)
            cur = ""
        else:
            cur += ch
    cols.append(cur)
    names = []
    for c in cols:
        c = " ".join(c.split())
        if not c:
            continue
        m = re.search(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)$", c)
        names.append(m.group(1) if m else c.split(".")[-1])
    assert sorted(names) == sorted(V2_COLUMNS)


def test_v2_ledger_with_transfers_off_matches_the_v1_inventory():
    """The parity the brief asks for: the flag off must reproduce the old ledger.

    Expectation: with `transfer_mode='none'` the transfer is not applied at all,
    so the sender keeps credit for tokens it sent and the recipient goes negative
    — exactly the v1 numbers pinned in test_audit_findings.py.
    """
    raws, transfers = transfer_then_sell(buy_units=100_000_000,
                                         transfer_units=60_000_000)
    events = [r.to_event() for r in raws]
    st = TokenStateV2(events[0].x0_lam, events[0].y0_units,
                      cfg=LedgerConfig(transfer_mode="none"))
    st.apply(events[0])
    xf = transfers[0]
    st.apply_transfer(TransferIn(xf.mint, xf.slot, xf.tx_index, 0, 1,
                                 xf.sender, xf.recipient, xf.units))
    st.apply(events[1])
    assert st.wallets[events[0].wallet].held == 100_000_000
    assert st.wallets[events[1].wallet].held == -60_000_000
