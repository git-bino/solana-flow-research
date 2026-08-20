"""Loosening the age limit `A`, everything else held fixed.

  python -m src.age_limit_curve

Base set: q=5, entry latency L=8 (L3), hard stop 0.05, k=1, pf=0, exit latency
Lx=0.  Only `A` moves, over {9, 10, 12, 15, 20, 25, 37, 50, 75}; A >= 9 because
the entry lands at slot 8 and an earlier limit is untradeable.

`A = 75` is the reference for "no effective age limit": at that setting the flow
rule does nearly all the exiting.

This module does NOT name a best `A`.  It reports the curve; picking a point off
it is a research decision, and one made after 19,544 prior evaluations.  Section
3 runs its stability checks at the A with the highest MEASURED expectancy, which
is a mechanical argmax, and says so.
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
from src.fwd_net_ret import (  # noqa: E402
    FIRST_AGE, LATENCY, TRAJ, flow_exit, load, stop_exit,
)
from src.stage0_tail import expectancy_ci  # noqa: E402

SEED = 20260819
B = 2_000
A_GRID = (9, 10, 12, 15, 20, 25, 37, 50, 75)
LX_GRID = (0, 1, 3, 8)
Q_GRID = (0.5, 1.0, 2.0, 5.0)
TRIMS = (0.01, 0.05, 0.10)
BASE = {"q": 5.0, "lat": 8, "L": 0.05, "k": 1, "pf": 0.0}
PRIOR = 19_544


def rule_labels(c, q, lat, kc, A, L, a_exit):
    """Which rule(s) fired at the exit age, as an exclusive label per row."""
    fe = flow_exit(c.traj, kc)
    age = np.full(c.n, max(A, FIRST_AGE), dtype=np.int64)
    st = stop_exit(c, q, lat, L, "true")
    f = fe == a_exit
    a = age == a_exit
    s = (st == a_exit) & (st > 0)
    lab = np.full(c.n, "none", dtype=object)
    lab[f & ~a & ~s] = "flow"
    lab[~f & a & ~s] = "age"
    lab[~f & ~a & s] = "stop"
    lab[f & a & ~s] = "flow+age"
    lab[f & ~a & s] = "flow+stop"
    lab[~f & a & s] = "age+stop"
    lab[f & a & s] = "flow+age+stop"
    return lab, f, a, s


def trimmed(y, frac, side="top"):
    n = len(y)
    k = int(round(n * frac))
    if k == 0:
        return float(y.mean())
    s = np.sort(y)
    return float(s[:n - k].mean() if side == "top" else s[k:].mean())


def evaluate(c, tok, mn, A, lx=0, q=None, want_ci=True) -> dict:
    q = BASE["q"] if q is None else q
    y, tr, a_exit, _, _, trunc = price(c, q, BASE["lat"], BASE["k"], A,
                                       BASE["L"], BASE["pf"], lx)
    yt = y[tr]
    hold = (a_exit - BASE["lat"])[tr]
    out = {"A": A, "Lx": lx, "q": q, "n": int(tr.sum()),
           "expectancy": float(yt.mean()),
           "expectancy_per_sol": float(yt.mean() / q),
           "median": float(np.median(yt)),
           "share_positive": float((yt > 0).mean()),
           "hold_mean": float(hold.mean()), "hold_median": float(np.median(hold)),
           "truncated_share": float(trunc[tr].mean())}
    if want_ci:
        out["ci"] = expectancy_ci(tok[tr], mn[tr], yt, n_boot=B, seed=SEED)
        out["ci_per_sol"] = {"lo": out["ci"]["lo"] / q, "hi": out["ci"]["hi"] / q}
    lab, f, a, s = rule_labels(c, q, BASE["lat"], BASE["k"], A, BASE["L"], a_exit)
    labt = lab[tr]
    out["rule_share"] = {"any_flow": float(f[tr].mean()),
                         "any_age": float(a[tr].mean()),
                         "any_stop": float(s[tr].mean())}
    groups = {}
    for name in ("flow", "age", "stop", "flow+age", "flow+stop", "age+stop",
                 "flow+age+stop"):
        m = labt == name
        if not m.any():
            groups[name] = {"n": 0}
            continue
        v = yt[m]
        groups[name] = {"n": int(m.sum()), "share": float(m.mean()),
                        "expectancy": float(v.mean()),
                        "median": float(np.median(v)),
                        "share_positive": float((v > 0).mean())}
    out["by_rule"] = groups
    return out, yt, tr


def main() -> None:
    c = load()
    d, _ = load_clusters()
    tok, mn = d.tok, d.mn

    curve = []
    print(f"суурь {BASE}, зөвхөн A хөдөлнө\n")
    print(f"{'A':>4} {'n':>7} {'exp':>10} {'/SOL':>10} {'median':>10} {'>0':>7} "
          f"{'CI доод':>10} {'CI дээд':>10} {'flow':>6} {'age':>6} {'stop':>6} {'барих':>6}")
    ys = {}
    for A in A_GRID:
        r, yt, tr = evaluate(c, tok, mn, A)
        curve.append(r)
        ys[A] = (yt, tr)
        rs = r["rule_share"]
        print(f"{A:>4} {r['n']:>7,} {r['expectancy']:>+10.6f} "
              f"{r['expectancy_per_sol']:>+10.6f} {r['median']:>+10.6f} "
              f"{100*r['share_positive']:>6.2f}% {r['ci']['lo']:>+10.6f} "
              f"{r['ci']['hi']:>+10.6f} {100*rs['any_flow']:>5.1f}% "
              f"{100*rs['any_age']:>5.1f}% {100*rs['any_stop']:>5.1f}% "
              f"{r['hold_median']:>6.1f}")

    exps = [r["expectancy"] for r in curve]
    argmax = A_GRID[int(np.argmax(exps))]
    diffs = np.diff(exps)
    shape = ("монотон өсөх" if np.all(diffs > 0) else
             "монотон буурах" if np.all(diffs < 0) else
             f"оргилтой (max A = {argmax})")
    print(f"\nхэлбэр: {shape}; argmax A = {argmax}")

    print("\n2. механизмын задаргаа")
    for r in curve:
        g = r["by_rule"]
        parts = [f"{k}:n={v['n']:,},exp={v['expectancy']:+.4f}"
                 for k, v in g.items() if v["n"] > 0]
        print(f"  A={r['A']:>3}  " + "  ".join(parts))

    ref = [r for r in curve if r["A"] == 75][0]
    print(f"\nA=75 (насны хязгааргүй лавлагаа): n {ref['n']:,}  "
          f"exp {ref['expectancy']:+.6f}  flow {100*ref['rule_share']['any_flow']:.1f}%")

    # ------------------------------------------------------------------ 3
    print(f"\n3. тогтвортой байдал: A = {argmax} vs A = 12")
    stab = {}
    for A in sorted({argmax, 12}):
        yt, tr = ys[A]
        row = {"A": A,
               "trims": {f"top{int(f*100)}": trimmed(yt, f) for f in TRIMS},
               "bottom1": trimmed(yt, 0.01, "bottom"),
               "lx": [], "q": []}
        for lx in LX_GRID:
            r, _, _ = evaluate(c, tok, mn, A, lx=lx, want_ci=False)
            row["lx"].append({"Lx": lx, "expectancy": r["expectancy"],
                              "per_sol": r["expectancy_per_sol"],
                              "n": r["n"]})
        for q in Q_GRID:
            r, _, _ = evaluate(c, tok, mn, A, q=q, want_ci=False)
            row["q"].append({"q": q, "per_sol": r["expectancy_per_sol"],
                             "n": r["n"]})
        per = [x["per_sol"] for x in row["q"]]
        row["q_monotone_decreasing"] = bool(np.all(np.diff(per) < 0))
        stab[A] = row
        print(f"  A={A}: trim top1/5/10 "
              f"{row['trims']['top1']:+.6f}/{row['trims']['top5']:+.6f}/"
              f"{row['trims']['top10']:+.6f}  Lx0→8 "
              f"{row['lx'][0]['per_sol']:+.6f}→{row['lx'][3]['per_sol']:+.6f}  "
              f"q монотон буурах {row['q_monotone_decreasing']}")

    n_tests = len(curve) + sum(len(v["lx"]) + len(v["q"]) + len(v["trims"]) + 1
                               for v in stab.values())
    out = {"base": BASE, "A_grid": list(A_GRID), "curve": curve,
           "shape": shape, "argmax_A": argmax,
           "reference_A75": ref, "stability": stab,
           "counts": {"this_step": n_tests, "prior": PRIOR,
                      "cumulative": PRIOR + n_tests}}
    p = config.RESULTS / "age_limit_curve.json"
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"\ntest {n_tests:,}, хуримтлагдсан {PRIOR + n_tests:,}\n-> {p}")


if __name__ == "__main__":
    main()
