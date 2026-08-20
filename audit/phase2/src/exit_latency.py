"""Exit latency — the §5.1 asymmetry that the P&L has so far ignored.

  python -m src.exit_latency

Entry has carried a latency of up to 8 slots from the start; the exit has been
instantaneous.  §5.1 says the flow during the exit latency is CONDITIONALLY
NEGATIVE, because the exit rule fires exactly when flow turns, so others are
selling ahead of you.  This step prices that.

The exit rule still fires at `a_exit`; the fill lands at `a_exit + Lx`.  The
reserve at the fill comes from the same reconstruction the rest of the study
uses, `x_end_slot + cumf[a]`, validated against the exported `x_at_plus{5,12,37}`
on all 126,089 rows.  A row whose fill would land past age 75 is NOT dropped --
it is forced out at 75 and counted, because dropping it would be survivorship.

Nothing here decides anything; it reports numbers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.exploratory_search import load_clusters  # noqa: E402
from src.fwd_net_ret import (  # noqa: E402
    A_LIMIT, FIRST_AGE, K_CONSEC, L_STOP, LATENCY, PF, Q_SIZES, TRAJ,
    combine, flow_exit, load, net_pnl_vec, stop_exit,
)
from src.stage0_checks import BEST  # noqa: E402
from src.stage0_tail import expectancy_ci  # noqa: E402

SEED = 20260819
B = 2_000
LX = (0, 1, 3, 8)
ENTRY_L = (1, 3, 8)
PRIOR = 19_437
N_REPRESENTATIVE = 20


def price(c, q, lat, kc, A, L, pf, lx):
    """P&L with the exit fill delayed by `lx` slots past the rule."""
    a_rule, _ = combine(flow_exit(c.traj, kc),
                        np.full(c.n, max(A, FIRST_AGE), dtype=np.int64),
                        stop_exit(c, q, lat, L, "true"))
    traded = a_rule > lat
    a_fill = np.minimum(a_rule + lx, TRAJ)
    truncated = (a_rule + lx) > TRAJ
    V = c.cumf[:, lat]
    idx = np.arange(c.n)
    W = c.cumf[idx, a_fill] - V + (c.xend - c.depth)
    w_exit = c.cumf[idx, a_fill] - c.cumf[idx, a_rule]
    y = net_pnl_vec(c.depth, q, V, W, pf)
    return y, traded, a_rule, a_fill, w_exit, truncated


def summarise(y, traded, w_exit, truncated, q, tok, mn, want_ci=True) -> dict:
    yt = y[traded]
    we = w_exit[traded]
    out = {"n": int(traded.sum()),
           "expectancy": float(yt.mean()),
           "expectancy_per_sol": float(yt.mean() / q),
           "median": float(np.median(yt)),
           "share_positive": float((yt > 0).mean()),
           "truncated_share": float(truncated[traded].mean()),
           "w_exit": {"median": float(np.median(we)),
                      "p10": float(np.percentile(we, 10)),
                      "p90": float(np.percentile(we, 90)),
                      "share_negative": float((we < 0).mean()),
                      "share_zero": float((we == 0).mean())}}
    if want_ci:
        out["ci"] = expectancy_ci(tok[traded], mn[traded], yt, n_boot=B, seed=SEED)
        out["ci_per_sol"] = {"lo": out["ci"]["lo"] / q, "hi": out["ci"]["hi"] / q}
    return out


def representative(sets: list[dict], k: int = N_REPRESENTATIVE) -> list[dict]:
    """`k` sets spread evenly over the expectancy range, lowest to highest.

    Not the top k: the brief asks for representative sets, and taking the best
    ones would answer a different question.  Deterministic -- sort by expectancy
    and take evenly spaced ranks.
    ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР.
    """
    srt = sorted(sets, key=lambda s: s["expectancy"])
    idx = np.linspace(0, len(srt) - 1, k).round().astype(int)
    return [srt[i] for i in idx]


def main() -> None:
    c = load()
    d, _ = load_clusters()
    tok, mn = d.tok, d.mn

    # ---------------------------------------------------------------- 1
    lat = LATENCY[BEST["latency"]]
    best_rows = []
    print(f"хамгийн сайн багц {BEST}")
    for lx in LX:
        y, tr, a_rule, a_fill, we, trunc = price(
            c, BEST["q"], lat, BEST["k"], BEST["A"], BEST["L"], BEST["pf"], lx)
        r = summarise(y, tr, we, trunc, BEST["q"], tok, mn)
        r["Lx"] = lx
        best_rows.append(r)
        print(f"  Lx={lx}: exp {r['expectancy']:+.6f}  /SOL {r['expectancy_per_sol']:+.6f}  "
              f"median {r['median']:+.6f}  >0 {100*r['share_positive']:.2f}%  "
              f"CI [{r['ci']['lo']:+.6f}, {r['ci']['hi']:+.6f}]  "
              f"W_exit median {r['w_exit']['median']:+.6f} "
              f"сөрөг {100*r['w_exit']['share_negative']:.2f}%")

    # representative 20, from the tradeable sets at Lx = 0
    all_sets = []
    for lat_name, latN in LATENCY.items():
        for q in Q_SIZES:
            for kc in K_CONSEC:
                for A in A_LIMIT:
                    for L in L_STOP:
                        y, tr, *_ = price(c, q, latN, kc, A, L, 0.0, 0)
                        if not tr.any():
                            continue
                        for pf in PF:
                            all_sets.append({"latency": lat_name, "q": q, "k": kc,
                                             "A": A, "L": L, "pf": pf,
                                             "n": int(tr.sum()),
                                             "expectancy": float((y[tr] - 2 * pf).mean())})
    reps = representative(all_sets)
    print(f"\nтөлөөлөх {len(reps)} багц (expectancy-ийн мужаар жигд):")
    rep_rows = []
    for s in reps:
        latN = LATENCY[s["latency"]]
        row = {"set": {k2: s[k2] for k2 in ("latency", "q", "k", "A", "L", "pf")},
               "by_lx": []}
        for lx in LX:
            y, tr, _, _, we, trunc = price(c, s["q"], latN, s["k"], s["A"],
                                           s["L"], s["pf"], lx)
            r = summarise(y, tr, we, trunc, s["q"], tok, mn)
            r["Lx"] = lx
            row["by_lx"].append(r)
        rep_rows.append(row)
        e0 = row["by_lx"][0]["expectancy_per_sol"]
        e8 = row["by_lx"][3]["expectancy_per_sol"]
        print(f"  {s['latency']} q={s['q']} k={s['k']} A={s['A']} L={s['L']} "
              f"pf={s['pf']}: /SOL Lx0 {e0:+.6f} → Lx8 {e8:+.6f}  "
              f"CI(Lx8) [{row['by_lx'][3]['ci_per_sol']['lo']:+.6f}, "
              f"{row['by_lx'][3]['ci_per_sol']['hi']:+.6f}]")

    # ---------------------------------------------------------------- 2
    grid = []
    print("\n2. орох × гарах latency-ийн тор (per SOL risked):")
    for Lin in ENTRY_L:
        for lx in LX:
            y, tr, _, _, we, trunc = price(c, BEST["q"], Lin, BEST["k"],
                                           BEST["A"], BEST["L"], BEST["pf"], lx)
            if not tr.any():
                grid.append({"L": Lin, "Lx": lx, "n": 0})
                continue
            r = summarise(y, tr, we, trunc, BEST["q"], tok, mn)
            r |= {"L": Lin, "Lx": lx, "symmetric": Lin == lx}
            grid.append(r)
            print(f"  L={Lin} Lx={lx}{'  (тэгш хэмтэй)' if Lin == lx else '':16} "
                  f"n {r['n']:>6,}  /SOL {r['expectancy_per_sol']:+.6f}  "
                  f"CI [{r['ci_per_sol']['lo']:+.6f}, {r['ci_per_sol']['hi']:+.6f}]")

    # ---------------------------------------------------------------- 3
    y, tr, a_rule, _, _, _ = price(c, BEST["q"], lat, BEST["k"], BEST["A"],
                                   BEST["L"], BEST["pf"], 0)
    hold = (a_rule - lat)[tr]
    yt = y[tr]
    total_pos = float(yt[yt > 0].sum())
    buckets = [("1", hold == 1), ("2–3", (hold >= 2) & (hold <= 3)),
               ("4–7", (hold >= 4) & (hold <= 7)), ("8+", hold >= 8)]
    hold_rows = []
    print("\n3. барих хугацаагаар:")
    for lab, m in buckets:
        if not m.any():
            hold_rows.append({"bucket": lab, "n": 0})
            continue
        v = yt[m]
        r = {"bucket": lab, "n": int(m.sum()),
             "share_of_rows": float(m.mean()),
             "expectancy": float(v.mean()), "median": float(np.median(v)),
             "share_positive": float((v > 0).mean()),
             "sum_pnl": float(v.sum()),
             "share_of_positive_pnl": float(v[v > 0].sum() / total_pos)
                                      if total_pos > 0 else float("nan")}
        hold_rows.append(r)
        print(f"  {lab:4} n {r['n']:>6,} ({100*r['share_of_rows']:5.2f}%)  "
              f"exp {r['expectancy']:+.6f}  median {r['median']:+.6f}  "
              f">0 {100*r['share_positive']:5.2f}%  "
              f"эерэг P&L-ийн {100*r['share_of_positive_pnl']:5.2f}%")

    n_tests = len(best_rows) + len(reps) * len(LX) + len(grid) + len(hold_rows)
    out = {"best": BEST, "best_by_lx": best_rows,
           "representative": rep_rows, "grid": grid, "hold": hold_rows,
           "counts": {"this_step": n_tests, "prior": PRIOR,
                      "cumulative": PRIOR + n_tests}}
    p = config.RESULTS / "exit_latency.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"\ntest {n_tests:,}, хуримтлагдсан {PRIOR + n_tests:,}\n-> {p}")


if __name__ == "__main__":
    main()
