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
    base = dict(b1_q5_lower=0.5, b2_q5_lower=0.5, exit_window_s=60.0)
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


def test_exit_fill_is_the_next_event_after_the_trigger_and_is_the_overshoot():
    """Trigger at seq 26 (x = 71 >= 60); the fill is the NEXT event, seq 27 at
    80.0 -- the reserve that event left, not the 71 that met the condition."""
    evs, _ = R._fixture()
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.trigger_seq == 26 and d.trigger_kind == "target"
    assert d.exit_seq == 27 and d.x_exit == 80.0
    assert d.diag["fill_ordinal"] == 1


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
    """x1 = 44, q = 0.5, exit at the NEXT event (80.0) so x2 = 80.5.

        dy   = k*q/(x1*(x1+q)) = 1.6095e10 / 1958   = 8_220_122.574055...
        out  = dy*x2^2/(k + dy*x2)
        net  = out*0.9875 - 0.5/0.9875 - 2*0.001
    """
    evs, _ = R._fixture()
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.x_exit == 80.0
    dy = K * 0.5 / (44.0 * 44.5)
    out = dy * 80.5 ** 2 / (K + dy * 80.5)
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

def test_universe_is_the_launch_time_flag_not_the_whole_life_invariant():
    """Audit 4 fix 1: admission is `is_mayhem_mode`, known at launch."""
    evs, _ = R._fixture()
    ok = R.decide("T", evs, DAY, priors_all_won(), params(), mayhem_flag=False)
    no = R.decide("T", evs, DAY, priors_all_won(), params(), mayhem_flag=True)
    assert ok.traded is True
    assert no.traded is False and no.reason == "mayhem_at_launch"


def test_the_whole_life_invariant_is_a_diagnostic_and_never_admits_or_rejects():
    """A token off the invariant still trades: the invariant is lookahead."""
    evs = twenty_buyers() + [ev(21, 41.0), ev(22, 42.0), ev(23, 44.0),
                             ev(24, 71.0), ev(25, 80.0), ev(26, 85.0), ev(27, 90.0)]
    bad = evs[:19] + [R.Event(seq=20, unix=20.0, x=40.0, y=K / 40.0 * 1.01,
                              legs=(("w20", 1000.0),))] + evs[20:]
    assert R.is_clean(evs) is True
    assert R.is_clean(bad) is False
    d = R.decide("T", bad, DAY, priors_all_won(), params())
    assert d.traded is True and d.state.startswith("CLOSED")


def test_exit_window_boundary_is_inclusive_and_decides_closed_vs_open():
    """Trigger at unix 24; the next trade at unix 34 is a 10 s gap.

    W = 10 closes the position, W = 9 leaves it OPEN_LATE_FILL.  Nothing else
    about the token changes, so W alone moves it between the two states.
    """
    evs = twenty_buyers() + [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22),
                             ev(23, 44.0, unix=23), ev(24, 61.0, unix=24),
                             ev(25, 62.0, unix=34), ev(26, 63.0, unix=40)]
    inside = R.decide("T", evs, DAY, priors_all_won(), params(exit_window_s=10.0))
    outside = R.decide("T", evs, DAY, priors_all_won(), params(exit_window_s=9.0))
    assert inside.state == "CLOSED_TARGET" and inside.x_exit == 62.0
    assert inside.diag["fill_gap_s"] == pytest.approx(10.0)
    assert outside.state == "OPEN_LATE_FILL" and outside.ret is None
    assert outside.diag["late_gap_s"] == pytest.approx(10.0)


def test_open_dead_is_a_six_hour_gap_and_carries_the_last_reserve():
    """The next trade is 7 h after the trigger: DEAD, not LATE_FILL."""
    evs = twenty_buyers() + [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22),
                             ev(23, 44.0, unix=23), ev(24, 61.0, unix=24),
                             ev(25, 30.8, unix=24 + 7 * 3600)]
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.traded is True and d.state == "OPEN_DEAD"
    assert d.ret is None and d.pnl_sol is None and d.x_exit is None
    assert d.diag["x_last_over_x_entry"] == pytest.approx(30.8 / 44.0)


def test_open_dead_when_no_trade_follows_the_trigger_at_all():
    evs = twenty_buyers() + [ev(21, 41.0), ev(22, 42.0), ev(23, 44.0),
                             ev(24, 61.0)]
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.state == "OPEN_DEAD" and d.ret is None


