"""`L_stop` and `k` curves, and the stability battery for the reduced rule.

  python -m src.param_reduction

Base: q=5, entry latency L=8 (L3), k=1, pf=0, Lx=0, A=75 (the age limit was
dropped as immaterial, decisions.md 2026-08-19).

Flatness criterion, stated rather than assumed: a parameter is called FLAT when
every one of its 95% CIs overlaps every other -- i.e. the largest lower bound
sits below the smallest upper bound.  The spread of the point estimates relative
to the median CI width is reported alongside as a magnitude.
ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (the criterion; the parameter choice is not
made here).

Section 3 does not pick `k`.  If `k` is flat its four values are equivalent
within noise, so the stability battery is run for all four and the choice is
left open.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.exit_latency import price  # noqa: E402
from src.exploratory_search import load_clusters  # noqa: E402
from src.fwd_net_ret import FIRST_AGE, flow_exit, load, stop_exit  # noqa: E402
from src.stage0_tail import expectancy_ci  # noqa: E402

SEED = 20260819
B = 2_000
LSTOP_GRID = (0.02, 0.05, 0.10, 0.20, 0.35, 0.50, None)
K_GRID = (1, 2, 3, 5)
LX_GRID = (0, 1, 3, 8)
Q_GRID = (0.5, 1.0, 2.0, 5.0)
L_GRID = (1, 3, 8)
TRIMS = (0.01, 0.05, 0.10)
BASE = {"q": 5.0, "lat": 8, "k": 1, "pf": 0.0, "A": 75, "L": 0.05}
PRIOR = 19_577


def evaluate(c, tok, mn, *, q=None, lat=None, kc=None, A=None, L="keep",
             lx=0, want_ci=True) -> dict:
    q = BASE["q"] if q is None else q
    lat = BASE["lat"] if lat is None else lat
    kc = BASE["k"] if kc is None else kc
    A = BASE["A"] if A is None else A
    L = BASE["L"] if L == "keep" else L
    y, tr, a_exit, _, _, _ = price(c, q, lat, kc, A, L, BASE["pf"], lx)
    yt = y[tr]
    hold = (a_exit - lat)[tr]
    fe = flow_exit(c.traj, kc)
    st = stop_exit(c, q, lat, L, "true")
    age = np.full(c.n, max(A, FIRST_AGE), dtype=np.int64)
    f = (fe == a_exit)[tr]
    s = ((st == a_exit) & (st > 0))[tr]
    a = (age == a_exit)[tr]
    out = {"q": q, "L_entry": lat, "k": kc, "A": A, "L_stop": L, "Lx": lx,
           "n": int(tr.sum()), "expectancy": float(yt.mean()),
           "expectancy_per_sol": float(yt.mean() / q),
           "median": float(np.median(yt)),
           "share_positive": float((yt > 0).mean()),
           "hold_mean": float(hold.mean()), "hold_median": float(np.median(hold)),
           "share_flow": float(f.mean()), "share_stop": float(s.mean()),
           "share_age": float(a.mean())}
    for name, m in (("flow_only", f & ~s & ~a), ("stop_any", s), ("age_any", a)):
        if m.any():
            v = yt[m]
            out[name] = {"n": int(m.sum()), "expectancy": float(v.mean()),
                         "median": float(np.median(v))}
        else:
            out[name] = {"n": 0}
    if want_ci:
        out["ci"] = expectancy_ci(tok[tr], mn[tr], yt, n_boot=B, seed=SEED)
        out["ci_per_sol"] = {"lo": out["ci"]["lo"] / q, "hi": out["ci"]["hi"] / q}
    return out, y, tr


def flatness(rows: list[dict]) -> dict:
    los = [r["ci"]["lo"] for r in rows]
    his = [r["ci"]["hi"] for r in rows]
    pts = np.array([r["expectancy"] for r in rows])
    widths = np.array([r["ci"]["hi"] - r["ci"]["lo"] for r in rows])
    overlap = max(los) < min(his)
    return {"all_ci_overlap": bool(overlap),
            "max_lower": float(max(los)), "min_upper": float(min(his)),
            "spread": float(pts.max() - pts.min()),
            "median_ci_width": float(np.median(widths)),
            "spread_over_ci_width": float((pts.max() - pts.min())
                                          / np.median(widths)),
            "flat": bool(overlap)}


def trimmed(y, frac, side="top"):
    n = len(y)
    k = int(round(n * frac))
    if k == 0:
        return float(y.mean())
    s = np.sort(y)
    return float(s[:n - k].mean() if side == "top" else s[k:].mean())


def main() -> None:
    c = load()
    d, _ = load_clusters()
    tok, mn = d.tok, d.mn

    # ------------------------------------------------------------------ 1
    print("1. L_stop-ийн муруй (A = 75)")
    lstop_rows = []
    for L in LSTOP_GRID:
        r, _, _ = evaluate(c, tok, mn, L=L)
        lstop_rows.append(r)
        print(f"  L_stop={'∞' if L is None else L:>5}  n {r['n']:>6,}  "
              f"exp {r['expectancy']:+.6f}  /SOL {r['expectancy_per_sol']:+.6f}  "
              f"median {r['median']:+.6f}  >0 {100*r['share_positive']:5.2f}%  "
              f"CI [{r['ci']['lo']:+.6f}, {r['ci']['hi']:+.6f}]  "
              f"flow {100*r['share_flow']:5.1f}%  stop {100*r['share_stop']:5.1f}%")
    fl_lstop = flatness(lstop_rows)
    print(f"  → CI бүгд давхцах уу: {fl_lstop['all_ci_overlap']}  "
          f"муж {fl_lstop['spread']:.6f} = CI өргөний "
          f"{100*fl_lstop['spread_over_ci_width']:.1f}%")

    # ------------------------------------------------------------------ 2
    print("\n2. k-ийн муруй")
    k_rows = []
    for kc in K_GRID:
        r, _, _ = evaluate(c, tok, mn, kc=kc)
        k_rows.append(r)
        print(f"  k={kc}  n {r['n']:>6,}  exp {r['expectancy']:+.6f}  "
              f"/SOL {r['expectancy_per_sol']:+.6f}  median {r['median']:+.6f}  "
              f">0 {100*r['share_positive']:5.2f}%  "
              f"CI [{r['ci']['lo']:+.6f}, {r['ci']['hi']:+.6f}]  "
              f"барих дундаж {r['hold_mean']:.2f} median {r['hold_median']:.1f}")
    fl_k = flatness(k_rows)
    print(f"  → CI бүгд давхцах уу: {fl_k['all_ci_overlap']}  "
          f"муж {fl_k['spread']:.6f} = CI өргөний "
          f"{100*fl_k['spread_over_ci_width']:.1f}%")

    # ------------------------------------------------------------------ 3
    reduced_L = None if fl_lstop["flat"] else \
        LSTOP_GRID[int(np.argmax([r["expectancy"] for r in lstop_rows]))]
    ks = list(K_GRID) if fl_k["flat"] else \
        [K_GRID[int(np.argmax([r["expectancy"] for r in k_rows]))]]
    print(f"\n3. цөөрүүлсэн дүрэм: L_stop = {'∞' if reduced_L is None else reduced_L}; "
          f"k = {ks} ({'бүгд, сонголт нээлттэй' if len(ks) > 1 else 'механик argmax'})")

    stab = []
    for kc in ks:
        base_r, y, tr = evaluate(c, tok, mn, kc=kc, L=reduced_L)
        yt = y[tr]
        row = {"k": kc, "L_stop": reduced_L, "base": base_r,
               "trims": {f"top{int(f*100)}": trimmed(yt, f) for f in TRIMS},
               "bottom1": trimmed(yt, 0.01, "bottom"), "lx": [], "q": [],
               "L_matched": []}
        for lx in LX_GRID:
            r, _, _ = evaluate(c, tok, mn, kc=kc, L=reduced_L, lx=lx, want_ci=False)
            row["lx"].append({"Lx": lx, "expectancy": r["expectancy"],
                              "per_sol": r["expectancy_per_sol"]})
        for q in Q_GRID:
            r, _, _ = evaluate(c, tok, mn, kc=kc, L=reduced_L, q=q, want_ci=False)
            row["q"].append({"q": q, "per_sol": r["expectancy_per_sol"],
                             "n": r["n"]})
        row["q_monotone_decreasing"] = bool(
            np.all(np.diff([x["per_sol"] for x in row["q"]]) < 0))
        # entry latency on the MATCHED sample: rows that trade at L = 8
        for Lin in L_GRID:
            yy, ttr, *_ = price(c, BASE["q"], Lin, kc, BASE["A"], reduced_L,
                                BASE["pf"], 0)
            row["L_matched"].append({
                "L": Lin, "n_matched": int(tr.sum()),
                "expectancy": float(yy[tr].mean()),
                "per_sol": float(yy[tr].mean() / BASE["q"]),
                "n_own": int(ttr.sum())})
        stab.append(row)
        print(f"  k={kc}: exp {base_r['expectancy']:+.6f}  "
              f"CI [{base_r['ci']['lo']:+.6f}, {base_r['ci']['hi']:+.6f}]  "
              f"trim1/5/10 {row['trims']['top1']:+.6f}/{row['trims']['top5']:+.6f}/"
              f"{row['trims']['top10']:+.6f}  Lx0→8 "
              f"{row['lx'][0]['per_sol']:+.6f}→{row['lx'][3]['per_sol']:+.6f}  "
              f"q↓ {row['q_monotone_decreasing']}  "
              f"L(тохирсон) " + " ".join(f"{x['L']}:{x['expectancy']:+.4f}"
                                         for x in row['L_matched']))

    n_tests = (len(lstop_rows) + len(k_rows)
               + sum(len(s["lx"]) + len(s["q"]) + len(s["L_matched"])
                     + len(s["trims"]) + 2 for s in stab))
    out = {"base": BASE,
           "lstop": {"grid": [str(x) for x in LSTOP_GRID], "rows": lstop_rows,
                     "flatness": fl_lstop},
           "k": {"grid": list(K_GRID), "rows": k_rows, "flatness": fl_k},
           "reduced": {"L_stop": reduced_L, "k_candidates": ks,
                       "rule_parameters": 1 if reduced_L is None else 2,
                       "stability": stab},
           "counts": {"this_step": n_tests, "prior": PRIOR,
                      "cumulative": PRIOR + n_tests}}
    p = config.RESULTS / "param_reduction.json"
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"\ntest {n_tests:,}, хуримтлагдсан {PRIOR + n_tests:,}\n-> {p}")


if __name__ == "__main__":
    main()
