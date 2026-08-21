"""Hand-computed tests for the frozen B1 rule, plus a mutation harness.

Every expected number below was worked out by hand from the rule text in
`src/b1_rule.py`, not read back from the analysis path.  The mutation harness at
the bottom re-executes a deliberately broken copy of the module and asserts that
at least one check catches each break; a mutation that survives is a hole in this
file, not a curiosity.
"""

from __future__ import annotations

import datetime as _dt
import math
from decimal import Decimal

import pytest

from src import b1_rule as R

K = 30.0 * 1_073_000_000.0
DAY = _dt.date(2026, 5, 12)


def ev(seq, x, wallet="w01", units=1000.0, unix=None, y=None):
    """A trade event.  `y` defaults to the constant-product partner of `x`."""
    return R.Event(seq=seq, unix=float(seq) if unix is None else float(unix),
                   x=x, y=(K / x if y is None else y), legs=((wallet, units),))


def transfer(seq, frm, to, units, unix=None):
    return R.Event(seq=seq, unix=float(seq) if unix is None else float(unix),
                   x=None, y=None, legs=((to, units), (frm, -units)))


def twenty_buyers(start_x=30.5, step=0.5):
    """Twenty distinct wallets buying once each; the 20th leaves x = 40.0."""
    xs = [start_x + step * i for i in range(19)] + [40.0]
    return [ev(i + 1, x, wallet=f"w{i + 1:02d}") for i, x in enumerate(xs)]


def priors_all_won(n=20, day=_dt.date(2026, 5, 10)):
    return [R.PriorToken(f"w{i:02d}", day, day) for i in range(1, n + 1)]


def params(**kw):
    base = dict(b1_q5_lower=0.5, b2_q5_lower=0.5)
    base.update(kw)
    return R.Params(**base)


# --- 1. the anchor -----------------------------------------------------------

def test_anchor_fires_at_exactly_twenty_holders():
    """Nineteen buyers is not an anchor; the twentieth event is."""
    evs = twenty_buyers()
    assert R.find_anchor(evs[:19], 20) is None
    idx, x_a, holders = R.find_anchor(evs, 20)
    assert idx == 19            # zero-based: the 20th event
    assert evs[idx].seq == 20
    assert len(holders) == 20


def test_anchor_counts_the_event_itself_and_x_a_is_what_it_left():
    """x_a is the reserve AFTER the anchor event, so 40.0 and not 39.5."""
    evs = twenty_buyers()
    _, x_a, _ = R.find_anchor(evs, 20)
    assert x_a == 40.0
    assert evs[18].x == pytest.approx(39.5)


def test_transfer_carries_the_last_trade_reserve():
    """A transfer moves units, not reserves, so x_a is the previous trade's x."""
    evs = twenty_buyers()[:19] + [transfer(20, "w01", "w20", 500.0)]
    idx, x_a, holders = R.find_anchor(evs, 20)
    assert idx == 19 and evs[idx].x is None
    assert x_a == pytest.approx(39.5)      # the 19th trade's reserve
    assert len(holders) == 20              # w20 became a holder by transfer


def test_ledger_is_transfer_aware_a_sender_stops_holding():
    """Sending the whole balance away drops the count back below 20."""
    evs = twenty_buyers()[:19] + [transfer(20, "w01", "w20", 1000.0)]
    assert R.find_anchor(evs, 20) is None  # w01 hits 0, w20 hits 1000 -> still 19


# --- 2. the win rate and its time boundary -----------------------------------

def test_win_rate_excludes_a_prior_token_that_reached_sixty_on_the_launch_day():
    """d_w must be STRICTLY before D: same-day knowledge is not prior knowledge."""
    p_before = [R.PriorToken("w01", _dt.date(2026, 5, 10), _dt.date(2026, 5, 11))]
    p_sameday = [R.PriorToken("w01", _dt.date(2026, 5, 10), DAY)]
    p_after = [R.PriorToken("w01", _dt.date(2026, 5, 10), _dt.date(2026, 5, 13))]
    assert R.wallet_win_rate("w01", DAY, p_before) == 1.0
    assert R.wallet_win_rate("w01", DAY, p_sameday) == 0.0
    assert R.wallet_win_rate("w01", DAY, p_after) == 0.0