def test_window_edge_beats_dead_and_is_never_priced():
    """A token whose trigger sits inside the last 6 h of data is an artefact."""
    evs = twenty_buyers() + [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22),
                             ev(23, 44.0, unix=23), ev(24, 61.0, unix=24)]
    end_close = R.decide("T", evs, DAY, priors_all_won(),
                         params(data_end_unix=24 + 3600))
    end_far = R.decide("T", evs, DAY, priors_all_won(),
                       params(data_end_unix=24 + 7 * 3600))
    assert end_close.state == "OPEN_WINDOW_EDGE" and end_close.ret is None
    assert end_far.state == "OPEN_DEAD"


def test_a_token_that_never_triggers_is_classified_off_its_last_trade():
    """No trigger at all: the reference moment is the last observed trade."""
    evs = twenty_buyers() + [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22),
                             ev(23, 44.0, unix=23), ev(24, 45.0, unix=24),
                             ev(25, 46.0, unix=25)]
    d = R.decide("T", evs, DAY, priors_all_won(), params())
    assert d.traded is True and d.state == "OPEN_DEAD" and d.ret is None
    edge = R.decide("T", evs, DAY, priors_all_won(), params(data_end_unix=25 + 60))
    assert edge.state == "OPEN_WINDOW_EDGE"


def test_exit_window_is_required():
    with pytest.raises(ValueError):
        R.Params(b1_q5_lower=0.5, b2_q5_lower=0.5)


def test_closed_states_are_labelled_by_which_trigger_fired():
    evs, _ = R._fixture()
    assert R.decide("T", evs, DAY, priors_all_won(), params()).state == "CLOSED_TARGET"
    e2 = twenty_buyers()
    e2 += [ev(20 + i, 41.0 + i * 0.1, unix=20 + i) for i in range(1, 10)]
    e2 += [ev(80 + i, 45.0 + i, unix=80 + i) for i in range(1, 8)]
    assert R.decide("T", e2, DAY, priors_all_won(), params()).state == "CLOSED_TIME"


def test_unfilled_exit_parameter_is_gone():
    """The fallback knob was removed, not merely defaulted away."""
    with pytest.raises(TypeError):
        R.Params(b1_q5_lower=0.5, b2_q5_lower=0.5, unfilled_exit="entry_price")


# --- 8. mutation harness -----------------------------------------------------

