"""The anchor rule — one function, re-derived independently of the analysis code.

  python -m src.anchor_rule            # self-check on the built-in fixture

This module deliberately does NOT import `src.holder_anchor`, `src.execution_gap`,
`src.asymmetric_barriers`, `src.fill_timing` or any SQL text.  The ledger, the
holder count, the anchor, the Gini, the delays and the exit search are all
written out again here, so a mistake in the analysis path cannot reproduce itself
in the check.  `src.cost_model` IS imported: it is the sanctioned pricing module
and the task specifies its exact path arithmetic.

THE RULE
--------
    walk the token's events in `seq` order, keeping a TRANSFER-AWARE ledger
      balance(w) = (bought - sold) + (received - sent)          [oh_a mechanism]
    a wallet HOLDS while balance(w) > 0

    ANCHOR = the first event at whose END the holder count reaches 3.
      The event itself is counted -- the condition cannot be known before it
      completes.  (SQL equivalent: ROWS ... AND CURRENT ROW.)
    x_a    = the reserve that anchor event LEFT.  `virtual_sol_reserves` on
      pump.fun's TradeEvent is the POST-trade reserve; proved in
      sql/phase0_kill_gate.sql, 74,733 / 74,733 first trades imply x0 = 30 SOL.
      A transfer moves units, not reserves, so the last trade's reserve carries.

    FILTERS
      (a) t_anchor > 3 s since launch
      (b) the anchor-moment `gini` (or `creator_share`) is in the LOWER tertile.
          The tertile boundary is a CROSS-SECTIONAL quantity -- it cannot be
          computed from one token -- so it is passed in as `tertile_cut`, which
          is REQUIRED: passing None raises rather than silently disabling the
          filter.  Measured: gini <= 0.267351881, creator_share <= 0.432181919.

    ENTRY  = the 3rd TRADE event after the anchor, priced on the reserve that
             event left.  Fewer than 3 trade events after the anchor -> NOT
             TRADED (the order never fills; that is not a zero and not a loss).
    EXIT   = the 3rd TRADE event after the first event with x >= x_a * 1.76,
             priced the same way.  No crossing, or fewer than 3 events after it
             -> hold to the LAST trade (censored).
    no stop.

    PRICE  P = x^2 / k with k constant (mayhem prevalence measured at
           0 / 262,129), fee 1.25% PER SIDE, own price impact on both legs via
           `cost_model.net_pnl`, plus an optional FIXED cost per round trip.

Delays are counted in TRADE events, matching `result_flow_gapin` /
`result_flow_gapout`, whose forward set is `pump_evt_tradeevent` only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from src import cost_model


@dataclass(frozen=True)
class Event:
    """One event in `seq` order.  `x` is the reserve AFTER the event, or None for
    a transfer (which moves units but not reserves)."""
    seq: int
    t: float                    # seconds since launch
    x: float | None
    wallet: str | None = None
    d_units: float = 0.0


@dataclass(frozen=True)
class Params:
    n_holders_target: int = 3
    min_t_anchor_s: float = 3.0
    tertile_feature: str = "gini"        # "gini" | "creator_share"
    #: Upper bound of the LOWER tertile.  REQUIRED -- `None` raises.  The
    #: boundary is CROSS-SECTIONAL and cannot be computed from one token, so it
    #: is measured once and written down (sql/tertile_cutoff.sql, on
    #: gapin INNER JOIN hfeat INNER JOIN hbar INNER JOIN token_base, mid-rank):
    #:     gini           t1 = [0.000000000, 0.267351881]
    #:     creator_share  t1 = [0.000000000, 0.432181919]
    #: The default is the gini cut, i.e. the frozen configuration.
    tertile_cut: float | None = 0.267351881
    entry_delay: int = 3                 # trade events after the anchor
    exit_delay: int = 3                  # trade events after the crossing
    target_mult: float | None = 1.76     # None = no target, hold to last trade
    q: Decimal = Decimal(1)
    fixed_cost: Decimal = Decimal(0)     # SOL PER LEG (charged twice)


@dataclass
class Outcome:
    traded: bool
    reason: str
    anchor_idx: int | None = None
    t_anchor: float | None = None
    x_anchor: float | None = None
    gini: float | None = None
    creator_share: float | None = None
    entry_idx: int | None = None
    x_entry: float | None = None
    exit_idx: int | None = None
    x_exit: float | None = None
    censored: bool = False
    pnl: Decimal | None = None
    ret: Decimal | None = None


# ------------------------------------------------------------------ ledger

def _gini(vals: list[float]) -> float:
    """Gini of strictly positive holdings, re-derived here.

        G = 2 * sum(i * u_i) / (n * sum(u)) - (n + 1) / n,  u sorted ASCENDING,
        i = 1..n

    One holder gives 0 by construction (2*1*u/(1*u) - 2 = 0)."""
    u = sorted(v for v in vals if v > 0)
    n = len(u)
    if n == 0:
        return 0.0
    tot = sum(u)
    if tot <= 0:
        return 0.0
    s = sum((i + 1) * v for i, v in enumerate(u))
    return 2.0 * s / (n * tot) - (n + 1) / n


def anchor_index(events: list[Event], n_target: int) -> int | None:
    """First index at whose END the holder count reaches `n_target`.

    The running balance includes the current event, so the count is the state
    AFTER it -- a wallet becomes a holder on the event that lifts it above zero.
    """
    bal: dict[str, float] = {}
    holders = 0
    for i, e in enumerate(events):
        if e.wallet is not None:
            before = bal.get(e.wallet, 0.0)
            after = before + e.d_units
            bal[e.wallet] = after
            if after > 0 >= before:
                holders += 1
            elif after <= 0 < before:
                holders -= 1
        if holders >= n_target:
            return i
    return None


def ledger_at(events: list[Event], idx: int) -> dict[str, float]:
    """Wallet balances after event `idx` inclusive."""
    bal: dict[str, float] = {}
    for e in events[: idx + 1]:
        if e.wallet is not None:
            bal[e.wallet] = bal.get(e.wallet, 0.0) + e.d_units
    return bal


def reserve_after(events: list[Event], idx: int) -> float | None:
    """The reserve event `idx` left; a transfer carries the last trade's."""
    for j in range(idx, -1, -1):
        if events[j].x is not None:
            return events[j].x
    return None


