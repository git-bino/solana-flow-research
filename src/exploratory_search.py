"""Exploratory search on chunk 1 — parameter structure and entry filters.

  python -m src.exploratory_search

Chunk 1 is the search sample and is spent: everything evaluated here is counted
in test_log_atomic.md and feeds the next stage's multiplicity correction.

Corrections applied first (research lead, 2026-08-19): q grid {0.5, 1, 2, 5};
`x_end_slot` is the primary reserve base with `depth_x` kept as robustness; the
age rule exits at `a >= A`, not `a > A`.

Nothing here decides whether a result is promising.  It reports numbers.
"""

from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.bootstrap_validation import Data, Estimator  # noqa: E402
from src.fwd_net_ret import (  # noqa: E402
    A_LIMIT, FIRST_AGE, K_CONSEC, L_STOP, LATENCY, PF, Q_SIZES, TRAJ,
    combine, flow_exit, load, net_pnl_vec, stop_exit,
)

SEED = 20260819
B = 1_000
BREAKEVEN = 0.657231
PRIMARY_BASE = "true"

FEATURES = [
    "net_flow_5slot", "depth_x", "oh_ratio_a", "n_buyers_12slot",
    "size_cv_25slot", "round_frac_25slot", "accel", "curve_progress",
    "burst_age_slot", "oh_conc_a",
]


def compute_y(c, base, lat, q, kc, A, L, pf, flow_ex=None):
    """`fwd_net_ret` per row for one parameter set, plus the exit age."""
    fe = flow_ex if flow_ex is not None else flow_exit(c.traj, kc)
    age_ex = np.full(c.n, max(A, FIRST_AGE), dtype=np.int64)
    st = stop_exit(c, q, lat, L, base)
    a_exit, censored = combine(fe, age_ex, st)
    V = c.cumf[:, lat]
    W = c.cumf[np.arange(c.n), a_exit] - V
    if base == "true":
        W = W + (c.xend - c.depth)
    return net_pnl_vec(c.depth, q, V, W, pf), a_exit, censored


