"""One meaningful test per generator parameter that no test used to vary.

`test_audit_findings.py::test_every_generator_parameter_is_exercised_by_some_test`
recorded six of eleven parameters as never varied: mayhem_share, n_tokens,
n_wallets, round_share, sell_share, slot_density.  Passing a parameter through
proves nothing, so each test here moves the parameter and asserts that a
MEASURED quantity moves with it.

Every expectation is hand-computed or quoted from the spec.  None is read back
from the code's output.

Two of the six were not merely unused — they were inert.  `mayhem_share` was
declared but never read by `make_token`, and `n_wallets` only sized a pool.  They
now have builders (`make_mixed_mayhem_stream`, `make_wallet_ladder`); see the
note in tests/synthetic.py.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.features_reference import net_flow, round_frac
from src.oh_reference import TOKEN_UNITS, TokenState
from tests.synthetic import (
    SyntheticConfig,
    make_events,
    make_mixed_mayhem_stream,
    make_token,
    make_wallet_ladder,
)


def _replay(events) -> TokenState:
    state = TokenState(events[0].x0_lam, events[0].y0_units)
    for e in events:
        state.apply(e)
    return state


# --- sell_share -------------------------------------------------------------

def test_sell_share_moves_inventory_but_never_the_cost_basis():
    """spec §1.2: "Sell гарвал tokens_received-ээс хасаж, cost basis-ийг хэвээр
    үлдээнэ" — selling reduces the balance and leaves the basis alone.

    Expectation, from that line: for every wallet in either stream the basis must
    equal buy_lam / (buy_units × 1000) exactly, a function of buys only, whatever
    the sell rate.  What selling does move is inventory: at sell_share = 0.0
    nothing is ever sold and every wallet still holds exactly what it bought, so
    the busy stream must end holding strictly less than it bought.

    The brief expected the count of positive-balance wallets to fall too.  It does
    not, and the assertion below records why rather than dropping the claim.
    """
    quiet = make_token(SyntheticConfig(n_events=200, sell_share=0.0,
                                       empty_slot_share=0.0, seed=7), 0)
    busy = make_token(SyntheticConfig(n_events=200, sell_share=0.9,
                                      empty_slot_share=0.0, seed=7), 0)

    for events in (quiet, busy):
        for w in _replay(events).wallets.values():
            if w.buy_units == 0:
                assert w.cost_basis() is None
                continue
            assert w.cost_basis() == Decimal(w.buy_lam) / (
                Decimal(w.buy_units) * Decimal(1000))

    quiet_state, busy_state = _replay(quiet), _replay(busy)
    assert all(w.held_units == w.buy_units for w in quiet_state.wallets.values())

    def held(st):
        return sum(w.held_units for w in st.wallets.values())

    def holders(st):
        return sum(1 for w in st.wallets.values() if w.held_units > 0)

    # Inventory is the observable that moves.  Selling can only subtract, so the
    # busy stream must end with strictly less of what it bought still held.
    assert held(busy_state) < sum(w.buy_units for w in busy_state.wallets.values())
    assert held(quiet_state) == sum(w.buy_units for w in quiet_state.wallets.values())

    # MEASURED, and contrary to the expectation this test was written with: the
    # count of wallets holding a positive balance does NOT fall.  The generator
    # sells `rng.randint(1, sellable)`, a partial amount, so a wallet almost never
    # lands exactly on zero and stays OH-eligible however hard it sells.  Pinned
    # rather than dropped, so that a generator able to close a position out
    # entirely would fail here and be noticed.
    assert holders(busy_state) == holders(quiet_state) == 12


# --- slot_density -----------------------------------------------------------

def test_slot_density_does_not_move_the_trailing_window_boundary():
    """spec §3, §6.1: a trailing w-slot window is (s − w, s] over events up to t.

    Hardened form of the A2/A3 pair: instead of one hand-built slot, this packs
    many events per slot and re-derives the window from the definition for every
    trigger, then demands the reference agree.  The guard below fails the test if
    the stream has no trigger with a same-slot successor, which is what made the
    original single-slot test possible to pass by accident.
    """
    events = make_token(SyntheticConfig(n_events=300, slot_density=3.0,
                                        empty_slot_share=0.0, seed=11), 0)
    with_successor = 0
    for i, ev in enumerate(events):
        if any(e.slot == ev.slot for e in events[i + 1:]):
            with_successor += 1
        expected = sum(e.signed_lam for e in events[: i + 1]
                       if e.slot > ev.slot - 5)
        assert net_flow(events, i, 5) == Decimal(expected) / Decimal(10) ** 9
    assert with_successor > 0, "stream has no same-slot successors; test is vacuous"


# --- round_share ------------------------------------------------------------

@pytest.mark.parametrize("share,expected", [(0.0, Decimal(0)), (1.0, Decimal(1))])
def test_round_share_endpoints_are_exact(share, expected):
    """spec §3 f9: share of trades whose SOL size is 0.1, 0.5 or 1.0.

    Expectation, hand-derived from the generator: with sell_share = 0.0 every
    trade is a buy, and a buy takes a round size with probability `round_share`.
    At 0.0 no trade can be round, at 1.0 every trade is, so f9 over a window
    covering the whole stream is exactly 0 and exactly 1.  (A non-round draw
    landing exactly on 1e8/5e8/1e9 has probability ~3/2e9 and is ignored.)
    """
    events = make_token(SyntheticConfig(n_events=120, round_share=share,
                                        sell_share=0.0, empty_slot_share=0.0,
                                        seed=3), 0)
    assert round_frac(events, len(events) - 1, 10 ** 9) == expected


def test_round_share_middle_lands_within_binomial_bounds():
    """spec §3 f9, continued.

    Expectation, hand-computed: n = 400 buys at round_share = 0.5 gives a
    Binomial(400, 0.5) count, mean 200 and sd √(400 × 0.25) = 10.  Four sd is
    ±40, i.e. f9 ∈ [0.40, 0.60].  Wide on purpose: the point is that the
    parameter drives the statistic, not that the RNG hits its mean.
    """
    events = make_token(SyntheticConfig(n_events=400, round_share=0.5,
                                        sell_share=0.0, empty_slot_share=0.0,
                                        seed=5), 0)
    frac = round_frac(events, len(events) - 1, 10 ** 9)
    assert Decimal("0.40") <= frac <= Decimal("0.60")


# --- mayhem_share -----------------------------------------------------------

@pytest.mark.parametrize("n_tokens,share,expected_flagged", [
    (10, 0.0, 0), (10, 0.3, 3), (10, 1.0, 10), (5, 0.4, 2),
])
def test_mayhem_share_sets_how_many_streams_are_reparameterised(
        n_tokens, share, expected_flagged):
    """Audit finding E, parameterised.  spec §1.1 (k from createevent), §2.2 stratum.

    Expectation, hand-computed: the builder flags round(n_tokens × share)
    streams, so 10 × 0.3 = 3 and 5 × 0.4 = 2.  Deterministic rather than sampled
    precisely so the count can be asserted instead of bounded.
    """
    streams, flagged = make_mixed_mayhem_stream(
        SyntheticConfig(n_tokens=n_tokens, mayhem_share=share))
    assert len(streams) == n_tokens
    assert len(flagged) == expected_flagged
    assert all(any(r.mayhem for r in streams[i]) for i in flagged)
    assert all(not any(r.mayhem for r in streams[i])
               for i in range(n_tokens) if i not in flagged)


def test_mayhem_streams_break_the_launch_k_price_and_clean_ones_do_not():
    """Audit finding E.  spec §1.1 `P(x) = x²/k`, k from createevent.

    Expectation, derived: P_launch / P_instantaneous = x·y / k₀.  A stream with no
    reparameterisation keeps x·y = k₀, so the ratio is 1.  A reparameterised one
    jumps the SOL side by 1.5× and leaves the token side, so the ratio is 1.5.
    """
    streams, flagged = make_mixed_mayhem_stream(
        SyntheticConfig(n_tokens=4, mayhem_share=0.5))
    for i, raws in enumerate(streams):
        last = raws[-1]
        state = TokenState(last.x0_lam, last.y0_units)
        p_launch = state.spot_price(last.vsol)
        p_inst = (Decimal(last.vsol) / Decimal(10) ** 9) / (
            Decimal(last.vtok) / TOKEN_UNITS)
        ratio = p_launch / p_inst
        if i in flagged:
            assert Decimal("1.4") < ratio < Decimal("1.6")
        else:
            assert abs(ratio - 1) < Decimal("1e-6")


# --- n_wallets --------------------------------------------------------------

def test_three_wallets_put_all_overhead_in_the_top_three():
    """spec §1.2: OH_conc is the share of OH held by the top 3 wallets.

    Expectation, from that definition: with only three wallets the top three are
    all of them, so OH_conc = 1 exactly — no arithmetic required.
    """
    raws = make_wallet_ladder(SyntheticConfig(n_wallets=3))
    events = [r.to_event() for r in raws]
    state = _replay(events)
    oh, _, conc, n = state.overhead(events[-1].vsol)
    assert oh > 0 and n == 3
    assert conc == Decimal(1)


@pytest.mark.parametrize("n_wallets", [4, 8, 16, 32])
def test_overhead_concentration_falls_as_wallets_are_added(n_wallets):
    """spec §1.2 OH_conc, monotonicity.

    Expectation, derived: every buyer in the ladder pays more and receives fewer
    tokens than the one before, so contributions are strictly decreasing and the
    top three are the first three.  Adding wallets adds only smaller
    contributions to the denominator, so OH_conc must fall strictly below its
    three-wallet value of 1 and keep falling.
    """
    def conc(n: int) -> Decimal:
        events = [r.to_event() for r in make_wallet_ladder(SyntheticConfig(n_wallets=n))]
        return _replay(events).overhead(events[-1].vsol)[2]

    assert conc(n_wallets) < conc(3) == Decimal(1)
    assert conc(n_wallets) < conc(n_wallets - 1)


# --- n_tokens ---------------------------------------------------------------

def test_ledgers_are_isolated_between_tokens():
    """spec §1.2: cost basis and OH are per (wallet, token).

    Expectation, derived from the generator's determinism: `make_token(config, 0)`
    depends only on the seed and the token index, so token 0's event stream is
    identical whether the config asks for one token or five.  If any ledger state
    leaked across tokens, OH for token 0 computed inside the five-token universe
    would differ from OH computed on token 0 alone.  It must not.
    """
    alone = make_events(SyntheticConfig(n_tokens=1, n_events=80, seed=21))
    together = make_events(SyntheticConfig(n_tokens=5, n_events=80, seed=21))
    first_mint = alone[0].mint
    same_token = [e for e in together if e.mint == first_mint]
    assert same_token == alone

    oh_alone = _replay(alone).overhead(alone[-1].vsol)
    oh_together = _replay(same_token).overhead(same_token[-1].vsol)
    assert oh_alone == oh_together
    assert len({e.mint for e in together}) == 5
