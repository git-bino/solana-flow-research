"""The causal rule — one exit parameter, on an executable clock.

  python -m src.causal_rule            # replay on chunk 1

SUPERSEDES `frozen_rule.py` (renamed 2026-08-20).  An external audit stopped the
confirmation over two execution defects; the freeze recorded in
`audit/phase1/11_frozen_rule.md` is VOID.  Both are fixed here.

DEFECT 1 -- entry reserve.  The entry was struck on `depth_x`, the reserve at the
trigger ROW, while the exit was struck on `x_end_slot + cumf[a]`.  The difference
`x_end_slot - depth_x` is flow that landed in the trigger slot BEFORE any order
could exist, and it was being booked as post-entry profit.  The entry now sits on
the reserve that is actually known when the decision is made.

DEFECT 2 -- one-slot lookahead.  `nf3(L)` is only complete once slot `s+L` has
closed, so the earliest executable fill is `s+L+1`.  Entry and exit both now
decide at the end of a slot and fill in the next one.

This module deliberately does not import `src.fwd_net_ret`, `src.exit_latency`,
`src.exploratory_search` or any other search module.  The trajectory recursion
and the path arithmetic are re-derived here so that a mistake in the search code
cannot silently reproduce itself; `tests/test_causal_rule.py` checks this
implementation against `src.reconstruct_label` and `src.cost_model` instead.

THE RULE
--------
    watch a burst, wait `L` slots
    the exit rule is live from age 3 onward: exit at the first a >= 3 with
    nf3(a) <= 0
    DECIDE at end(s+L), knowing nf3(L).  If the exit already fired at a <= L the
    flow broke while waiting and nothing opens -- NOT TRADED.
    otherwise FILL at s+L+1, against the reserve known at end(s+L), which is
    `x_end_slot + cumf[L]`
    the exit predicate becomes known at end(a_exit) and fills at a_exit + 1 + Lx

    no age limit (A = 75 is just the trajectory length), no stop loss, k = 1

The trade gate stays `a_exit > L` (research lead, 2026-08-20): the decision uses
only what end(s+L) knows.  A row whose exit fires at exactly L+1 still enters and
then leaves on the next slot.

Intra-slot ordering inside the fill slot `s+L+1` is NOT modelled: the entry is
struck on the end-of-`s+L` reserve, which assumes none of that slot's flow lands
ahead of us.  The opposite assumption (all of it does) is measured as a stress
cell in docs/audit2_fix.md rather than silently chosen.
ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (reporting both, not picking one).

Note on the entry condition.  The brief states it as "at s+L, if nf3 > 0 then
enter".  The operational rule is stronger: the exit rule is already running from
age 3, so a burst whose nf3 first went non-positive at age 5 was exited at 5 and
was never available to enter at 8.  `nf3(L) > 0` alone is implied by, but does
not imply, `a_exit > L`.  Both are computed and the difference is reported;
`a_exit > L` is the one that reproduces the search's numbers.

Prices: one base for both ends -- `x_end_slot` plus the reconstructed cumulative
flow -- fee 1.25% per side, `cost_model`'s path arithmetic.  `depth_x` is no
longer used for pricing; it is kept only to report the gap it used to create.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TRAJ = 75
FIRST_AGE = 3
FEE = Decimal("0.0125")
#: k = x0 * y0 for the SOL curve, the same constant `cost_model` derives.
K = Decimal(30_000_000_000) / Decimal(10**9) * Decimal(1_073_000_000_000_000) / Decimal(10**6)

DEFAULTS = {"L": 8, "q": Decimal(5), "Lx": 0, "pf": Decimal(0)}
SENSITIVITY = {"L": (1, 3, 8), "q": (Decimal("0.5"), Decimal(1), Decimal(2), Decimal(5)),
               "Lx": (0, 1, 3, 8), "pf": (Decimal(0), Decimal("0.001"), Decimal("0.01"))}


@dataclass
class Outcome:
    traded: bool
    entry_slot: int | None       # age at which the entry FILLS, = L + 1
    exit_slot: int | None        # age at which the exit fills
    pnl: Decimal | None
    exit_age_rule: int           # age the rule fired, before any exit latency
    censored: bool               # rule never fired inside 75 ages


def slot_flows(nf3: list[float], excl1: float, excl2: float) -> list[float]:
    """Per-slot net flow f(1..75) from the 3-slot rolling sum.

    nf3(a) = f(a-2) + f(a-1) + f(a) with f indexed from -1, so

        f(1) = excl1
        f(2) = excl2 - excl1
        f(3) = nf3(3) - excl2
        f(a) = nf3(a) - nf3(a-1) + f(a-3)      a >= 4
    """
    f = [0.0] * (TRAJ + 1)                  # 1-indexed
    f[1] = excl1
    f[2] = excl2 - excl1
    f[3] = nf3[2] - excl2
    for a in range(4, TRAJ + 1):
        f[a] = nf3[a - 1] - nf3[a - 2] + f[a - 3]
    return f


def exit_age(nf3: list[float]) -> tuple[int, bool]:
    """First age >= 3 with nf3 <= 0; (75, True) when it never happens."""
    for a in range(FIRST_AGE, TRAJ + 1):
        if nf3[a - 1] <= 0:
            return a, False
    return TRAJ, True


def net_pnl(x_obs: Decimal, q: Decimal, V: Decimal, W: Decimal,
            pf: Decimal) -> Decimal:
    """The §5 path: fill on x_obs + V, exit against x_obs + V + q + W."""
    x1 = x_obs + V
    dy = K / x1 - K / (x1 + q)
    x2 = x1 + q + W
    out = dy * x2 * x2 / (K + dy * x2)
    return out * (1 - FEE) - q / (1 - FEE) - 2 * pf


def apply(nf3, excl1, excl2, x_end, depth_x=None, *, L=None, q=None, Lx=None,
          pf=None) -> Outcome:
    """Run the rule on one burst.  `depth_x` is accepted but NOT used in pricing."""
    L = DEFAULTS["L"] if L is None else L
    q = DEFAULTS["q"] if q is None else Decimal(str(q))
    Lx = DEFAULTS["Lx"] if Lx is None else Lx
    pf = DEFAULTS["pf"] if pf is None else Decimal(str(pf))

    a_rule, censored = exit_age(nf3)
    if a_rule <= L:
        return Outcome(False, None, None, None, a_rule, censored)

    f = slot_flows(nf3, excl1, excl2)
    cum = [Decimal(0)] * (TRAJ + 1)
    acc = Decimal(0)
    for a in range(1, TRAJ + 1):
        acc += Decimal(str(f[a]))
        cum[a] = acc

    # entry: decided at end(s+L), filled in s+L+1, struck on the reserve that
    # end(s+L) knows.  x_end_slot is the base at BOTH ends -- depth_x is not used.
    a_entry = min(L + 1, TRAJ)
    x_entry_obs = Decimal(str(x_end)) + cum[L]
    # exit: predicate known at end(a_rule), filled one slot later, plus Lx
    a_fill = min(a_rule + 1 + Lx, TRAJ)
    W = cum[a_fill] - cum[L]
    pnl = net_pnl(x_entry_obs, q, Decimal(0), W, pf)
    return Outcome(True, a_entry, a_fill, pnl, a_rule, censored)


# --------------------------------------------------------------- batch replay

def replay(rows, **kw) -> dict:
    """Apply the rule to an iterable of (nf3, excl1, excl2, x_end, depth_x)."""
    pnl, ages, n_seen, n_cens = [], [], 0, 0
    weak_entry = 0
    L = kw.get("L") or DEFAULTS["L"]
    for nf3, e1, e2, xe, dx in rows:
        n_seen += 1
        o = apply(nf3, e1, e2, xe, dx, **kw)
        if nf3[L - 1] > 0:
            weak_entry += 1
        if o.traded:
            pnl.append(o.pnl)
            ages.append(o.exit_age_rule)
            n_cens += o.censored
    arr = np.array([float(p) for p in pnl])
    return {"n_seen": n_seen, "n_traded": len(pnl),
            "n_weak_entry_condition": weak_entry,
            "expectancy": float(arr.mean()) if len(arr) else float("nan"),
            "median": float(np.median(arr)) if len(arr) else float("nan"),
            "share_positive": float((arr > 0).mean()) if len(arr) else float("nan"),
            "censored": n_cens,
            "exit_age": {"median": float(np.median(ages)) if ages else float("nan"),
                         "p90": float(np.percentile(ages, 90)) if ages else float("nan"),
                         "p99": float(np.percentile(ages, 99)) if ages else float("nan"),
                         "max": int(max(ages)) if ages else 0},
            "pnl": arr}


def load_chunk1():
    from src.load_clickhouse_v2 import client
    cols = client().query(
        "SELECT nf3_traj_75_incl_pre, nf3_excl_pre_1, nf3_excl_pre_2, "
        "       x_end_slot, depth_x FROM flow.burst_v2 WHERE NOT mayhem"
    ).result_columns
    return list(zip([list(r) for r in cols[0]], cols[1], cols[2], cols[3], cols[4]))


def main() -> None:
    rows = load_chunk1()
    r = replay(rows)
    print(f"n_seen {r['n_seen']:,}  n_traded {r['n_traded']:,}  "
          f"expectancy {r['expectancy']:+.6f}  median {r['median']:+.6f}  "
          f">0 {100*r['share_positive']:.2f}%")
    print(f"сул орох нөхцөл (nf3(L) > 0) л хангасан мөр: "
          f"{r['n_weak_entry_condition']:,}")
    print(f"гарах нас: median {r['exit_age']['median']:.1f}  "
          f"p90 {r['exit_age']['p90']:.1f}  p99 {r['exit_age']['p99']:.1f}  "
          f"max {r['exit_age']['max']}  censored {r['censored']}")
    ok_n = r["n_traded"] == 5_402
    print(f"\nn = 5,402 таарах эсэх: {ok_n}  (expectancy нь засварын дараа ӨӨР байх ёстой)")


if __name__ == "__main__":
    main()
