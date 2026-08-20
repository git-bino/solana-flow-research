"""The frozen rule — one exit parameter, written independently of the search code.

  python -m src.frozen_rule            # replay on chunk 1 and check the targets

This module deliberately does not import `src.fwd_net_ret`, `src.exit_latency`,
`src.exploratory_search` or any other search module.  The trajectory recursion
and the path arithmetic are re-derived here so that a mistake in the search code
cannot silently reproduce itself; `tests/test_frozen_rule.py` checks this
implementation against `src.reconstruct_label` and `src.cost_model` instead.

THE RULE
--------
    watch a burst, wait `L` slots
    the exit rule is live from age 3 onward: exit at the first a >= 3 with
    nf3(a) <= 0
    if that exit would land at or before `L`, the position never opened -- NOT
    TRADED
    otherwise enter `q` SOL at s+L and leave at a_exit (+ `Lx` if an exit latency
    is applied)

    no age limit (A = 75 is just the trajectory length), no stop loss, k = 1

Note on the entry condition.  The brief states it as "at s+L, if nf3 > 0 then
enter".  The operational rule is stronger: the exit rule is already running from
age 3, so a burst whose nf3 first went non-positive at age 5 was exited at 5 and
was never available to enter at 8.  `nf3(L) > 0` alone is implied by, but does
not imply, `a_exit > L`.  Both are computed and the difference is reported;
`a_exit > L` is the one that reproduces the search's numbers.

Prices: entry fill on the observable depth (`depth_x` + flow during latency, the
§5 fill), reserve path on `x_end_slot` + reconstructed cumulative flow, fee
1.25% per side, `cost_model`'s path arithmetic.
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
    entry_slot: int | None       # age at which the entry lands, = L
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


def apply(nf3, excl1, excl2, x_end, depth_x, *, L=None, q=None, Lx=None,
          pf=None) -> Outcome:
    """Run the rule on one burst.  All money arguments are Decimal-friendly."""
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

    a_fill = min(a_rule + Lx, TRAJ)
    V = cum[L]
    # the reserve path is rooted at x_end_slot; the fill is struck on depth_x
    W = cum[a_fill] - V + (Decimal(str(x_end)) - Decimal(str(depth_x)))
    pnl = net_pnl(Decimal(str(depth_x)), q, V, W, pf)
    return Outcome(True, L, a_fill, pnl, a_rule, censored)


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
    ok_e = abs(r["expectancy"] - 0.450435) < 5e-6
    print(f"\nтулгалт: n = 5,402 → {ok_n};  expectancy = +0.450435 → {ok_e}")
    if not (ok_n and ok_e):
        raise SystemExit("ЗӨРӨВ — зогсов")
    print("ТААРАВ")


if __name__ == "__main__":
    main()