def _nth_trade_after(events: list[Event], idx: int, n: int) -> int | None:
    """Index of the n-th event with a reserve, strictly after `idx`."""
    seen = 0
    for j in range(idx + 1, len(events)):
        if events[j].x is None:
            continue
        seen += 1
        if seen == n:
            return j
    return None


def _last_trade(events: list[Event]) -> int | None:
    for j in range(len(events) - 1, -1, -1):
        if events[j].x is not None:
            return j
    return None


# -------------------------------------------------------------------- rule

def apply(events: list[Event], creator: str | None = None,
          params: Params = Params()) -> Outcome:
    """Run the rule on one token's event stream."""
    a = anchor_index(events, params.n_holders_target)
    if a is None:
        return Outcome(False, "no_anchor")

    t_a = events[a].t
    x_a = reserve_after(events, a)
    if x_a is None:
        return Outcome(False, "no_reserve_at_anchor", anchor_idx=a, t_anchor=t_a)

    bal = ledger_at(events, a)
    pos = [v for v in bal.values() if v > 0]
    tot = sum(pos)
    g = _gini(pos)
    cs = (bal.get(creator, 0.0) / tot) if (creator is not None and tot > 0) else 0.0
    cs = max(cs, 0.0)

    base = Outcome(False, "", anchor_idx=a, t_anchor=t_a, x_anchor=x_a,
                   gini=g, creator_share=cs)

    if not (t_a > params.min_t_anchor_s):
        base.reason = "anchor_too_early"
        return base

    if params.tertile_cut is None:
        raise ValueError(
            "tertile_cut is required: the tertile boundary is cross-sectional "
            "and cannot be derived from one token.  Measured values are "
            "gini <= 0.267351881, creator_share <= 0.432181919 "
            "(sql/tertile_cutoff.sql).")
    feat = g if params.tertile_feature == "gini" else cs
    if feat > params.tertile_cut:
        base.reason = "not_lower_tertile"
        return base

    ei = _nth_trade_after(events, a, params.entry_delay)
    if ei is None:
        base.reason = "entry_never_filled"
        return base
    x_entry = events[ei].x

    # exit: crossing, then the delay; fall back to the last trade
    xi, censored = None, True
    if params.target_mult is not None:
        for j in range(a + 1, len(events)):
            if events[j].x is not None and events[j].x >= x_a * params.target_mult:
                xi = _nth_trade_after(events, j, params.exit_delay)
                censored = xi is None
                break
    if xi is None:
        xi = _last_trade(events)
    if xi is None or xi <= ei:
        xi = ei                      # nothing after the entry: exit where we are
    x_exit = events[xi].x

    q = params.q
    pnl = cost_model.net_pnl(Decimal(str(x_entry)), q, V=0,
                             W=Decimal(str(x_exit)) - Decimal(str(x_entry)),
                             fixed_cost_per_leg=params.fixed_cost)
    base.traded = True
    base.reason = "traded"
    base.entry_idx, base.x_entry = ei, x_entry
    base.exit_idx, base.x_exit = xi, x_exit
    base.censored = censored
    base.pnl, base.ret = pnl, pnl / q
    return base


FIXTURE = [
    Event(1, 0.5, 31.0, "A", +100.0),
    Event(2, 1.0, 33.0, "B", +100.0),
    Event(3, 4.0, 40.0, "C", +100.0),   # anchor: 3rd holder, t = 4.0 > 3.0
    Event(4, 4.5, 41.0, "D", +10.0),
    Event(5, 5.0, 42.0, "E", +10.0),
    Event(6, 5.5, 44.0, "F", +10.0),    # entry: 3rd trade after the anchor
    Event(7, 6.0, 60.0, "G", +10.0),
    Event(8, 7.0, 71.0, "H", +10.0),    # crossing: 71.0 >= 40 * 1.76 = 70.4
    Event(9, 8.0, 75.0, "I", +10.0),
    Event(10, 9.0, 80.0, "J", +10.0),
    Event(11, 10.0, 90.0, "K", +10.0),  # exit: 3rd trade after the crossing
    Event(12, 11.0, 50.0, "L", -10.0),
]


def main() -> None:
    o = apply(FIXTURE, creator="A")
    print(f"anchor idx {o.anchor_idx} t {o.t_anchor} x_a {o.x_anchor}")
    print(f"gini {o.gini:.6f}  creator_share {o.creator_share:.6f}")
    print(f"entry idx {o.entry_idx} x {o.x_entry}   exit idx {o.exit_idx} x {o.x_exit}")
    print(f"traded {o.traded} censored {o.censored} pnl {o.pnl:.9f} ret {o.ret:.9f}")


if __name__ == "__main__":
    main()
