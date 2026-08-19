"""Phase 1 cost model — the nine checks the brief requires.

Test 1 is the audit's counter-example and the reason the model was rewritten: a
zero-fee round trip with no intervening flow must return exactly nothing.  The
§1.1 formula fails it, which is what `test_legacy_formula_fails_the_counterexample`
records rather than hides.
"""

from __future__ import annotations

import os
from decimal import Decimal, localcontext

import pytest

#: Fallback when a test carries no `prec` marker.
DEFAULT_PREC = 60


@pytest.fixture(autouse=True)
def decimal_precision(request):
    """Run each test at the precision it declares, in a scoped context.

    Phase 1 pinned nothing and inherited whatever the last-imported module had
    set globally, so these tests passed or failed on collection order.  Each one
    now states the precision its tolerance actually needs, measured by sweeping
    `COST_MODEL_PREC_OVERRIDE` rather than guessed, and localcontext keeps that
    choice from escaping the test.
    """
    override = int(os.environ.get("COST_MODEL_PREC_OVERRIDE", "0"))
    marker = request.node.get_closest_marker("prec")
    prec = override or (marker.args[0] if marker else DEFAULT_PREC)
    with localcontext() as ctx:
        ctx.prec = prec
        yield

from src.cost_model import (
    FEE_RATE,
    K_DEFAULT,
    V_P75_SOL,
    breakeven_w,
    breakeven_w_limit_small_q,
    net_pnl,
    net_pnl_path,
    reference_table,
    tokens_bought,
)
from src.curve import breakeven_legacy

ZERO = Decimal(0)


# 1 -------------------------------------------------------------------------

@pytest.mark.prec(18)   # measured: stable from prec >= 18
@pytest.mark.parametrize("x_obs", [Decimal(35), Decimal(50), Decimal(100)])
@pytest.mark.parametrize("q", [Decimal("0.5"), Decimal(1), Decimal(5)])
def test_round_trip_with_no_flow_and_no_fees_is_exactly_zero(x_obs, q):
    """THE AUDIT'S COUNTER-EXAMPLE.  Buy q, sell it straight back: P&L = 0."""
    pnl = net_pnl(x_obs, q, V=0, W=0, fee_rate=0, pf=0)
    assert abs(pnl) < Decimal("1e-15"), f"{pnl} at x={x_obs}, q={q}"


@pytest.mark.prec(16)   # measured: stable from prec >= 16
def test_legacy_formula_fails_the_counterexample():
    """Kept as evidence, not as a fix: the §1.1 formula charges own impact twice.

    At V = 0 and fees = 0 it still returns (1+q/x)² − 1 > 0, where the exact
    reserve path returns 0.
    """
    legacy = breakeven_legacy(Decimal(0), Decimal(1), Decimal(50), fees=Decimal(0))
    assert legacy > 0
    assert legacy == (1 + Decimal(1) / Decimal(50)) ** 2 - 1
    assert abs(net_pnl(50, 1, V=0, W=0, fee_rate=0, pf=0)) < Decimal("1e-15")


# 2 -------------------------------------------------------------------------

@pytest.mark.prec(8)   # measured: stable from prec >= 8
def test_positive_flow_is_profitable_and_monotone_without_fees():
    ws = [Decimal("0.1"), Decimal("0.5"), Decimal(1), Decimal(2), Decimal(5)]
    pnls = [net_pnl(50, 1, V=0, W=w, fee_rate=0, pf=0) for w in ws]
    assert all(p > 0 for p in pnls)
    assert all(a < b for a, b in zip(pnls, pnls[1:]))


# 3 -------------------------------------------------------------------------

@pytest.mark.prec(18)   # measured: stable from prec >= 18
@pytest.mark.parametrize("v", [Decimal("0.4"), Decimal(2), Decimal(10)])
def test_latency_flow_alone_is_not_a_loss(v):
    """V shrinks Δy but the round trip still returns exactly what it cost.

    Latency is only a loss once combined with fees or an adverse W; on its own it
    changes the size of the position, not its P&L.
    """
    pnl = net_pnl(50, 1, V=v, W=0, fee_rate=0, pf=0)
    assert abs(pnl) < Decimal("1e-15"), pnl
    assert tokens_bought(50, 1, V=v) < tokens_bought(50, 1, V=0)


# 4 -------------------------------------------------------------------------

@pytest.mark.prec(8)   # measured: stable from prec >= 8
@pytest.mark.parametrize("q", [Decimal("0.5"), Decimal(1), Decimal(2)])
def test_fees_alone_cost_about_two_fee_rates_of_q(q):
    pnl = net_pnl(50, q, V=0, W=0, fee_rate=FEE_RATE, pf=0)
    assert pnl < 0
    first_order = -2 * FEE_RATE * q
    assert abs(pnl - first_order) < Decimal("0.02") * abs(first_order)