def test_win_rate_denominator_excludes_same_day_first_trades():
    """A token the wallet first touched on D itself is not a prior token."""
    same = [R.PriorToken("w01", DAY, _dt.date(2026, 5, 10))]
    assert R.wallet_win_rate("w01", DAY, same) is None
    mixed = [R.PriorToken("w01", _dt.date(2026, 5, 11), None),
             R.PriorToken("w01", DAY, _dt.date(2026, 5, 11))]
    assert R.wallet_win_rate("w01", DAY, mixed) == 0.0   # 0 of 1, not 0 of 2


def test_win_rate_is_none_without_history_and_the_token_is_not_traded():
    """No history is not a win rate of zero."""
    assert R.wallet_win_rate("w01", DAY, []) is None
    d = R.decide("T", twenty_buyers() + [ev(i, 41.0 + i) for i in range(21, 40)],
                 DAY, [], params())
    assert d.traded is False and d.reason == "no_wallet_history"


# --- 3. the quintile filter --------------------------------------------------

def test_filter_rejects_when_b1_is_below_the_frozen_boundary():
    evs = twenty_buyers() + [ev(i, 41.0 + i) for i in range(21, 40)]
    half = ([R.PriorToken(f"w{i:02d}", _dt.date(2026, 5, 10), _dt.date(2026, 5, 10))
             for i in range(1, 11)]
            + [R.PriorToken(f"w{i:02d}", _dt.date(2026, 5, 10), None)
               for i in range(11, 21)])
    d = R.decide("T", evs, DAY, half, params(b1_q5_lower=0.9, b2_q5_lower=0.0))
    assert d.traded is False and d.reason == "filtered_out"
    assert d.b1 == 0.0 and d.b2 == 1.0          # nearest-rank over ten 0s, ten 1s
    ok = R.decide("T", evs, DAY, half, params(b1_q5_lower=0.0, b2_q5_lower=0.0))
    assert ok.traded is True


def test_boundaries_are_required():
    with pytest.raises(ValueError):
        R.Params()
    with pytest.raises(ValueError):
        R.Params(b1_q5_lower=0.5)


def test_nearest_rank_is_the_documented_convention():
    """sorted[ceil(p*n)-1]: p50 of 1..20 is the 10th value, p90 the 18th."""
    vs = list(range(1, 21))
    assert R.nearest_rank(vs, 0.50) == 10
    assert R.nearest_rank(vs, 0.90) == 18
    assert R.nearest_rank([], 0.5) is None


# --- 4. entry and exit delays ------------------------------------------------

def test_entry_is_the_third_trade_event_after_the_anchor():
    evs = twenty_buyers() + [ev(21, 41.0), ev(22, 42.0), ev(23, 44.0),
                             ev(24, 50.0), ev(25, 55.0)]
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.entry_seq == 23 and d.x_entry == 44.0


def test_entry_delay_skips_transfers():
    """The delay counts TRADE events; a transfer in between does not consume it."""
    evs = twenty_buyers() + [ev(21, 41.0), transfer(22, "w01", "w02", 1.0),
                             ev(23, 42.0), ev(24, 44.0), ev(25, 50.0),
                             ev(26, 55.0), ev(27, 58.0)]
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.entry_seq == 24 and d.x_entry == 44.0


def test_entry_never_fills_with_fewer_than_three_events_after_the_anchor():
    evs = twenty_buyers() + [ev(21, 41.0), ev(22, 42.0)]
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.traded is False and d.reason == "entry_never_fills"


def test_exit_fill_is_the_third_event_after_the_trigger_and_is_the_overshoot():
    """Trigger at seq 26 (x = 71 >= 60); the fill is seq 29 at 90.0, not 71."""
    evs, _ = R._fixture()
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.trigger_seq == 26 and d.trigger_kind == "target"
    assert d.exit_seq == 29 and d.x_exit == 90.0


# --- 5. the sixty-second limit -----------------------------------------------

