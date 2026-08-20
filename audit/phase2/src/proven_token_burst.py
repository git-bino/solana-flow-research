"""C -- the causal rule on bursts filtered by `depth_x`, plus the
"distribution has not changed" filter.

    python -m src.proven_token_burst

LOCAL ONLY, 0 credit.  Reads `flow.burst_v2` and nothing else.

THE RULE is `src.causal_rule` unchanged: decide at end(s+L), fill at s+L+1,
price on `x_end_slot + cumf[L]`, exit predicate at end(a_exit) fills at
a_exit + 1 + Lx.  Defaults L = 8, q = 5 SOL, Lx = 0, pf = 0.  Baseline
expectancy on the unfiltered 5,402 traded rows is -0.168718.

--------------------------------------------------------------------------
NO LOOKAHEAD IN THE FILTER -- proved from the schema, not asserted
--------------------------------------------------------------------------
`depth_x` is the SOL reserve on the trigger row itself, i.e. the state of the
curve at the moment the burst fires.  It is an observable, not an outcome.

`max_x` and `t_60` ARE outcomes and must not filter.  They cannot be used here
even by accident: neither is a column of `flow.burst_v2`.  `_assert_no_outcome_
columns()` below queries `system.columns` and fails loudly if either ever
appears.  The only Dune object that holds them, `result_flow_token_base`, is
remote and no Dune client is imported by this module.

The distribution-change filter uses `oh_n_wallets_a` and `oh_conc_a` of the
PREVIOUS burst on the same token.  A previous burst is strictly in the past of
the current one (ordered by slot, tx_index, event_seq), and `oh_*_a` is itself
trailing -- built from the watch window up to and including the trigger row --
so the delta is known at the current burst's moment.

--------------------------------------------------------------------------
CLUSTER STRUCTURE (written out explicitly, as the task requires)
--------------------------------------------------------------------------
Rows are BURSTS.  Bursts repeat within a token and pile up within a minute, and
the two groupings CROSS: a given minute contains bursts of many tokens and a
given token has bursts in many minutes.  So this is Owen's (2007) pigeonhole
two-way bootstrap for CROSSED clusters -- resample token clusters with
replacement AND minute clusters with replacement, weight each row by the product
of its two multiplicities, B = 2,000.

This is NOT the situation of `src/early_cluster_ci.py`, where the row was a
TOKEN and token was nested inside launch-day so the two-way construction
collapsed.  Here the two factors genuinely cross and the two-way bootstrap
applies.

Clusters are drawn from the token/minute universe PRESENT IN THE FILTERED SUBSET
being reported, not from the full 126,089 rows: the estimand of each line is the
expectancy on that subset.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import causal_rule
from src.load_clickhouse_v2 import client

B = 2_000
SEED = 20260821
Q_SOL = float(causal_rule.DEFAULTS["q"])
BASELINE = -0.168718
THRESHOLDS = [None, 40, 50, 60, 80, 115]
OUTCOME_COLUMNS = ("max_x", "t_60", "t_115", "final_x")


# ------------------------------------------------------------------ guards

def _assert_no_outcome_columns(c) -> list[str]:
    """Fail if flow.burst_v2 ever grows a column that looks past the burst."""
    cols = [r[0] for r in c.query(
        "SELECT name FROM system.columns "
        "WHERE database='flow' AND table='burst_v2'").result_rows]
    bad = [x for x in OUTCOME_COLUMNS if x in cols]
    if bad:
        raise AssertionError(f"outcome column(s) present in burst_v2: {bad}")
    return cols


# ------------------------------------------------------------------- load

def load(c) -> dict:
    cols = c.query(
        "SELECT nf3_traj_75_incl_pre, nf3_excl_pre_1, nf3_excl_pre_2, "
        "       x_end_slot, depth_x, token_mint, minute_bucket, "
        "       slot, tx_index, event_seq, oh_n_wallets_a, oh_conc_a "
        "FROM flow.burst_v2 WHERE NOT mayhem "
        "ORDER BY token_mint, slot, tx_index, event_seq"
    ).result_columns
    return {
        "nf3": [list(r) for r in cols[0]],
        "excl1": np.asarray(cols[1], dtype=float),
        "excl2": np.asarray(cols[2], dtype=float),
        "x_end": np.asarray(cols[3], dtype=float),
        "depth_x": np.asarray(cols[4], dtype=float),
        "token": np.asarray(cols[5]),
        "minute": np.asarray(cols[6]),
        "n_wallets": np.asarray(cols[10], dtype=float),
        "conc": np.asarray(cols[11], dtype=float),
    }


def run_rule(d: dict) -> tuple[np.ndarray, np.ndarray]:
    """Apply the rule row by row.  Returns (traded mask, pnl aligned to rows)."""
    n = len(d["nf3"])
    traded = np.zeros(n, dtype=bool)
    pnl = np.full(n, np.nan)
    for i in range(n):
        o = causal_rule.apply(d["nf3"][i], d["excl1"][i], d["excl2"][i],
                              d["x_end"][i], d["depth_x"][i])
        if o.traded:
            traded[i] = True
            pnl[i] = float(o.pnl)
    return traded, pnl


# --------------------------------------------------- previous-burst deltas

def previous_burst_deltas(d: dict) -> dict:
    """Change in oh_n_wallets_a / oh_conc_a since the PREVIOUS burst of the
    same token.  Rows are already ordered by (token, slot, tx_index, event_seq).

    `has_prev` is False for the first burst of every token; those rows have no
    defined change and are counted separately, never silently folded in.
    """
    tok = d["token"]
    has_prev = np.empty(len(tok), dtype=bool)
    has_prev[0] = False
    has_prev[1:] = tok[1:] == tok[:-1]

    d_wallets = np.full(len(tok), np.nan)
    d_conc = np.full(len(tok), np.nan)
    d_wallets[1:][has_prev[1:]] = (d["n_wallets"][1:] - d["n_wallets"][:-1])[has_prev[1:]]
    d_conc[1:][has_prev[1:]] = (d["conc"][1:] - d["conc"][:-1])[has_prev[1:]]
    return {"has_prev": has_prev, "d_wallets": d_wallets, "d_conc": d_conc}


# --------------------------------------------------------------- bootstrap

def pigeonhole_ci(pnl: np.ndarray, token: np.ndarray, minute: np.ndarray,
                  b: int = B, seed: int = SEED) -> tuple[float, float]:
    """Owen (2007) two-way pigeonhole bootstrap CI of the MEAN.

    Resamples token clusters and minute clusters independently, weights each row
    by the product of its multiplicities, and recomputes the weighted mean.
    """
    if pnl.size == 0:
        return float("nan"), float("nan")
    ti = np.unique(token, return_inverse=True)[1]
    mi = np.unique(minute, return_inverse=True)[1]
    n_t, n_m = ti.max() + 1, mi.max() + 1
    rng = np.random.default_rng(seed)
    means = np.empty(b)
    for k in range(b):
        w_t = np.bincount(rng.integers(0, n_t, n_t), minlength=n_t).astype(float)
        w_m = np.bincount(rng.integers(0, n_m, n_m), minlength=n_m).astype(float)
        w = w_t[ti] * w_m[mi]
        s = w.sum()
        means[k] = np.nan if s == 0 else float((w * pnl).sum() / s)
    lo, hi = np.nanpercentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def cell(name: str, sel: np.ndarray, d: dict, traded: np.ndarray,
         pnl: np.ndarray, *, n_seen_sel: np.ndarray | None = None) -> dict:
    """One reported line.  `sel` selects rows AFTER the rule has been applied."""
    m = sel & traded
    y = pnl[m]
    seen = int((sel if n_seen_sel is None else n_seen_sel).sum())
    if y.size == 0:
        return {"name": name, "n_seen": seen, "n_traded": 0, "n_tokens": 0,
                "expectancy": float("nan"), "per_sol": float("nan"),
                "median": float("nan"), "share_positive": float("nan"),
                "ci_lo": float("nan"), "ci_hi": float("nan"),
                "delta_vs_baseline": float("nan")}
    lo, hi = pigeonhole_ci(y, d["token"][m], d["minute"][m])
    e = float(y.mean())
    return {"name": name, "n_seen": seen, "n_traded": int(y.size),
            "n_tokens": int(np.unique(d["token"][m]).size),
            "expectancy": e, "per_sol": e / Q_SOL,
            "median": float(np.median(y)),
            "share_positive": float((y > 0).mean()),
            "ci_lo": lo, "ci_hi": hi, "delta_vs_baseline": e - BASELINE}


def fmt(r: dict) -> str:
    if r["n_traded"] == 0:
        return f"  {r['name']:<34} n_seen {r['n_seen']:>7,}  арилжаа 0 -- хоосон"
    return (f"  {r['name']:<34} n_seen {r['n_seen']:>7,}  арилжаа {r['n_traded']:>6,}  "
            f"токен {r['n_tokens']:>5,}  exp {r['expectancy']:+.6f}  "
            f"/SOL {r['per_sol']:+.6f}  median {r['median']:+.6f}  "
            f">0 {100*r['share_positive']:5.2f}%  "
            f"CI [{r['ci_lo']:+.6f}, {r['ci_hi']:+.6f}]")


def main() -> None:
    c = client()
    cols = _assert_no_outcome_columns(c)
    print(f"schema guard: `max_x`, `t_60`, `t_115`, `final_x` нь burst_v2-ийн "
          f"{len(cols)} баганын аль нь ч БИШ ✓\n")

    d = load(c)
    traded, pnl = run_rule(d)
    n = len(d["depth_x"])
    print(f"mayhem бус burst {n:,}, арилжигдсан {int(traded.sum()):,}, "
          f"ялгаатай токен {np.unique(d['token']).size:,}, "
          f"ялгаатай минут {np.unique(d['minute']).size:,}")
    base = cell("суурь (шүүлтгүй)", np.ones(n, dtype=bool), d, traded, pnl)
    print(f"суурь expectancy {base['expectancy']:+.6f} "
          f"(бүртгэгдсэн {BASELINE:+.6f}, зөрүү {base['expectancy']-BASELINE:+.9f})\n")

    out: dict = {"B": B, "seed": SEED, "q_sol": Q_SOL, "baseline": BASELINE,
                 "clustering": "pigeonhole two-way, token x minute (CROSSED)",
                 "n_rows": n, "n_traded": int(traded.sum())}

    # ---------------------------------------------------------- C.1 thresholds
    print("C.1 `depth_x` БОСГО ТУТМЫН ДҮРЭМ")
    rows = []
    for th in THRESHOLDS:
        sel = np.ones(n, dtype=bool) if th is None else (d["depth_x"] >= th)
        nm = "суурь (шүүлтгүй)" if th is None else f"depth_x >= {th}"
        r = cell(nm, sel, d, traded, pnl)
        r["threshold"] = th
        rows.append(r)
        print(fmt(r))
    out["thresholds"] = rows

    # ------------------------------------------- C.2 distribution unchanged
    print("\nC.2 ТАРХАЛТ ӨӨРЧЛӨГДӨӨГҮЙ ЭСЭХ (`depth_x >= 60` дотор)")
    dd = previous_burst_deltas(d)
    g60 = d["depth_x"] >= 60
    hp = dd["has_prev"]

    single = g60 & ~hp
    multi = g60 & hp

    # "no previous burst" and "token has exactly one burst" are DIFFERENT sets:
    # the first burst of a 12-burst token has no predecessor but its token is not
    # a one-burst token.  The task named the second; the delta is undefined for
    # the first.  Both are counted, neither is folded into the filtered cells.
    toks, counts = np.unique(d["token"], return_counts=True)
    one_burst_token = np.isin(d["token"], toks[counts == 1])
    g60_one = g60 & one_burst_token

    print(f"  `depth_x >= 60` burst {int(g60.sum()):,}: "
          f"өмнөх burst-гүй {int(single.sum()):,}, өмнөх burst-тэй {int(multi.sum()):,}")
    print(f"  үүнээс НЭГ Л burst-тэй токенийх {int(g60_one.sum()):,} "
          f"(бүх burst дээр нэг burst-тэй токен {int(one_burst_token.sum()):,})")
    out["single_burst"] = {
        "no_previous_burst_rows": int(single.sum()),
        "one_burst_token_rows_ge60": int(g60_one.sum()),
        "one_burst_token_rows_all": int(one_burst_token.sum()),
    }

    wal_ok = multi & (dd["d_wallets"] >= 0)
    conc_ok = multi & (dd["d_conc"] <= 0)
    both = wal_ok & conc_ok
    neither = multi & ~(dd["d_wallets"] >= 0) & ~(dd["d_conc"] <= 0)

    cells = [
        cell("depth_x>=60, БҮГД", g60, d, traded, pnl),
        cell("  өмнөх burst-гүй (Δ тодорхойгүй)", single, d, traded, pnl),
        cell("  НЭГ Л burst-тэй токен", g60_one, d, traded, pnl),
        cell("  өмнөх burst-тэй, БҮГД", multi, d, traded, pnl),
        cell("  эзэмшигч буураагүй (dW>=0)", wal_ok, d, traded, pnl),
        cell("  төвлөрөл өсөөгүй (dC<=0)", conc_ok, d, traded, pnl),
        cell("  ХОЁУЛАА", both, d, traded, pnl),
        cell("  аль нь ч биш", neither, d, traded, pnl),
    ]
    for r in cells:
        print(fmt(r))
    out["distribution_filter"] = cells

    dw = dd["d_wallets"][multi]
    dc = dd["d_conc"][multi]
    out["delta_distribution"] = {
        "n": int(multi.sum()),
        "d_wallets": {"p10": float(np.nanpercentile(dw, 10)),
                      "median": float(np.nanmedian(dw)),
                      "p90": float(np.nanpercentile(dw, 90)),
                      "share_ge_0": float(np.nanmean(dw >= 0))},
        "d_conc": {"p10": float(np.nanpercentile(dc, 10)),
                   "median": float(np.nanmedian(dc)),
                   "p90": float(np.nanpercentile(dc, 90)),
                   "share_le_0": float(np.nanmean(dc <= 0))},
    }
    w, cc = out["delta_distribution"]["d_wallets"], out["delta_distribution"]["d_conc"]
    print(f"\n  Δэзэмшигч: p10 {w['p10']:+.1f} median {w['median']:+.1f} "
          f"p90 {w['p90']:+.1f}, >=0 байх хувь {100*w['share_ge_0']:.2f}%")
    print(f"  Δтөвлөрөл: p10 {cc['p10']:+.4f} median {cc['median']:+.4f} "
          f"p90 {cc['p90']:+.4f}, <=0 байх хувь {100*cc['share_le_0']:.2f}%")

    p = Path("results/proven_token_burst.json")
    p.write_text(json.dumps(out, indent=2, default=float))
    print(f"\n-> {p}")


if __name__ == "__main__":
    main()