def load_clusters() -> tuple[Data, dict]:
    """Cluster ids and the feature columns, from the same non-mayhem cell."""
    from src.load_clickhouse_v2 import client
    cols = client().query(
        "SELECT token_mint, toUnixTimestamp(toStartOfMinute("
        "         parseDateTimeBestEffort(block_time, 'UTC'))) AS minute_utc, "
        "       trigger_wallet, " + ", ".join(FEATURES) +
        " FROM flow.burst_v2 WHERE NOT mayhem"
    ).result_columns
    _, tok = np.unique(np.asarray(cols[0]), return_inverse=True)
    minute = np.asarray(cols[1], dtype=np.int64)
    _, mn = np.unique(minute, return_inverse=True)
    _, wal = np.unique(np.asarray(cols[2]), return_inverse=True)
    _, blk5 = np.unique(minute // 300, return_inverse=True)
    feats = {}
    for i, name in enumerate(FEATURES):
        v = np.asarray([np.nan if x is None else x for x in cols[3 + i]],
                       dtype=np.float64)
        feats[name] = v
    return Data(np.zeros(len(tok)), tok, mn, wal, blk5, len(tok)), feats


def equal_groups(v: np.ndarray, k: int) -> np.ndarray:
    """Equal-sized rank groups, 0 = lowest.  NaN rows go to group -1."""
    out = np.full(len(v), -1, dtype=np.int64)
    ok = np.where(np.isfinite(v))[0]
    order = ok[np.argsort(v[ok], kind="stable")]
    edges = np.linspace(0, len(order), k + 1).round().astype(int)
    for g in range(k):
        out[order[edges[g]:edges[g + 1]]] = g
    return out


def level_ci(d: Data, y: np.ndarray, idx: np.ndarray, n_boot: int = B) -> dict:
    """Two-way cluster CI for the LEVEL of a median, not a difference.

    `Estimator` compares two groups; a level needs the same restricted-multinomial
    weights applied to one.  `_restricted_multiplicities` is reused unchanged so
    the resampling law is the validated one.
    """
    from src.bootstrap_validation import _restricted_multiplicities
    o = idx[np.argsort(y[idx], kind="stable")]
    ys = y[o]
    n_cells, n_needed, compact = [], [], []
    for col in (d.tok, d.mn):
        uniq, inv = np.unique(col[o], return_inverse=True)
        n_cells.append(int(col.max()) + 1)
        n_needed.append(len(uniq))
        compact.append(inv)
    rng = np.random.default_rng(SEED)
    draws = np.empty(n_boot)
    for b in range(n_boot):
        w = np.ones(len(o))
        for nc, nn, inv in zip(n_cells, n_needed, compact):
            w = w * _restricted_multiplicities(rng, nc, nc, nn)[inv]
        tot = w.sum()
        draws[b] = (ys[np.searchsorted(np.cumsum(w), tot / 2.0, side="left")]
                    if tot > 0 else np.nan)
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return {"point": float(np.median(y[idx])), "lo": float(lo), "hi": float(hi),
            "contains_zero": bool(lo <= 0 <= hi)}


def ci_for(d: Data, y: np.ndarray, idx1: np.ndarray, idx10: np.ndarray,
           n_boot: int = B) -> dict:
    d2 = Data(y, d.tok, d.mn, d.wal, d.blk5, d.n_rows)
    est = Estimator(d2, (d.tok, d.mn), idx1, idx10)
    lo, hi, _ = est.ci(np.random.default_rng(SEED), n_boot)
    return {"point": est.point, "lo": lo, "hi": hi, "excludes_zero": lo > 0 or hi < 0}


# ------------------------------------------------------------------ section 1

def marginals(rows: list[dict]) -> dict:
    keys = ("k", "A", "L", "q", "latency", "pf")
    out = {}
    for key in keys:
        vals = sorted({r[key] for r in rows},
                      key=lambda v: (v is None, v if v is not None else 0)
                      if key != "latency" else LATENCY[v])
        table = []
        for v in vals:
            sub = [r["median"] for r in rows if r[key] == v]
            pos = [r["share_positive"] for r in rows if r[key] == v]
            ae = [r["a_exit_mean"] for r in rows if r[key] == v]
            table.append({"value": v, "n_sets": len(sub),
                          "mean_of_medians": float(np.mean(sub)),
                          "median_of_medians": float(np.median(sub)),
                          "min": float(np.min(sub)), "max": float(np.max(sub)),
                          "mean_share_positive": float(np.mean(pos)),
                          "mean_a_exit": float(np.mean(ae))})
        seq = [t["mean_of_medians"] for t in table]
        diffs = np.diff(seq)
        out[key] = {"table": table,
                    "monotone_increasing": bool(np.all(diffs > 0)),
                    "monotone_decreasing": bool(np.all(diffs < 0)),
                    "n_sign_changes": int(np.sum(np.diff(np.sign(diffs)) != 0))
                                      if len(diffs) > 1 else 0,
                    "spread": float(max(seq) - min(seq))}
    return out


def concentration(rows: list[dict], n: int = 20) -> dict:
    srt = sorted(rows, key=lambda r: r["median"])
    bot, top = srt[:n], srt[-n:]
    out = {}
    for name, grp in (("top", top), ("bottom", bot)):
        out[name] = {k: {str(v): sum(1 for r in grp if r[k] == v)
                         for v in sorted({r[k] for r in rows},
                                         key=lambda x: (x is None, str(x)))}
                     for k in ("k", "A", "L", "q", "latency", "pf")}
        out[name]["median_range"] = [grp[0]["median"], grp[-1]["median"]]
    return out


def main() -> None:
    base = json.load(open(config.RESULTS / "fwd_net_ret_baseline.json"))
    rows = [r for r in base["rows"] if r["base"] == PRIMARY_BASE]
    print(f"үндсэн конвенц `{PRIMARY_BASE}`: {len(rows):,} багц")

    marg = marginals(rows)
    for key, m in marg.items():
        print(f"\n{key}: spread {m['spread']:.6f}  monotone↑ {m['monotone_increasing']}"
              f"  monotone↓ {m['monotone_decreasing']}  sign changes {m['n_sign_changes']}")
        for t in m["table"]:
            print(f"    {str(t['value']):>8}  mean {t['mean_of_medians']:+.6f}  "
                  f"median {t['median_of_medians']:+.6f}  "
                  f"[{t['min']:+.6f}, {t['max']:+.6f}]  "
                  f">0 {100*t['mean_share_positive']:.2f}%  a_exit {t['mean_a_exit']:.2f}")

    conc = concentration(rows)
    print(f"\nдээд 20 median муж {conc['top']['median_range']}, "
          f"доод 20 {conc['bottom']['median_range']}")

    # --- the chosen set: best MEAN marginal for each parameter, not the max set
    chosen = {}
    for key in ("k", "A", "L", "q", "latency", "pf"):
        t = max(marg[key]["table"], key=lambda x: x["mean_of_medians"])
        chosen[key] = t["value"]
    print(f"\nсонгосон багц (маргиналын дундажаар хамгийн сайн): {chosen}")

    c = load()
    d, feats = load_clusters()
    y, a_exit, censored = compute_y(
        c, PRIMARY_BASE, LATENCY[chosen["latency"]], chosen["q"],
        chosen["k"], chosen["A"], chosen["L"], chosen["pf"])
    print(f"сонгосон багцын y: median {np.median(y):+.6f}  "
          f">0 {100*(y>0).mean():.2f}%  a_exit дундаж {a_exit.mean():.3f}")

    # top set CI
    top_set = max(rows, key=lambda r: r["median"])
    y_top, _, _ = compute_y(c, PRIMARY_BASE, LATENCY[top_set["latency"]],
                            top_set["q"], top_set["k"], top_set["A"],
                            top_set["L"], top_set["pf"])
    lev = level_ci(d, y_top, np.arange(d.n_rows))
    top_ci = {"set": {k: top_set[k] for k in ("k", "A", "L", "q", "latency", "pf")},
              "median": top_set["median"], "level_ci": lev}
    print(f"дээд багц {top_ci['set']} median {top_set['median']:+.6f}  "
          f"95% CI [{lev['lo']:+.6f}, {lev['hi']:+.6f}]  0∈CI {lev['contains_zero']}")

    # --- section 2: feature deciles
    feat_out = []
    for name in FEATURES:
        v = feats[name]
        grp = equal_groups(v, 10)
        rows_f = []
        for gi in range(10):
            m = grp == gi
            rows_f.append({"decile": gi + 1, "n": int(m.sum()),
                           "median": float(np.median(y[m])),
                           "share_positive": float((y[m] > 0).mean()),
                           "feat_min": float(v[m].min()), "feat_max": float(v[m].max())})
        idx1 = np.where(grp == 0)[0]
        idx10 = np.where(grp == 9)[0]
        ci = ci_for(d, y, idx1, idx10)
        feat_out.append({"feature": name, "n_nan": int((~np.isfinite(v)).sum()),
                         "deciles": rows_f, "ci": ci,
                         "d10_median": rows_f[9]["median"],
                         "d10_beats_breakeven": rows_f[9]["median"] > BREAKEVEN})
        print(f"{name:20} d1 {rows_f[0]['median']:+.6f}  d10 {rows_f[9]['median']:+.6f}  "
              f"Δ {ci['point']:+.6f}  CI [{ci['lo']:+.6f}, {ci['hi']:+.6f}]  "
              f"0∉CI {ci['excludes_zero']}  d10>BE {rows_f[9]['median'] > BREAKEVEN}")

    # --- section 3: combination of the three strongest by |Δ|
    top3 = sorted(feat_out, key=lambda f: abs(f["ci"]["point"]), reverse=True)[:3]
    names = [f["feature"] for f in top3]

    def combo_for(side: str) -> dict:
        """`top` is the brief's literal rule; `favourable` follows the sign of Δ."""
        masks = []
        for f in top3:
            ter = equal_groups(feats[f["feature"]], 3)
            g = 2 if side == "top" else (2 if f["ci"]["point"] > 0 else 0)
            masks.append(ter == g)
        both = masks[0] & masks[1] & masks[2]
        out = {"side": side, "features": names,
               "tercile_used": ["T3" if side == "top" else
                                ("T3" if f["ci"]["point"] > 0 else "T1")
                                for f in top3],
               "n": int(both.sum())}
        if both.sum() < 1000:
            out["stopped"] = "n < 1,000 — хэт нарийн зүсэлт, ЗОГСОВ"
            return out
        yy = y[both]
        out |= {"median": float(np.median(yy)),
                "share_positive": float((yy > 0).mean()),
                "level_ci": level_ci(d, y, np.where(both)[0]),
                "ci_vs_rest": ci_for(d, y, np.where(~both)[0], np.where(both)[0]),
                "beats_breakeven": float(np.median(yy)) > BREAKEVEN}
        return out

    combo = {s: combo_for(s) for s in ("top", "favourable")}
    for s, cb in combo.items():
        print(f"\nхослол [{s}] {names} {cb['tercile_used']}: n {cb['n']:,}")
        if "median" in cb:
            print(f"  median {cb['median']:+.6f}  >0 {100*cb['share_positive']:.2f}%  "
                  f"level CI [{cb['level_ci']['lo']:+.6f}, {cb['level_ci']['hi']:+.6f}]  "
                  f">BE {cb['beats_breakeven']}")
        else:
            print(f"  {cb['stopped']}")

    n_tests = len(rows) + len(FEATURES) + len(combo)
    out = {"n_rows": c.n, "primary_base": PRIMARY_BASE,
           "n_param_sets": len(rows), "marginals": marg, "concentration": conc,
           "chosen_set": chosen,
           "chosen_summary": {"median": float(np.median(y)),
                              "share_positive": float((y > 0).mean()),
                              "a_exit_mean": float(a_exit.mean()),
                              "censored_share": float(censored.mean())},
           "top_set": top_ci, "features": feat_out, "combination": combo,
           "n_tests_this_step": n_tests, "breakeven": BREAKEVEN}
    p = config.RESULTS / "exploratory_search_01.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"\nтестийн тоо: {n_tests:,}\n-> {p}")


if __name__ == "__main__":
    main()