def test_time_limit_fires_when_the_target_is_never_reached():
    """x stays under 60; the first event >= 60 s after the anchor is the trigger."""
    evs = twenty_buyers()
    evs += [ev(20 + i, 41.0 + i * 0.1, unix=20 + i) for i in range(1, 10)]  # 21..29
    evs += [ev(80 + i, 45.0 + i, unix=80 + i) for i in range(1, 8)]          # 81..87
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.trigger_kind == "time"
    assert evs[[e.seq for e in evs].index(d.trigger_seq)].unix - d.anchor_unix >= 60.0
    assert d.trigger_seq == 81


def test_target_wins_an_exact_tie_with_the_time_limit():
    """One event both crosses 60 and is 60 s past the anchor -> counted as target."""
    evs = twenty_buyers()
    evs += [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22), ev(23, 44.0, unix=23)]
    evs += [ev(24, 61.0, unix=80), ev(25, 62.0, unix=81), ev(26, 63.0, unix=82),
            ev(27, 64.0, unix=83)]
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.trigger_seq == 24 and d.trigger_kind == "target"


# --- 6. the arithmetic -------------------------------------------------------

def test_pnl_matches_the_hand_computation_on_the_fixture():
    """x1 = 44, q = 0.5, x2 = 90.5, k = 3.219e10.

        dy   = k*q/(x1*(x1+q)) = 1.6095e10 / 1958   = 8_220_122.574055...
        out  = dy*x2^2/(k + dy*x2)                  = 2.0442...
        net  = out*0.9875 - 0.5/0.9875 - 2*0.001    = 1.510358...
    """
    evs, _ = R._fixture()
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    dy = K * 0.5 / (44.0 * 44.5)
    out = dy * 90.5 ** 2 / (K + dy * 90.5)
    expect = out * 0.9875 - 0.5 / 0.9875 - 0.002
    assert float(d.pnl_sol) == pytest.approx(expect, rel=1e-12)
    assert float(d.ret) == pytest.approx(expect / 0.5, rel=1e-12)


def test_price_is_quadratic_in_the_reserve():
    """P = x^2/k: doubling x quadruples the price, so the check is on the model."""
    dy = K * 0.5 / (44.0 * 44.5)
    p_lo = 44.0 ** 2 / K
    p_hi = 88.0 ** 2 / K
    assert p_hi / p_lo == pytest.approx(4.0, rel=1e-12)
    assert dy == pytest.approx(K / 44.0 - K / 44.5, rel=1e-9)


def test_fee_is_charged_on_each_side_of_a_flat_round_trip():
    """W = 0 means the reserve comes back; the loss is exactly the two fees."""
    q = Decimal("0.5")
    pnl = R.cost_model.net_pnl(Decimal("44"), q, V=0, W=0, fixed_cost_per_leg=0)
    f = Decimal("0.0125")
    assert float(pnl / q) == pytest.approx(float((1 - f) - 1 / (1 - f)), rel=1e-12)
    assert float(pnl) < 0


def test_fixed_cost_is_charged_twice_and_scales_as_two_over_q():
    a = R.cost_model.net_pnl(Decimal("44"), Decimal("0.5"), V=0, W=0,
                             fixed_cost_per_leg=Decimal("0.001"))
    b = R.cost_model.net_pnl(Decimal("44"), Decimal("0.5"), V=0, W=0,
                             fixed_cost_per_leg=0)
    assert float(b - a) == pytest.approx(0.002, rel=1e-12)
    assert float((b - a) / Decimal("0.5")) == pytest.approx(2 * 0.001 / 0.5, rel=1e-12)


def test_own_slippage_makes_a_bigger_order_worse_on_the_same_path():
    """Same entry and exit reserves; only the size changes."""
    small = R.cost_model.net_pnl(Decimal("44"), Decimal("0.05"), V=0,
                                 W=Decimal("46"), fixed_cost_per_leg=0)
    big = R.cost_model.net_pnl(Decimal("44"), Decimal("5"), V=0,
                               W=Decimal("46"), fixed_cost_per_leg=0)
    assert float(small / Decimal("0.05")) > float(big / Decimal("5"))