# 5 -------------------------------------------------------------------------

@pytest.mark.prec(40)   # measured: stable from prec >= 40
def test_flow_path_does_not_matter_only_the_net():
    """Constant product: ten increments equal one jump of the same total."""
    total = Decimal(3)
    one = net_pnl_path(50, 1, Decimal("0.4"), [total])
    many = net_pnl_path(50, 1, Decimal("0.4"), [total / 10] * 10)
    assert abs(one - many) < Decimal("1e-40")
    assert abs(one - net_pnl(50, 1, V=Decimal("0.4"), W=total)) < Decimal("1e-40")


@pytest.mark.prec(42)   # measured: stable from prec >= 42
def test_path_with_flow_reversals_still_only_depends_on_the_net():
    mixed = [Decimal(5), Decimal(-4), Decimal(3), Decimal(-1)]      # net 3
    assert abs(net_pnl_path(50, 1, ZERO, mixed)
               - net_pnl(50, 1, V=0, W=Decimal(3))) < Decimal("1e-40")


# 6 -------------------------------------------------------------------------

@pytest.mark.prec(22)   # measured: stable from prec >= 22
@pytest.mark.parametrize("x_obs", [Decimal(35), Decimal(50), Decimal(100)])
@pytest.mark.parametrize("v", [ZERO, V_P75_SOL])
def test_small_q_limit_is_the_pure_fee_price_move(x_obs, v):
    """As q → 0, breakeven W → (x_obs+V)·f/(1−f): the move that just clears fees."""
    got = breakeven_w(x_obs, Decimal("1e-9"), V=v, pf=0)
    want = breakeven_w_limit_small_q(x_obs, v)
    assert abs(got - want) / want < Decimal("1e-8"), f"{got} vs {want}"


# 7 -------------------------------------------------------------------------

@pytest.mark.prec(12)   # measured: stable from prec >= 12
def test_breakeven_w_substituted_back_gives_zero_pnl_everywhere():
    """Every reference cell: net_pnl at the solved W must be zero to 1e-9 SOL."""
    worst = ZERO
    for r in reference_table():
        pnl = net_pnl(r["x_obs"], r["q"], V=r["V"], W=r["breakeven_w"], pf=r["pf"])
        worst = max(worst, abs(pnl))
    assert worst < Decimal("1e-9"), worst


# 8 -------------------------------------------------------------------------

@pytest.mark.prec(8)   # measured: stable from prec >= 8
@pytest.mark.parametrize("x_obs", [Decimal(35), Decimal(50), Decimal(70), Decimal(100)])
def test_breakeven_w_increases_with_order_size(x_obs):
    ws = [breakeven_w(x_obs, q) for q in [Decimal("0.5"), Decimal(1), Decimal(2), Decimal(5)]]
    assert all(a < b for a, b in zip(ws, ws[1:])), ws


@pytest.mark.prec(8)   # measured: stable from prec >= 8
@pytest.mark.parametrize("q", [Decimal("0.5"), Decimal(1), Decimal(2), Decimal(5)])
def test_breakeven_w_increases_with_depth(q):
    ws = [breakeven_w(x, q) for x in [Decimal(35), Decimal(50), Decimal(70), Decimal(100)]]
    assert all(a < b for a, b in zip(ws, ws[1:])), ws


# 9 -------------------------------------------------------------------------

def _legacy_dv(x_obs: Decimal, q: Decimal, v: Decimal) -> Decimal:
    """The ΔV the legacy formula implies, exactly as Phase 3a used it.

    BE is a return; §7 (ii) turns it into a flow through (1+ΔV/x)² − 1 = BE, so
    ΔV = x·(√(1+BE) − 1).  fees there is the two-sided 0.025.
    """
    be = breakeven_legacy(v, q, x_obs, fees=Decimal("0.025"))
    return x_obs * ((1 + be).sqrt() - 1)


@pytest.mark.prec(8)   # measured: stable from prec >= 8
def test_legacy_overstates_the_required_flow_on_every_reference_cell():
    """Records the size of the error rather than asserting a particular ratio."""
    ratios = []
    for r in reference_table():
        if r["pf"] != 0:
            continue                      # the legacy formula has no pf term
        new = r["breakeven_w"]
        old = _legacy_dv(r["x_obs"], r["q"], r["V"])
        ratios.append(old / new)
    assert len(ratios) == 32
    assert all(x > 1 for x in ratios), "legacy did not overstate somewhere"
    # No tighter bound is asserted.  An earlier draft of this test demanded
    # min(ratio) > 1.5 and failed at 1.371 (x = 100, q = 0.5, V = 0) -- that was a
    # guessed expectation, not a measured one.  The measured span is recorded in
    # docs/phase1_cost_model.md instead: 1.371 to 10.942, median 3.131.
    assert max(ratios) > 10
