"""Stage 0's three checks: tail sensitivity, arithmetic consistency, bootstrap validity.

  python -m src.stage0_checks

Local only.  Best set from stage 0: q=5, latency=L3, L=0.05, k=1, pf=0, A=12,
which trades 3,921 of the 126,089 non-mayhem rows.

Nothing here decides whether a number is real.  Each check prints ДАВСАН/УНАСАН
against the criterion it was given and reports the numbers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.bootstrap_validation import _restricted_multiplicities  # noqa: E402
from src.exploratory_search import load_clusters  # noqa: E402
from src.fwd_net_ret import (  # noqa: E402
    A_LIMIT, FIRST_AGE, K_CONSEC, L_STOP, LATENCY, PF, Q_SIZES, K, FEE,
    combine, flow_exit, load, net_pnl_vec, stop_exit,
)

SEED = 20260819
BEST = {"q": 5.0, "latency": "L3", "L": 0.05, "k": 1, "pf": 0.0, "A": 12}
TRIMS = (0.01, 0.02, 0.05, 0.10)
PRIOR = 17_401


def build(c, q, lat, kc, A, L, pf):
    a_exit, _ = combine(flow_exit(c.traj, kc),
                        np.full(c.n, max(A, FIRST_AGE), dtype=np.int64),
                        stop_exit(c, q, lat, L, "true"))
    traded = a_exit > lat
    V = c.cumf[:, lat]
    W = c.cumf[np.arange(c.n), a_exit] - V + (c.xend - c.depth)
    y = net_pnl_vec(c.depth, q, V, W, pf)
    return y, a_exit, traded, V, W


def trimmed_expectancy(y: np.ndarray, frac: float, side: str) -> float:
    """Expectancy after dropping `frac` of the rows from one end."""
    n = len(y)
    k = int(round(n * frac))
    if k == 0 or n - k <= 0:
        return float(y.mean())
    s = np.sort(y)
    return float(s[:n - k].mean() if side == "top" else s[k:].mean())


# ----------------------------------------------------------------- check 3

def _weights(rng, cols, o):
    w = np.ones(len(o))
    for col in cols:
        uniq, inv = np.unique(col[o], return_inverse=True)
        w = w * _restricted_multiplicities(rng, int(col.max()) + 1,
                                           int(col.max()) + 1, len(uniq))[inv]
    return w


def coverage(y, tok, mn, scheme: str, stat: str, n_sim=200, n_boot=400,
             seed=SEED) -> dict:
    """Null coverage: random 10%/90% split, no planted effect, so the truth is 0."""
    rng = np.random.default_rng(seed)
    n = len(y)
    cols = () if scheme == "iid" else (tok, mn)
    covered = 0
    widths = []
    for _ in range(n_sim):
        u = rng.random(n)
        i1, i10 = np.where(u < 0.10)[0], np.where(u >= 0.90)[0]
        o1 = i1[np.argsort(y[i1], kind="stable")]
        o10 = i10[np.argsort(y[i10], kind="stable")]
        y1, y10 = y[o1], y[o10]
        draws = np.empty(n_boot)
        for b in range(n_boot):
            if scheme == "iid":
                m1 = rng.multinomial(len(o1), np.full(len(o1), 1 / len(o1)))
                m10 = rng.multinomial(len(o10), np.full(len(o10), 1 / len(o10)))
            else:
                m1, m10 = _weights(rng, cols, o1), _weights(rng, cols, o10)
            if m1.sum() <= 0 or m10.sum() <= 0:
                draws[b] = np.nan
                continue
            if stat == "mean":
                draws[b] = (m10 @ y10) / m10.sum() - (m1 @ y1) / m1.sum()
            else:
                a = y1[np.searchsorted(np.cumsum(m1), m1.sum() / 2, side="left")]
                bq = y10[np.searchsorted(np.cumsum(m10), m10.sum() / 2, side="left")]
                draws[b] = bq - a
        lo, hi = np.nanpercentile(draws, [2.5, 97.5])
        covered += int(lo <= 0 <= hi)
        widths.append(hi - lo)
    return {"scheme": scheme, "stat": stat, "n_sim": n_sim, "n_boot": n_boot,
            "coverage": covered / n_sim, "median_width": float(np.median(widths))}


def main() -> None:
    c = load()
    d, feats = load_clusters()
    lat = LATENCY[BEST["latency"]]
    q = BEST["q"]
    y, a_exit, traded, V, W = build(c, q, lat, BEST["k"], BEST["A"],
                                    BEST["L"], BEST["pf"])
    yt = y[traded]
    print(f"хамгийн сайн багц: арилжсан {traded.sum():,} / {c.n:,}  "
          f"expectancy {yt.mean():+.6f}  median {np.median(yt):+.6f}")

    # ------------------------------------------------------------- check 1
    curve = []
    for frac in TRIMS:
        for side in ("top", "bottom"):
            e = trimmed_expectancy(yt, frac, side)
            curve.append({"frac": frac, "side": side, "expectancy": e,
                          "per_sol": e / q})
            print(f"  {side:6} {100*frac:>5.1f}% хассан: expectancy {e:+.6f}  "
                  f"per SOL {e/q:+.6f}")
    flip = next((r["frac"] for r in curve
                 if r["side"] == "top" and r["expectancy"] < 0), None)
    if flip is None:
        fine = []
        for frac in np.arange(0.001, 0.201, 0.001):
            e = trimmed_expectancy(yt, float(frac), "top")
            fine.append((float(frac), e))
            if e < 0:
                flip = float(frac)
                break
    print(f"  тэмдэг эргэх дээд-хасалтын хувь: "
          f"{'олдсонгүй (20% хүртэл)' if flip is None else f'{100*flip:.1f}%'}")

    # all 2,016 sets
    all_sets = []
    for lat_name, latN in LATENCY.items():
        for qq in Q_SIZES:
            for kc in K_CONSEC:
                for A in A_LIMIT:
                    for L in L_STOP:
                        yy, ae, tr, _, _ = build(c, qq, latN, kc, A, L, 0.0)
                        if not tr.any():
                            continue
                        base = yy[tr]
                        for pf in PF:
                            z = base - 2 * pf
                            rec = {"latency": lat_name, "q": qq, "k": kc, "A": A,
                                   "L": L, "pf": pf, "n": int(tr.sum()),
                                   "expectancy": float(z.mean())}
                            for frac in TRIMS:
                                rec[f"top{int(frac*100)}"] = trimmed_expectancy(z, frac, "top")
                            rec["bottom1"] = trimmed_expectancy(z, 0.01, "bottom")
                            rec["bottom5"] = trimmed_expectancy(z, 0.05, "bottom")
                            all_sets.append(rec)
    arr = {k2: np.array([s[k2] for s in all_sets])
           for k2 in ("expectancy", "top1", "top2", "top5", "top10",
                      "bottom1", "bottom5")}
    print(f"\n2,016 багц: expectancy median {np.median(arr['expectancy']):+.6f}")
    for k2 in ("top1", "top2", "top5", "top10", "bottom1", "bottom5"):
        v = arr[k2]
        print(f"  {k2:8} median {np.median(v):+.6f}  сөрөг болсон багц "
              f"{int((v < 0).sum()):,} / {len(v):,}")

    # top 10 bursts on the best set
    idx = np.where(traded)[0]
    order = idx[np.argsort(y[idx])[::-1][:10]]
    top10 = [{"pnl": float(y[i]), "depth_x": float(c.depth[i]),
              "net_flow_5slot": float(c.cumf[i, 5] - c.cumf[i, 0]),
              "a_exit": int(a_exit[i]), "W": float(W[i]),
              "x_end_slot": float(c.xend[i])} for i in order]
    print("\nдээд 10 burst:")
    for t in top10:
        print(f"  P&L {t['pnl']:+12.4f}  depth_x {t['depth_x']:9.4f}  "
              f"nf5 {t['net_flow_5slot']:+9.4f}  a_exit {t['a_exit']:3d}  "
              f"W {t['W']:+12.4f}")

    # ------------------------------------------------------------- check 2
    x_eff = c.depth[traded] + V[traded]
    x_entry = x_eff + q
    x_exit = x_entry + W[traded]
    p_entry = x_eff * (x_eff + q) / K
    p_exit = x_exit * x_exit / K
    ratio = p_exit / p_entry
    slip = q / x_entry
    hold = a_exit[traded] - lat
    recon = c.xend[traded] + c.cumf[traded, :][np.arange(traded.sum()), a_exit[traded]] + q
    ident = np.abs(x_exit - recon) / np.maximum(np.abs(x_exit), 1.0)
    print(f"\n2. нийцэл: |x_exit − (x_end_slot + cumf[a_exit] + q)| max харьц. "
          f"{ident.max():.3e}  (>1e-12: {int((ident > 1e-12).sum())})")
    qq_tab = []
    for qv in Q_SIZES:
        yv, _, trv, _, _ = build(c, qv, lat, BEST["k"], BEST["A"], BEST["L"], BEST["pf"])
        e = float(yv[trv].mean())
        qq_tab.append({"q": qv, "n": int(trv.sum()), "expectancy": e,
                       "per_sol": e / qv})
        print(f"   q={qv}: n {trv.sum():,}  expectancy {e:+.6f}  per SOL {e/qv:+.6f}")
    per = [r["per_sol"] for r in qq_tab]
    q_decreasing = all(np.diff(per) < 0)
    print(f"   per SOL монотон буурах уу: {q_decreasing}")

    # ------------------------------------------------------------- check 3
    print("\n3. bootstrap-ийн валидаци (null хамрах чадвар, expectancy vs median)")
    cov = []
    for scheme in ("iid", "token_minute"):
        for stat in ("mean", "median"):
            r = coverage(yt, d.tok[traded], d.mn[traded], scheme, stat)
            cov.append(r)
            print(f"   {scheme:13} {stat:6} coverage {100*r['coverage']:.1f}%  "
                  f"median width {r['median_width']:.6f}")

    tm_mean = next(r for r in cov if r["scheme"] == "token_minute"
                   and r["stat"] == "mean")
    check1 = "ДАВСАН" if (flip is None or flip >= 0.05) else "УНАСАН"
    check2 = "ДАВСАН" if (ident.max() < 1e-12 and q_decreasing) else "УНАСАН"
    check3 = "ДАВСАН" if tm_mean["coverage"] >= 0.90 else "УНАСАН"
    n_tests = len(all_sets) + len(curve) + len(qq_tab) + len(cov)
    print(f"\n1: {check1}   2: {check2}   3: {check3}")
    print(f"тестийн тоо {n_tests:,}, хуримтлагдсан {PRIOR + n_tests:,}")

    out = {"best": BEST, "n_traded": int(traded.sum()),
           "expectancy": float(yt.mean()), "median": float(np.median(yt)),
           "check1": {"curve": curve, "flip_frac": flip, "top10": top10,
                      "all_sets": {k2: {"median": float(np.median(v)),
                                        "n_negative": int((v < 0).sum()),
                                        "n": len(v)} for k2, v in arr.items()},
                      "verdict": check1},
           "check2": {"W": {q2: float(np.percentile(W[traded], p2))
                            for q2, p2 in (("p10", 10), ("p25", 25), ("p50", 50),
                                           ("p75", 75), ("p90", 90))},
                      "W_share_positive": float((W[traded] > 0).mean()),
                      "price_ratio": {q2: float(np.percentile(ratio, p2))
                                      for q2, p2 in (("p10", 10), ("p25", 25),
                                                     ("p50", 50), ("p75", 75),
                                                     ("p90", 90))},
                      "slippage": {"median": float(np.median(slip)),
                                   "max": float(slip.max())},
                      "hold_slots": {"median": float(np.median(hold)),
                                     "p90": float(np.percentile(hold, 90)),
                                     "max": int(hold.max())},
                      "identity_max_rel": float(ident.max()),
                      "identity_violations": int((ident > 1e-12).sum()),
                      "q_table": qq_tab, "q_per_sol_decreasing": bool(q_decreasing),
                      "verdict": check2},
           "check3": {"coverage": cov, "verdict": check3},
           "counts": {"this_step": n_tests, "prior": PRIOR,
                      "cumulative": PRIOR + n_tests}}
    p = config.RESULTS / "stage0_checks.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"-> {p}")


if __name__ == "__main__":
    main()