# --- 7. universe and conventions ---------------------------------------------

def test_a_token_off_the_constant_product_invariant_is_out_of_the_universe():
    evs = twenty_buyers()
    bad = evs[:-1] + [R.Event(seq=20, unix=20.0, x=40.0, y=K / 40.0 * 1.01,
                              legs=(("w20", 1000.0),))]
    assert R.is_clean(evs) is True
    assert R.is_clean(bad) is False
    d = R.decide("T", bad, DAY, priors_all_won(), params())
    assert d.traded is False and d.reason == "not_clean"


def test_unfilled_exit_conventions_differ_and_both_are_reachable():
    """Trigger with fewer than three events left: fee-only, or dropped."""
    evs = twenty_buyers() + [ev(21, 41.0), ev(22, 42.0), ev(23, 44.0),
                             ev(24, 61.0), ev(25, 62.0)]
    d1 = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d1.traded is True and d1.x_exit == d1.x_entry
    assert d1.diag.get("exit_unfilled") is True and float(d1.ret) < 0
    d2 = R.decide("T", evs, DAY, priors_all_won(),
                  params(unfilled_exit="not_traded"))
    assert d2.traded is False and d2.reason == "exit_never_fills"


# --- 8. mutation harness -----------------------------------------------------

MUTATIONS = {
    "anchor_off_by_one": ("if len(holders) >= n_target:", "if len(holders) >= n_target + 1:"),
    "win_rate_uses_lookahead": ("if p.t60_day is not None and max(p.first_trade_day, p.t60_day) < launch_day:",
                                "if p.t60_day is not None:"),
    "win_rate_boundary_not_strict": ("if p.wallet != wallet or not (p.first_trade_day < launch_day):",
                                     "if p.wallet != wallet or not (p.first_trade_day <= launch_day):"),
    "entry_delay_two": ("e_idx = _delayed(evs, a_idx, params.entry_delay)",
                        "e_idx = _delayed(evs, a_idx, params.entry_delay - 1)"),
    "exit_has_no_delay": ("x_idx = _delayed(evs, trig_idx, params.exit_delay)",
                          "x_idx = trig_idx"),
    "time_limit_thirty": ("time_limit_s: float = TIME_LIMIT_S",
                          "time_limit_s: float = 30.0"),
    "fee_charged_once": ("return out * (1 - f) - q / (1 - f)",
                         "return out * (1 - f) - q"),
    "filter_disabled": ("if d.b1 < params.b1_q5_lower or d.b2 < params.b2_q5_lower:",
                        "if False:"),
    "clean_check_disabled": ("if not is_clean(evs, params.clean_tol):", "if False:"),
    "ledger_ignores_transfers": ("for w, du in ev.legs:",
                                 "for w, du in (ev.legs if ev.is_trade else ()):"),
}