MUTATIONS = {
    "anchor_off_by_one": ("if len(holders) >= n_target:", "if len(holders) >= n_target + 1:"),
    "win_rate_uses_lookahead": ("if p.t60_day is not None and max(p.first_trade_day, p.t60_day) < launch_day:",
                                "if p.t60_day is not None:"),
    "win_rate_boundary_not_strict": ("if p.wallet != wallet or not (p.first_trade_day < launch_day):",
                                     "if p.wallet != wallet or not (p.first_trade_day <= launch_day):"),
    "entry_delay_two": ("e_idx = _delayed(evs, a_idx, params.entry_delay)",
                        "e_idx = _delayed(evs, a_idx, params.entry_delay - 1)"),
    "exit_takes_the_trigger_event_itself": (
        "x_idx = _delayed(evs, trig_idx, 1)", "x_idx = trig_idx"),
    "exit_window_boundary_exclusive": (
        "gap is not None and gap <= params.exit_window_s",
        "gap is not None and gap < params.exit_window_s"),
    "dead_and_late_fill_confused": (
        "elif gap is None or gap >= params.dead_gap_s:",
        "elif gap is None:"),
    "window_edge_checked_after_dead": (
        '        if (params.data_end_unix is not None\n                and params.data_end_unix - ref_unix < params.dead_gap_s):\n            d.state = "OPEN_WINDOW_EDGE"\n        elif gap is None or gap >= params.dead_gap_s:\n            d.state = "OPEN_DEAD"',
        '        if gap is None or gap >= params.dead_gap_s:\n            d.state = "OPEN_DEAD"\n        elif (params.data_end_unix is not None\n                and params.data_end_unix - ref_unix < params.dead_gap_s):\n            d.state = "OPEN_WINDOW_EDGE"'),
    "time_limit_thirty": ("time_limit_s: float = TIME_LIMIT_S",
                          "time_limit_s: float = 30.0"),
    "fee_charged_once": ("return out * (1 - f) - q / (1 - f)",
                         "return out * (1 - f) - q"),
    "filter_disabled": ("if d.b1 < params.b1_q5_lower or d.b2 < params.b2_q5_lower:",
                        "if False:"),
    "ledger_ignores_transfers": ("for w, du in ev.legs:",
                                 "for w, du in (ev.legs if ev.is_trade else ()):"),
    # --- audit 4 mutations ---
    "causal_universe_disabled": ("if mayhem_flag:", "if False:"),
    "open_no_fill_gets_entry_price_fallback": (
        "    else:\n        # OPEN: no realised PnL.  NO fallback price is invented here.\n        d.traded = True",
        "    else:\n        d.x_exit = d.x_entry\n        d.pnl_sol = cost_model.net_pnl(Decimal(str(d.x_entry)), params.q, V=0, W=0, fixed_cost_per_leg=params.fixed_cost_per_leg)\n        d.ret = d.pnl_sol / params.q\n        d.traded = True"),
    "no_trigger_falls_back_to_entry": (
        "    if trig_idx is not None:\n        d.trigger_seq = evs[trig_idx].seq",
        "    if trig_idx is None:\n        trig_idx = e_idx\n    if trig_idx is not None:\n        d.trigger_seq = evs[trig_idx].seq"),
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
    P = M.Params(b1_q5_lower=0.5, b2_q5_lower=0.5, exit_window_s=60.0)
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
    if name == "causal_universe_disabled":
        assert M.decide("T", evs, DAY, priors_all_won(), P, mayhem_flag=True).traded \
            != R.decide("T", evs, DAY, priors_all_won(), params(), mayhem_flag=True).traded
        return
    if name == "open_no_fill_gets_entry_price_fallback":
        e2 = twenty_buyers() + [ev(21, 41.0), ev(22, 42.0), ev(23, 44.0),
                                ev(24, 61.0)]
        assert M.decide("T", e2, DAY, priors_all_won(), P).x_exit is not None
        assert R.decide("T", e2, DAY, priors_all_won(), params()).x_exit is None
        return
    if name == "exit_window_boundary_exclusive":
        e2 = twenty_buyers() + [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22),
                                ev(23, 44.0, unix=23), ev(24, 61.0, unix=24),
                                ev(25, 62.0, unix=34), ev(26, 63.0, unix=40)]
        Pw = M.Params(b1_q5_lower=0.5, b2_q5_lower=0.5, exit_window_s=10.0)
        assert M.decide("T", e2, DAY, priors_all_won(), Pw).state != \
            R.decide("T", e2, DAY, priors_all_won(), params(exit_window_s=10.0)).state
        return
    if name == "dead_and_late_fill_confused":
        e2 = twenty_buyers() + [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22),
                                ev(23, 44.0, unix=23), ev(24, 61.0, unix=24),
                                ev(25, 30.8, unix=24 + 7 * 3600)]
        assert M.decide("T", e2, DAY, priors_all_won(), P).state != \
            R.decide("T", e2, DAY, priors_all_won(), params()).state
        return
    if name == "window_edge_checked_after_dead":
        e2 = twenty_buyers() + [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22),
                                ev(23, 44.0, unix=23), ev(24, 61.0, unix=24)]
        Pe = M.Params(b1_q5_lower=0.5, b2_q5_lower=0.5, exit_window_s=60.0,
                      data_end_unix=24 + 3600)
        assert M.decide("T", e2, DAY, priors_all_won(), Pe).state != \
            R.decide("T", e2, DAY, priors_all_won(),
                     params(data_end_unix=24 + 3600)).state
        return
    if name == "no_trigger_falls_back_to_entry":
        e2 = twenty_buyers() + [ev(21, 41.0, unix=21), ev(22, 42.0, unix=22),
                                ev(23, 44.0, unix=23), ev(24, 45.0, unix=24),
                                ev(25, 46.0, unix=25)]
        assert M.decide("T", e2, DAY, priors_all_won(), P).ret is not None
        assert R.decide("T", e2, DAY, priors_all_won(), params()).ret is None
        return
    if name == "exit_takes_the_trigger_event_itself":
        assert M.decide("T", evs, DAY, priors_all_won(), P).x_exit != \
            R.decide("T", evs, DAY, priors_all_won(), params()).x_exit
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
        strict = M.Params(b1_q5_lower=0.9, b2_q5_lower=0.9, exit_window_s=60.0)
        assert M.decide("T", evs, DAY, half, strict).reason != "filtered_out"
        return
    assert (got.entry_seq, got.exit_seq, got.pnl_sol) != \
           (base.entry_seq, base.exit_seq, base.pnl_sol), name


# --- 9. the unfilled-exit conventions, measured 2026-08-21 -------------------

def test_frozen_boundaries_are_documented_but_not_defaults():
    """The numbers live in the docstring; passing them is still mandatory."""
    assert "0.572916667" in R.__doc__ and "1.000000000" in R.__doc__
    with pytest.raises(ValueError):
        R.Params()
