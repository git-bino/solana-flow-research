"""The B1 rule — one function, re-derived independently of the analysis code.

  python -m src.b1_rule            # self-check on the built-in fixture

This module deliberately does NOT import `src.holder_anchor`, `src.anchor_rule`,
`src.execution_gap`, `src.asymmetric_barriers`, `src.fill_timing` or any SQL
text.  The ledger, the holder count, the anchor, the prior-token win rate, the
quintile filter, the entry and exit delays and the arithmetic are all written out
again here, so a mistake in the analysis path cannot reproduce itself in the
check.  `src.cost_model` IS imported: it is the sanctioned pricing module and the
rule specifies its exact path arithmetic.

THE RULE
--------
    UNIVERSE -- CAUSAL, changed 2026-08-21 (audit 4 fix 1)
      `createevent.is_mayhem_mode = false`, a LAUNCH-TIME observable.
      The universe WAS `max|x*y/k0 - 1| < 1e-6`, an invariant over the token's
      WHOLE LIFE: at the anchor nobody can know whether the token will leave the
      invariant later, so that filter was whole-life lookahead.
      Measured on the switch: 437 tokens leave the universe (179,725 -> 179,288)
      and ZERO of them had an H20 anchor, so every anchor-level baseline is
      unchanged (x>=60 37.44%, x_a p50 43.84, t_60 p50 17.1 s).  The prior-token
      universe is switched too (sql/causal_universe.sql), which moves
      b1_q5_lower by +0.000010930 and the subset by +1 token.
      `is_clean()` is kept below as a DIAGNOSTIC and is NOT consulted for
      admission; `decide()` never calls it.

    ANCHOR
      walk the token's events in `seq` order keeping a TRANSFER-AWARE ledger
        balance(w) = (bought - sold) + (received - sent)        [oh_a mechanism]
      a wallet HOLDS while balance(w) > 0.
      ANCHOR = the first event at whose END the holder count reaches 20.  The
      event itself counts: the condition cannot be known before it completes.
      x_a  = the reserve that anchor event LEFT.  `virtual_sol_reserves` on
      pump.fun's TradeEvent is the POST-trade reserve (proved in
      sql/phase0_kill_gate.sql, 74,733 / 74,733 first trades imply x0 = 30 SOL).
      A transfer moves units, not reserves, so the last trade's reserve carries.

    FILTER -- both of
      B1 = the MEDIAN over the 20 anchor wallets of each wallet's prior win rate
      B2 = the 90th PERCENTILE of the same values
      must be at or above the cross-sectional q5 lower boundary.

    WIN RATE, LOOKAHEAD-FREE.  For a token launched on day D, a wallet's prior
    token counts in the DENOMINATOR when the wallet's first trade on it fell on
    a day strictly before D, and in the NUMERATOR when

        d_w = max(day the wallet first traded it, day it first reached x >= 60)

    is also strictly before D.  A prior token that reached 60 only AFTER D
    contributes to the denominator and not to the numerator: at D nobody could
    know it would get there.  This is the correction made on 2026-08-21; the
    earlier build used `max_x >= 60` over the prior token's whole life to
    2026-08-15, which is future information (docs/b1_economics.md §0).

    ENTRY = the 3rd TRADE event after the anchor, priced on the reserve that
            event left.  Fewer than 3 trade events after the anchor -> NOT TRADED
            (the order never fills; that is not a zero and not a loss).
    EXIT  = whichever comes first of
              target: the first trade event after entry with x >= 60
              time:   the first trade event after entry at least 60 s after the
                      anchor
            on an exact tie the TARGET is taken.  No stop.
            The FILL is the 3rd trade event AFTER the trigger event, priced on
            the reserve that event left -- the OVERSHOOT price, not the price at
            which the condition was met.
    PRICE P = x^2 / k, fee 1.25% PER SIDE, own price impact on both legs and a
            fixed cost per leg, all through `cost_model.net_pnl`.

    TERMINAL STATE -- NO FALLBACKS, changed 2026-08-21 (audit 4 fix 2)
      CLOSED_TARGET    x >= 60 fired first and the 3rd event after it exists
      CLOSED_TIME      the 60 s limit fired first and that 3rd event exists
      OPEN_NO_FILL     a trigger fired but the 3rd event after it does not exist
      OPEN_NO_TRIGGER  no trigger ever fired
    An OPEN position has NO realised PnL.  `ret` is None -- not zero, not a
    fee-only round trip, not the last observed reserve.  The earlier
    `unfilled_exit` parameter offered exactly those fallbacks and is REMOVED:
    "entry_price" priced a position that could not be closed as if it had been
    closed at its own entry.  Measured at the frozen delay: 13.61% of baseline
    positions and 12.21% of subset positions are OPEN, and the OPEN rows sit at
    x_last/x_entry p50 = 0.7068 / 0.7136 -- far below entry.  Any caller that
    wants a number for them must supply its own assumption, in the open.

FROZEN CONSTANTS (research lead, 2026-08-21):
    q = 0.5 SOL, fixed_cost_per_leg = 0.001 SOL, T = 60 s, S = infinity,
    G = x >= 60, anchor H20, entry delay 3 events, exit delay 3 events.

FROZEN QUINTILE BOUNDARIES, measured 2026-08-21 on the 21,724-token measurement
sample (`sql/b1_boundaries.sql`), NEAREST-RANK p80 = sorted[ceil(0.8*n) - 1]:

    b1_q5_lower = 0.572916667        b2_q5_lower = 1.000000000

They are DOCUMENTED here and are still REQUIRED arguments -- they are not
defaults, because a default would let the rule run on a sample whose boundaries
were never checked.  Recomputing them on the holdout would be lookahead.
Measured against the two alternatives: identical to the mid-rank quintile cut
the analysis used (delta 0.000000000, same 2,571 tokens); `approx_percentile`
gives 0.571695476 / 0.989173410, six tokens more, x>=60 share 0.0101 pt lower.

TWO CONVENTIONS THAT ARE PARAMETERS, NOT CONSTANTS -- both are stated because
they change results and neither is self-evident:

  `percentile`  B1/B2 are a median and a p90 over ~20 values.  Dune computed
      them with `approx_percentile`, a t-digest.  This module uses NEAREST-RANK
      (`sorted[ceil(p*n) - 1]`).  The two agree on most 20-element inputs but not
      on all, so this is a named parity risk, not an identity.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from decimal import Decimal

from src import cost_model

# --- the frozen constants -----------------------------------------------------

Q_SOL = Decimal("0.5")
FIXED_COST_PER_LEG = Decimal("0.001")
TIME_LIMIT_S = 60.0
TARGET_X = 60.0
ANCHOR_HOLDERS = 20
ENTRY_DELAY_EVENTS = 3
EXIT_DELAY_EVENTS = 3
CLEAN_TOL = 1e-6


@dataclass(frozen=True)
class Event:
    """One event in `seq` order.

    `x` is the reserve AFTER the event and `y` the token side after it; both are
    None for a transfer, which moves units without touching the curve.
    `legs` is the signed unit change per wallet caused by this event; a trade has
    one leg, a transfer has two that sum to zero.
    """

    seq: int
    unix: float
    x: float | None
    y: float | None
    legs: tuple[tuple[str, float], ...]

    @property
    def is_trade(self) -> bool:
        return self.x is not None


@dataclass(frozen=True)
class PriorToken:
    """One (wallet, earlier token) pair, as of the wallet's own activity.

    `first_trade_day` is the day the wallet first traded that token.
    `t60_day` is the day that token first reached x >= 60, or None if it never
    did inside the observation window.
    """

    wallet: str
    first_trade_day: _dt.date
    t60_day: _dt.date | None


@dataclass(frozen=True)
class Params:
    """Everything that is not a property of the single token.

    `b1_q5_lower` and `b2_q5_lower` are CROSS-SECTIONAL quantities -- they cannot
    be computed from one token -- so they are REQUIRED.  Passing None raises
    rather than silently disabling the filter, the same discipline
    `src.anchor_rule.Params.tertile_cut` uses.  Recomputing them on a new sample
    would be lookahead; they are frozen from the measurement sample.
    """

    b1_q5_lower: float | None = None
    b2_q5_lower: float | None = None
    q: Decimal = Q_SOL
    fixed_cost_per_leg: Decimal = FIXED_COST_PER_LEG
    time_limit_s: float = TIME_LIMIT_S
    target_x: float = TARGET_X
    anchor_holders: int = ANCHOR_HOLDERS
    entry_delay: int = ENTRY_DELAY_EVENTS
    exit_delay: int = EXIT_DELAY_EVENTS
    clean_tol: float = CLEAN_TOL
    percentile: str = "nearest_rank"

    def __post_init__(self) -> None:
        if self.b1_q5_lower is None or self.b2_q5_lower is None:
            raise ValueError(
                "b1_q5_lower and b2_q5_lower are required: the quintile "
                "boundaries are cross-sectional and must be frozen from the "
                "measurement sample, never recomputed on the sample being scored"
            )
        if self.percentile != "nearest_rank":
            raise ValueError(f"unknown percentile convention {self.percentile!r}")


@dataclass
class Decision:
    """What the rule did with one token.

    `traded` False means no position was opened at all.  `traded` True with
    `state` starting OPEN_ means a position was opened and never closed: `ret` is
    None and MUST NOT be read as zero.
    """

    token: str
    traded: bool = False
    state: str = ""
    reason: str = ""
    anchor_seq: int | None = None
    anchor_unix: float | None = None
    x_a: float | None = None
    anchor_wallets: tuple[str, ...] = ()
    b1: float | None = None
    b2: float | None = None
    entry_seq: int | None = None
    x_entry: float | None = None
    trigger_seq: int | None = None
    trigger_kind: str = ""
    exit_seq: int | None = None
    x_exit: float | None = None
    pnl_sol: Decimal | None = None
    ret: Decimal | None = None
    hold_s: float | None = None
    diag: dict = field(default_factory=dict)


# --- pieces, each written out rather than imported ----------------------------


def is_clean(events, tol: float = CLEAN_TOL) -> bool:
    """max|x*y/k0 - 1| < tol over the token's TRADE events, k0 from the first.

    The expression is monotone in x*y, so the maximum deviation is attained at
    the smallest or the largest product; both are checked rather than every row.
    """
    prods = [e.x * e.y for e in events if e.is_trade and e.x is not None and e.y is not None]
    if not prods:
        return False
    k0 = prods[0]
    if k0 <= 0:
        return False
    return max(abs(max(prods) / k0 - 1.0), abs(min(prods) / k0 - 1.0)) < tol


def nearest_rank(values, p: float) -> float | None:
    """sorted[ceil(p*n) - 1].  None for an empty input.  See the module note."""
    vs = sorted(v for v in values if v is not None)
    if not vs:
        return None
    idx = max(0, min(len(vs) - 1, math.ceil(p * len(vs)) - 1))
    return vs[idx]


def find_anchor(events, n_target: int = ANCHOR_HOLDERS):
    """First event at whose END the transfer-aware holder count reaches n_target.

    Returns (index, x_a, holder_wallets) or None.  `x_a` is the last trade
    reserve at or before the anchor, because a transfer leaves the curve alone.
    """
    balance: dict[str, float] = {}
    last_x: float | None = None
    for i, ev in enumerate(events):
        if ev.is_trade:
            last_x = ev.x
        for w, du in ev.legs:
            balance[w] = balance.get(w, 0.0) + du
        holders = tuple(sorted(w for w, b in balance.items() if b > 0))
        if len(holders) >= n_target:
            return i, last_x, holders
    return None


def wallet_win_rate(wallet: str, launch_day: _dt.date, priors) -> float | None:
    """Prior win rate of one wallet as known on `launch_day`.

    Denominator: that wallet's tokens whose first trade day is strictly before
    `launch_day`.  Numerator: those of them whose d_w = max(first_trade_day,
    t60_day) is also strictly before `launch_day`.  None when the denominator is
    zero -- no history is not a win rate of zero.
    """
    den = num = 0
    for p in priors:
        if p.wallet != wallet or not (p.first_trade_day < launch_day):
            continue
        den += 1
        if p.t60_day is not None and max(p.first_trade_day, p.t60_day) < launch_day:
            num += 1
    return None if den == 0 else num / den


def _delayed(events, trigger_idx: int, delay: int) -> int | None:
    """Index of the `delay`-th TRADE event strictly after `trigger_idx`."""
    seen = 0
    for j in range(trigger_idx + 1, len(events)):
        if not events[j].is_trade:
            continue
        seen += 1
        if seen == delay:
            return j
    return None


# --- the rule -----------------------------------------------------------------


def decide(token: str, events, launch_day: _dt.date, priors, params: Params,
           *, mayhem_flag: bool = False) -> Decision:
    """Apply the frozen rule to one token.  Pure; no I/O, no globals.

    `mayhem_flag` is `createevent.is_mayhem_mode` for THIS token -- a launch-time
    observable, so it is a property of the token and not a frozen constant.
    ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР: it defaults to False (= not flagged), the
    literal meaning of an absent flag, rather than being required the way the
    cross-sectional boundaries are.
    """
    d = Decision(token=token)
    evs = sorted(events, key=lambda e: e.seq)

    if mayhem_flag:
        d.reason = d.state = "mayhem_at_launch"
        return d

    found = find_anchor(evs, params.anchor_holders)
    if found is None:
        d.reason = "no_anchor"
        return d
    a_idx, x_a, holders = found
    if x_a is None or x_a <= 0:
        d.reason = "no_reserve_at_anchor"
        return d
    d.anchor_seq = evs[a_idx].seq
    d.anchor_unix = evs[a_idx].unix
    d.x_a = x_a
    d.anchor_wallets = holders

    rates = [wallet_win_rate(w, launch_day, priors) for w in holders]
    known = [r for r in rates if r is not None]
    d.b1 = nearest_rank(known, 0.50)
    d.b2 = nearest_rank(known, 0.90)
    d.diag["n_wallets_with_history"] = len(known)
    if d.b1 is None or d.b2 is None:
        d.reason = "no_wallet_history"
        return d
    if d.b1 < params.b1_q5_lower or d.b2 < params.b2_q5_lower:
        d.reason = "filtered_out"
        return d

    e_idx = _delayed(evs, a_idx, params.entry_delay)
    if e_idx is None or evs[e_idx].x is None or evs[e_idx].x <= 0:
        d.reason = "entry_never_fills"
        return d
    d.entry_seq = evs[e_idx].seq
    d.x_entry = evs[e_idx].x

    t_idx = g_idx = None
    for j in range(e_idx + 1, len(evs)):
        ev = evs[j]
        if not ev.is_trade:
            continue
        if g_idx is None and ev.x >= params.target_x:
            g_idx = j
        if t_idx is None and ev.unix - d.anchor_unix >= params.time_limit_s:
            t_idx = j
        if g_idx is not None and t_idx is not None:
            break
    if g_idx is not None and (t_idx is None or g_idx <= t_idx):
        trig_idx, kind = g_idx, "target"
    elif t_idx is not None:
        trig_idx, kind = t_idx, "time"
    else:
        trig_idx, kind = None, "end"
    d.trigger_kind = kind

    if trig_idx is None:
        x_idx = None
    else:
        d.trigger_seq = evs[trig_idx].seq
        x_idx = _delayed(evs, trig_idx, params.exit_delay)

    if x_idx is None:
        # OPEN: no realised PnL.  NO fallback price is invented here.
        d.traded = True
        d.state = "OPEN_NO_TRIGGER" if trig_idx is None else "OPEN_NO_FILL"
        d.reason = d.state
        last = max((j for j in range(e_idx + 1, len(evs)) if evs[j].is_trade),
                   default=None)
        if last is not None:                       # DIAGNOSTIC ONLY, never priced
            d.diag["x_last_over_x_entry"] = evs[last].x / d.x_entry
        return d
    x_exit = evs[x_idx].x
    d.exit_seq = evs[x_idx].seq
    d.hold_s = evs[x_idx].unix - evs[e_idx].unix
    d.x_exit = x_exit
    d.state = "CLOSED_TARGET" if kind == "target" else "CLOSED_TIME"

    q = params.q
    pnl = cost_model.net_pnl(
        Decimal(str(d.x_entry)), q, V=0,
        W=Decimal(str(x_exit)) - Decimal(str(d.x_entry)),
        fixed_cost_per_leg=params.fixed_cost_per_leg,
    )
    d.pnl_sol = pnl
    d.ret = pnl / q
    d.traded = True
    d.reason = d.state
    return d


# --- built-in fixture ---------------------------------------------------------

def _fixture():
    """Hand-built token: 20 wallets enter one by one, then the reserve runs up.

    Seq 1..20 are buys by w01..w20, so the holder count reaches 20 at seq 20 and
    that event leaves the reserve at 40.0.  Seq 21..23 are the entry delay, so
    the entry fills at seq 23 on a reserve of 44.0.  Seq 26 is the first event at
    or above 60; the fill is the 3rd event after it, seq 29, at 90.0.
    """
    K = 30.0 * 1_073_000_000.0
    xs = ([30.0 + 0.5 * i for i in range(1, 20)] + [40.0]
          + [41.0, 42.0, 44.0, 50.0, 55.0, 71.0, 80.0, 85.0, 90.0, 95.0])
    evs = []
    for i, x in enumerate(xs, start=1):
        w = f"w{i:02d}" if i <= 20 else "w01"
        evs.append(Event(seq=i, unix=float(i), x=x, y=K / x, legs=((w, 1000.0),)))
    priors = [PriorToken(f"w{i:02d}", _dt.date(2026, 5, 10), _dt.date(2026, 5, 10))
              for i in range(1, 21)]
    return evs, priors


def main() -> None:
    evs, priors = _fixture()
    p = Params(b1_q5_lower=0.5, b2_q5_lower=0.5)
    d = decide("FIXTURE", evs, _dt.date(2026, 5, 12), priors, p)
    print(f"anchor seq {d.anchor_seq}  x_a {d.x_a}  b1 {d.b1}  b2 {d.b2}")
    print(f"entry seq {d.entry_seq}  x_entry {d.x_entry}")
    print(f"trigger {d.trigger_kind} seq {d.trigger_seq}  exit seq {d.exit_seq}  "
          f"x_exit {d.x_exit}")
    print(f"pnl {d.pnl_sol}  ret {d.ret}")


if __name__ == "__main__":
    main()
