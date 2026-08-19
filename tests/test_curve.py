"""Unit tests for the curve math (spec §1.1) and the causality guarantees of
the reconstruction interface (spec §6.1, §8.4.1/§8.4.2/§8.4.5).

These are pure-math tests: no data access, no network.  The equivalent checks
against real on-chain state are validation checks 1, 2 and 5 in
`src/validate_phase0.py`.
"""

from __future__ import annotations

import random
from decimal import Decimal, localcontext

import pytest

from src.curve import (
    K_HUMAN,
    K_UNITS,
    LAMPORTS_PER_SOL,
    TOKEN_UNITS_PER_TOKEN,
    X0_LAMPORTS,
    X0_SOL,
    Y0_UNITS,
    CurveEvent,
    CurveState,
    CurveViolation,
    FloatCurveState,
    OrderingViolation,
    Side,
    SolAmountConvention,
    avg_price_buy,
    curve_progress,
    curve_sol_amount,
    latency_cost,
    lamports_to_sol,
    own_slippage,
    replay_token,
    round_trip_breakeven,
    sol_out_for_tokens_in,
    spot_price,
    spot_price_from_reserves,
    tokens_out_for_sol_in,
)


@pytest.fixture(autouse=True)
def _curve_decimal_precision():
    """40 digits for this module only.

    This used to be `getcontext().prec = 40` at import, which mutates the
    thread-global decimal context and leaks into every other test module.  It
    made tests/test_cost_model.py pass or fail depending on collection order
    (docs/audit_findings_tests.md).  localcontext restores the previous context
    on exit, so nothing outside this module sees it.
    """
    with localcontext() as ctx:
        ctx.prec = 40
        yield


NET = SolAmountConvention.NET_OF_FEE
GROSS = SolAmountConvention.GROSS_INCLUDES_FEE


def buy(sol_lamports: int, tokens: int, slot: int, tx: int = 0, ix: int = 0) -> CurveEvent:
    return CurveEvent(slot, tx, ix, Side.BUY, sol_lamports, tokens)


def sell(sol_lamports: int, tokens: int, slot: int, tx: int = 0, ix: int = 0) -> CurveEvent:
    return CurveEvent(slot, tx, ix, Side.SELL, sol_lamports, tokens)


# --- constants and invariant ---------------------------------------------

def test_initial_state_satisfies_invariant():
    assert X0_LAMPORTS * Y0_UNITS == K_UNITS
    assert X0_SOL * Decimal(Y0_UNITS) / TOKEN_UNITS_PER_TOKEN == K_HUMAN
    state = CurveState()
    assert (state.x, state.y) == (X0_LAMPORTS, Y0_UNITS)


def test_spot_price_forms_agree_on_exact_invariant_state():
    # On a state that exactly satisfies x*y=k, P = x^2/k and P = x/y coincide.
    x = 50 * LAMPORTS_PER_SOL
    y = K_UNITS // x
    from_invariant = spot_price(lamports_to_sol(x))
    from_reserves = spot_price_from_reserves(x, y)
    assert abs(from_invariant - from_reserves) / from_invariant < Decimal("1e-15")


def test_migration_threshold_is_curve_progress_one():
    # spec §1.1: 85 real SOL -> x = 115 -> curve fully progressed.
    assert curve_progress(Decimal(115)) == 1
    assert curve_progress(X0_SOL) == 0


# --- closed-form formulas ------------------------------------------------

def test_tokens_out_matches_closed_form():
    x, y = X0_LAMPORTS, Y0_UNITS
    q = 2 * LAMPORTS_PER_SOL
    got = tokens_out_for_sol_in(x, y, q)
    want = y - (x * y) // (x + q)      # Δy = y − k/(x+q)
    assert got == want
    # average price paid agrees with x(x+q)/k to integer-truncation accuracy
    avg_realised = (Decimal(q) / LAMPORTS_PER_SOL) / (Decimal(got) / TOKEN_UNITS_PER_TOKEN)
    avg_formula = avg_price_buy(lamports_to_sol(x), lamports_to_sol(q))
    assert abs(avg_realised - avg_formula) / avg_formula < Decimal("1e-12")