def _exec_module(text, name):
    """Build a live module from source.

    `dataclasses` resolves a class's annotations through
    `sys.modules[cls.__module__]`, so the module has to be registered BEFORE the
    body runs or every @dataclass in it raises.  That is why this is not a bare
    `exec` into a fresh namespace.
    """
    import sys
    import types
    mut = types.ModuleType(name)
    mut.__dict__["__name__"] = name
    sys.modules[name] = mut
    try:
        exec(compile(text, name, "exec"), mut.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mut


def _mutated(name):
    text = open(R.__file__).read()
    old, new = MUTATIONS[name]
    if name == "fee_charged_once":
        cm_text = open(R.cost_model.__file__).read()
        assert old in cm_text, name
        mod = _exec_module(cm_text.replace(old, new), f"cm_mut_{name}")
        mut = _exec_module(text, f"b1_mut_{name}")
        mut.cost_model = mod
        return mut
    assert old in text, f"mutation target missing: {name}"
    return _exec_module(text.replace(old, new), f"b1_mut_{name}")


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_mutation_is_caught(name):
    """Each break must change an observable the checks above assert on."""
    M = _mutated(name)
    evs, _ = M._fixture()
    P = M.Params(b1_q5_lower=0.5, b2_q5_lower=0.5) if name != "time_limit_thirty" \
        else M.Params(b1_q5_lower=0.5, b2_q5_lower=0.5)
    base = R.decide("T", *(lambda e, p: (e, DAY, p))(*R._fixture()), params())

    if name == "anchor_off_by_one":
        assert M.find_anchor(evs, 20) != R.find_anchor(evs, 20)
        return
    if name in ("win_rate_uses_lookahead", "win_rate_boundary_not_strict"):
        pr = [M.PriorToken("w01", _dt.date(2026, 5, 10), _dt.date(2026, 5, 13))] \
            if name == "win_rate_uses_lookahead" else \
            [M.PriorToken("w01", DAY, _dt.date(2026, 5, 10))]
        got = M.wallet_win_rate("w01", DAY, pr)
        exp = R.wallet_win_rate("w01", DAY, pr)
        assert got != exp
        return
    if name == "clean_check_disabled":
        bad = evs[:-1] + [M.Event(seq=evs[-1].seq, unix=evs[-1].unix, x=40.0,
                                  y=K / 40.0 * 1.01, legs=(("w20", 1000.0),))]
        assert M.decide("T", bad, DAY, priors_all_won(), P).reason != "not_clean"
        return
    if name == "ledger_ignores_transfers":
        e2 = twenty_buyers()[:19] + [transfer(20, "w01", "w20", 500.0)]
        assert (M.find_anchor(e2, 20) is None) != (R.find_anchor(e2, 20) is None)
        return
    if name == "time_limit_thirty":
        e2 = twenty_buyers()
        e2 += [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22), ev(23, 44.0, unix=23)]
        e2 += [ev(24, 45.0, unix=55), ev(25, 46.0, unix=95), ev(26, 47.0, unix=96),
               ev(27, 48.0, unix=97), ev(28, 49.0, unix=98)]
        assert (M.decide("T", e2, DAY, priors_all_won(), P).trigger_seq
                != R.decide("T", e2, DAY, priors_all_won(), params()).trigger_seq)
        return

    got = M.decide("T", evs, DAY, priors_all_won(), P)
    if name == "filter_disabled":
        half = ([M.PriorToken(f"w{i:02d}", _dt.date(2026, 5, 10), None)
                 for i in range(1, 21)])
        strict = M.Params(b1_q5_lower=0.9, b2_q5_lower=0.9)
        assert M.decide("T", evs, DAY, half, strict).reason != "filtered_out"
        return
    assert (got.entry_seq, got.exit_seq, got.pnl_sol) != \
           (base.entry_seq, base.exit_seq, base.pnl_sol), name


# --- 9. the unfilled-exit conventions, measured 2026-08-21 -------------------

def test_unfilled_exit_last_x_prices_at_the_last_observed_reserve():
    """The third convention: the trader who cannot get out sits in the token.

    Trigger at seq 24 (x = 61 >= 60) with only one trade left, so the 3-event
    fill never happens.  "entry_price" exits at 44.0; "last_x" exits at the last
    observed reserve, 35.0, which is a real loss and not a fee-only round trip.
    """
    evs = twenty_buyers() + [ev(21, 41.0), ev(22, 42.0), ev(23, 44.0),
                             ev(24, 61.0), ev(25, 35.0)]
    a = R.decide("T", evs, DAY, priors_all_won(), params())
    b = R.decide("T", evs, DAY, priors_all_won(), params(unfilled_exit="last_x"))
    assert a.diag.get("exit_unfilled") is True and a.x_exit == 44.0
    assert b.diag.get("exit_unfilled") is True and b.x_exit == 35.0
    assert float(b.ret) < float(a.ret)


def test_unknown_unfilled_exit_is_rejected():
    with pytest.raises(ValueError):
        params(unfilled_exit="hold_forever")


def test_frozen_boundaries_are_documented_but_not_defaults():
    """The numbers live in the docstring; passing them is still mandatory."""
    assert "0.572916667" in R.__doc__ and "1.000000000" in R.__doc__
    with pytest.raises(ValueError):
        R.Params()
