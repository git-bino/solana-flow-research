"""Audit 2 blockers 1 and 2 — decompose the causal fix and stress the result.

  python -m src.audit2_fix

Three pricings of the same 5,402 rows, so the two defects can be separated:

    OLD     entry on depth_x + cum[L],     exit fill at a_exit + Lx
    FIX1    entry on x_end_slot + cum[L],  exit fill at a_exit + Lx
    CAUSAL  entry on x_end_slot + cum[L],  exit fill at a_exit + 1 + Lx

OLD is `frozen_rule.py` as audited; CAUSAL is `src/causal_rule.py`.

Clustering is token x LAUNCH-DAY, not token x minute: 98.98% of trades fall on
ten launch dates, and a minute cluster cannot absorb a shock that is common to a
whole launch day.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.bootstrap_validation import _restricted_multiplicities  # noqa: E402
from src.causal_rule import TRAJ, exit_age, net_pnl, slot_flows  # noqa: E402

SEED = 20260819
B = 2_000
MIGRATION_X = Decimal(115)      # curve_progress = (x - 30) / 85 = 1
LX_GRID = (0, 1, 3, 8)
Q_GRID = (Decimal("0.5"), Decimal(1), Decimal(2), Decimal(5))
L_GRID = (1, 3, 8)
PF_GRID = (Decimal(0), Decimal("0.001"), Decimal("0.01"))


def load():
    from src.load_clickhouse_v2 import client
    return client().query(
        "SELECT nf3_traj_75_incl_pre, nf3_excl_pre_1, nf3_excl_pre_2, "
        "       x_end_slot, depth_x, token_mint, "
        "       parseDateTimeBestEffort(token_created_at, 'UTC') AS ct "
        "FROM flow.burst_v2 WHERE NOT mayhem"
    ).result_columns


def cumulative(nf3, e1, e2):
    f = slot_flows(nf3, e1, e2)
    cum = [Decimal(0)] * (TRAJ + 1)
    acc = Decimal(0)
    for a in range(1, TRAJ + 1):
        acc += Decimal(str(f[a]))
        cum[a] = acc
    return cum


def price_three(nf3, e1, e2, x_end, depth, L=8, q=Decimal(5), Lx=0,
                pf=Decimal(0), adverse=False):
    """(old, fix1, causal, meta) for one burst, or None when it does not trade."""
    a_rule, censored = exit_age(nf3)
    if a_rule <= L:
        return None
    cum = cumulative(nf3, e1, e2)
    xe, dx = Decimal(str(x_end)), Decimal(str(depth))
    gap = xe - dx

    a_old = min(a_rule + Lx, TRAJ)
    a_new = min(a_rule + 1 + Lx, TRAJ)

    old = net_pnl(dx, q, cum[L], cum[a_old] - cum[L] + gap, pf)
    fix1 = net_pnl(xe + cum[L], q, Decimal(0), cum[a_old] - cum[L], pf)
    base = xe + cum[min(L + 1, TRAJ)] if adverse else xe + cum[L]
    causal = net_pnl(base, q, Decimal(0), cum[a_new] - cum[L], pf)

    x_at = [xe + cum[a] for a in range(min(L + 1, TRAJ), a_new + 1)]
    migrated = any(v >= MIGRATION_X for v in x_at)
    return old, fix1, causal, {"gap": gap, "a_rule": a_rule, "a_fill": a_new,
                               "censored": censored, "migrated": migrated}


def cluster_ci(tok, day, y, n_boot=B, seed=SEED) -> dict:
    """Two-way cluster percentile CI for a mean: token x launch-day."""
    n_cells, n_needed, compact = [], [], []
    for col in (tok, day):
        uniq, inv = np.unique(col, return_inverse=True)
        n_cells.append(len(uniq))
        n_needed.append(len(uniq))
        compact.append(inv)
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for b in range(n_boot):
        w = np.ones(len(y))
        for nc, nn, inv in zip(n_cells, n_needed, compact):
            w = w * _restricted_multiplicities(rng, nc, nc, nn)[inv]
        t = w.sum()
        draws[b] = (w @ y) / t if t > 0 else np.nan
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return {"point": float(y.mean()), "lo": float(lo), "hi": float(hi),
            "excludes_zero": bool(lo > 0 or hi < 0), "n": int(len(y))}


def main() -> None:
    traj, e1, e2, xend, depth, mint, ct = load()
    rows, old, fix1, causal, gaps, migs, toks, days = [], [], [], [], [], [], [], []
    for i in range(len(traj)):
        r = price_three(list(traj[i]), e1[i], e2[i], xend[i], depth[i])
        if r is None:
            continue
        o, f1, c, m = r
        rows.append(i)
        old.append(float(o)); fix1.append(float(f1)); causal.append(float(c))
        gaps.append(float(m["gap"])); migs.append(m["migrated"])
        toks.append(mint[i]); days.append(ct[i].date().isoformat())
    old = np.array(old); fix1 = np.array(fix1); causal = np.array(causal)
    gaps = np.array(gaps); migs = np.array(migs)
    _, tok_id = np.unique(np.array(toks), return_inverse=True)
    day_u, day_id = np.unique(np.array(days), return_inverse=True)
    n = len(old)
    print(f"n_traded {n:,}  (хаалга a_exit > 8 — өөрчлөгдөөгүй)")

    print(f"\n2. ЗАДАРГАА")
    print(f"  OLD     expectancy {old.mean():+.6f}  median {np.median(old):+.6f}  "
          f">0 {100*(old>0).mean():.2f}%")
    print(f"  FIX1    expectancy {fix1.mean():+.6f}  median {np.median(fix1):+.6f}  "
          f">0 {100*(fix1>0).mean():.2f}%")
    print(f"  CAUSAL  expectancy {causal.mean():+.6f}  median {np.median(causal):+.6f}  "
          f">0 {100*(causal>0).mean():.2f}%")
    d1 = old - fix1
    d2 = fix1 - causal
    tot = old.sum()
    print(f"  зөрүү 1 (entry reserve): нийлбэр {d1.sum():+.2f} = хуучин нийтийн "
          f"{100*d1.sum()/tot:.2f}%;  median {np.median(d1):+.6f}  "
          f"p10 {np.percentile(d1,10):+.6f}  p90 {np.percentile(d1,90):+.6f}  "
          f">0 {100*(d1>0).mean():.2f}%")
    print(f"  зөрүү 2 (нэг slot lookahead): нийлбэр {d2.sum():+.2f} = "
          f"{100*d2.sum()/tot:.2f}%;  median {np.median(d2):+.6f}  "
          f">0 {100*(d2>0).mean():.2f}%")
    z = gaps == 0
    print(f"\n  gap == 0 дэд олонлог: n {int(z.sum()):,} ({100*z.mean():.2f}%)  "
          f"OLD {old[z].mean():+.6f}  CAUSAL {causal[z].mean():+.6f}")

    out = {"n_traded": n,
           "variants": {k: {"expectancy": float(v.mean()),
                            "median": float(np.median(v)),
                            "share_positive": float((v > 0).mean()),
                            "total": float(v.sum())}
                        for k, v in (("old", old), ("fix1", fix1), ("causal", causal))},
           "decomposition": {
               "entry_reserve_sum": float(d1.sum()),
               "entry_reserve_share_of_old_total": float(d1.sum() / tot),
               "entry_reserve_median": float(np.median(d1)),
               "entry_reserve_p10": float(np.percentile(d1, 10)),
               "entry_reserve_p90": float(np.percentile(d1, 90)),
               "entry_reserve_share_positive": float((d1 > 0).mean()),
               "lookahead_sum": float(d2.sum()),
               "lookahead_share_of_old_total": float(d2.sum() / tot),
               "lookahead_median": float(np.median(d2)),
               "lookahead_share_positive": float((d2 > 0).mean())},
           "gap_zero": {"n": int(z.sum()), "share": float(z.mean()),
                        "old": float(old[z].mean()),
                        "causal": float(causal[z].mean())},
           "migration": {"n": int(migs.sum()), "share": float(migs.mean()),
                         "causal_expectancy_migrated":
                             float(causal[migs].mean()) if migs.any() else None,
                         "causal_expectancy_not_migrated":
                             float(causal[~migs].mean())}}

    print(f"\n3. STRESS CELLS (кластер: token × launch-day)")
    cells = []
    base_ci = cluster_ci(tok_id, day_id, causal)
    cells.append({"cell": "causal, үндсэн"} | base_ci)
    print(f"  {'үндсэн':28} n {base_ci['n']:>5,}  exp {base_ci['point']:+.6f}  "
          f"CI [{base_ci['lo']:+.6f}, {base_ci['hi']:+.6f}]")
    gz = cluster_ci(tok_id[z], day_id[z], causal[z])
    cells.append({"cell": "gap == 0"} | gz)
    print(f"  {'gap == 0':28} n {gz['n']:>5,}  exp {gz['point']:+.6f}  "
          f"CI [{gz['lo']:+.6f}, {gz['hi']:+.6f}]")
    adv = np.array([float(price_three(list(traj[i]), e1[i], e2[i], xend[i],
                                      depth[i], adverse=True)[2])
                    for i in rows])
    ac = cluster_ci(tok_id, day_id, adv)
    cells.append({"cell": "adverse fill (cum[L+1])"} | ac)
    print(f"  {'adverse fill (cum[L+1])':28} n {ac['n']:>5,}  exp {ac['point']:+.6f}  "
          f"CI [{ac['lo']:+.6f}, {ac['hi']:+.6f}]")

    def sweep(name, grid, kw):
        for v in grid:
            y = np.array([float(price_three(list(traj[i]), e1[i], e2[i], xend[i],
                                            depth[i], **{kw: v})[2])
                          for i in rows if price_three(list(traj[i]), e1[i], e2[i],
                                                       xend[i], depth[i],
                                                       **{kw: v}) is not None])
            ci = cluster_ci(tok_id[:len(y)], day_id[:len(y)], y)
            per = ci["point"] / float(v) if kw == "q" else None
            cells.append({"cell": f"{name}={v}", "per_sol": per} | ci)
            print(f"  {name+'='+str(v):28} n {ci['n']:>5,}  exp {ci['point']:+.6f}  "
                  f"CI [{ci['lo']:+.6f}, {ci['hi']:+.6f}]"
                  + (f"  /SOL {per:+.6f}" if per is not None else ""))

    sweep("pf", PF_GRID, "pf")
    sweep("Lx", LX_GRID, "Lx")
    sweep("q", Q_GRID, "q")

    # entry latency on a MATCHED sample: rows that trade at L = 8
    print("  L (тохирсон дээж, L=8-д арилжсан мөр дээр):")
    lm = []
    for Lin in L_GRID:
        y = np.array([float(price_three(list(traj[i]), e1[i], e2[i], xend[i],
                                        depth[i], L=Lin)[2])
                      if price_three(list(traj[i]), e1[i], e2[i], xend[i],
                                     depth[i], L=Lin) else np.nan
                      for i in rows])
        ok = ~np.isnan(y)
        ci = cluster_ci(tok_id[ok], day_id[ok], y[ok])
        lm.append({"L": Lin, "n_matched": int(ok.sum())} | ci)
        print(f"    L={Lin}: n {int(ok.sum()):>5,}  exp {ci['point']:+.6f}  "
              f"CI [{ci['lo']:+.6f}, {ci['hi']:+.6f}]")

    # leave-one-launch-day-out
    print("  leave-one-launch-day-out:")
    loo = []
    for k, dd in enumerate(day_u):
        m = day_id != k
        e = float(causal[m].mean())
        loo.append({"day": str(dd), "n_dropped": int((~m).sum()),
                    "expectancy_without": e,
                    "delta": e - float(causal.mean())})
        print(f"    -{dd}: n_хассан {int((~m).sum()):>5,}  exp {e:+.6f}  "
              f"Δ {e-float(causal.mean()):+.6f}")

    out |= {"stress_cells": cells, "L_matched": lm, "leave_one_day_out": loo,
            "cluster": "token x launch-day"}
    p = config.RESULTS / "audit2_fix.json"
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n-> {p}")


if __name__ == "__main__":
    main()