def test_sell_is_inverse_of_buy_up_to_one_lamport():
    x, y = X0_LAMPORTS, Y0_UNITS
    q = 3 * LAMPORTS_PER_SOL
    tokens = tokens_out_for_sol_in(x, y, q)
    x2, y2 = x + q, y - tokens
    back = sol_out_for_tokens_in(x2, y2, tokens)
    # Truncation must never hand the trader more SOL than they paid.
    assert back <= q
    assert q - back <= 2      # at most one lamport of dust per leg


def test_round_trip_costs_are_monotone_in_depth_and_size():
    # Shallower curve (small x) is strictly more expensive for the same size.
    shallow = round_trip_breakeven(Decimal(0), Decimal(1), Decimal(35))
    deep = round_trip_breakeven(Decimal(0), Decimal(1), Decimal(100))
    assert shallow > deep
    # More size is strictly more expensive at the same depth.
    assert round_trip_breakeven(Decimal(0), Decimal(2), Decimal(50)) > round_trip_breakeven(
        Decimal(0), Decimal(1), Decimal(50)
    )
    # Fees alone set the floor when V = q = 0.
    assert round_trip_breakeven(Decimal(0), Decimal(0), Decimal(50)) == Decimal("0.02")


def test_slippage_and_latency_reference_values():
    assert own_slippage(Decimal(2), Decimal(50)) == Decimal("0.04")
    # (1 + 5/50)^2 - 1 = 0.21
    assert latency_cost(Decimal(5), Decimal(50)) == Decimal("0.21")
    assert latency_cost(Decimal(0), Decimal(50)) == 0


# --- fee convention (spec §0.3) ------------------------------------------

def test_net_convention_passes_amount_through():
    for side in (Side.BUY, Side.SELL):
        assert curve_sol_amount(1_000_000_000, side, NET) == (1_000_000_000, 0)


def test_gross_convention_removes_fee_on_the_correct_side():
    # A buyer paid curve + 1%: curve = gross / 1.01
    curve, fee = curve_sol_amount(1_010_000_000, Side.BUY, GROSS, fee_bps=100)
    assert curve == 1_000_000_000 and fee == 10_000_000
    # A seller received curve − 1%: curve = net / 0.99
    curve, fee = curve_sol_amount(990_000_000, Side.SELL, GROSS, fee_bps=100)
    assert curve == 1_000_000_000 and fee == 10_000_000


def test_convention_choice_shifts_reconstruction_by_about_one_percent():
    """Why §0.3 is a kill-criterion item and not a footnote.

    Replaying the same events under the wrong convention drifts ~1% of cumulative
    flow — three orders of magnitude past the 0.01 SOL tolerance of check 1.
    """
    x_net = CurveState()
    x_gross = CurveState()
    for slot in range(50):
        tokens = tokens_out_for_sol_in(x_net.x, x_net.y, LAMPORTS_PER_SOL)
        event = buy(LAMPORTS_PER_SOL, tokens, slot)
        x_net.apply(event, NET)
        x_gross.apply(event, GROSS)
    drift = lamports_to_sol(x_net.x - x_gross.x)
    assert drift > Decimal("0.01")
    assert abs(drift / Decimal(50) - Decimal("0.01") / Decimal("1.01")) < Decimal("0.0001")


# --- causality (spec §6.1, §8.4.5) ---------------------------------------

def test_out_of_order_event_raises():
    state = CurveState()
    state.apply(buy(LAMPORTS_PER_SOL, 1_000_000, slot=100), NET)
    with pytest.raises(OrderingViolation):
        state.apply(buy(LAMPORTS_PER_SOL, 1_000_000, slot=99), NET)


def test_intra_transaction_order_is_resolved_by_ix_index():
    state = CurveState()
    state.apply(buy(LAMPORTS_PER_SOL, 1_000_000, slot=10, tx=3, ix=0), NET)
    state.apply(buy(LAMPORTS_PER_SOL, 1_000_000, slot=10, tx=3, ix=1), NET)
    with pytest.raises(OrderingViolation):
        state.apply(buy(LAMPORTS_PER_SOL, 1_000_000, slot=10, tx=3, ix=0), NET)


def test_replay_never_silently_sorts():
    """Shuffled input must fail, not be repaired — repairing hides the bug that
    produced it and would let a future event be applied as if it were past."""
    events = [buy(LAMPORTS_PER_SOL, 1_000_000, s) for s in (1, 5, 3, 9)]
    for mode in ("raise", "record"):
        with pytest.raises(OrderingViolation):
            list(replay_token(events, NET, on_violation=mode))


def test_state_violation_is_recordable_and_leaves_state_untouched():
    state = CurveState()
    events = [
        buy(LAMPORTS_PER_SOL, 1_000_000, 1),
        sell(50 * LAMPORTS_PER_SOL, 1_000_000, 2),   # impossible: drains below x0
        buy(LAMPORTS_PER_SOL, 1_000_000, 3),
    ]
    out = list(replay_token(events, NET, on_violation="record", initial=state))
    assert out[1][1] is None and "x_post" in out[1][2]
    assert out[2][1] is not None
    # the impossible sell did not move the reserves
    assert out[2][1].x_pre == out[0][1].x_post
    with pytest.raises(CurveViolation):
        list(replay_token(events, NET, initial=CurveState()))


# --- continuity and exactness --------------------------------------------

def _random_walk(n: int, seed: int = 7) -> list[CurveEvent]:
    """A plausible token history: buys and sells that never drain the curve."""
    rng = random.Random(seed)
    state = CurveState()
    events: list[CurveEvent] = []
    held = 0
    for slot in range(1, n + 1):
        real_sol = state.x - X0_LAMPORTS
        if held > 0 and rng.random() < 0.45:
            tokens = rng.randint(1, held)
            out = sol_out_for_tokens_in(state.x, state.y, tokens)
            if out >= real_sol or out <= 0:
                continue
            event = sell(out, tokens, slot)
            held -= tokens
        else:
            q = rng.randint(LAMPORTS_PER_SOL // 100, LAMPORTS_PER_SOL // 2)
            tokens = tokens_out_for_sol_in(state.x, state.y, q)
            event = buy(q, tokens, slot)
            held += tokens
        state.apply(event, NET)
        events.append(event)
    return events


def test_x_post_chains_into_next_x_pre():
    """The identity behind validation check 5, at the arithmetic level."""
    events = _random_walk(500)
    recs = [r for _, r, _ in replay_token(events, NET)]
    for prev, nxt in zip(recs, recs[1:]):
        assert prev.x_post == nxt.x_pre
        assert prev.y_post == nxt.y_pre


def test_integer_replay_is_exact_over_1e5_events():
    """§0.4: does floating-point error accumulate over 10^5 sequential events?

    The integer path is exact by construction — cumulative state equals x0 plus
    the signed sum of curve amounts, with zero error at any length.  The float64
    path is measured against it; the drift it accumulates is reported rather than
    assumed, and the bound asserted here is what keeps `Decimal`/int mandatory in
    spirit but demonstrably unnecessary in magnitude.
    """
    events = _random_walk(100_000, seed=11)
    assert len(events) > 90_000

    exact = CurveState()
    approx = FloatCurveState()
    signed_total = 0
    for event in events:
        rec = exact.apply(event, NET)
        approx.apply(event, NET)
        signed_total += rec.curve_sol

    assert exact.x == X0_LAMPORTS + signed_total          # exact, no tolerance
    drift_sol = abs(Decimal(approx.x) - lamports_to_sol(exact.x))
    assert drift_sol < Decimal("1e-6")                    # measured ~1e-11 SOL
    # ... and still ~7 orders of magnitude inside check 1's 0.01 SOL tolerance
    assert drift_sol < Decimal("0.01") / 1000
