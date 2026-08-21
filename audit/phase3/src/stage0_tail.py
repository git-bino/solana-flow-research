"""Stage 0 — is there a tail, and does expectancy change the answer?

  python -m src.stage0_tail

The programme's question was re-framed (decisions.md, 2026-08-19) from "is the
average token profitable" to "can a profitable subset be RECOGNISED", so the
statistic moves from the median to expectancy.  This step asks whether that move
rescues anything.

Everything runs on the primary convention of `src/fwd_net_ret.py`: `x_end_slot`
reserve base, age rule `a >= A`, rules from `a >= 3`, and rows whose exit fires
at or before the latency slot are NOT TRADED and excluded from the P&L (their
count is reported).

Expectancy is computed for every cell.  Bootstrap CIs are computed only for the
cells whose point expectancy is positive -- a percentile CI cannot lie entirely
above zero when the point estimate does not, so this is exact for the question
"how many cells have a CI above zero", not an approximation.
ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (which cells get a bootstrap, not which cells
are evaluated).

`fwd_net_flow` is never given an expectancy: it is a flow, not a P&L.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.bootstrap_validation import _restricted_multiplicities  # noqa: E402
from src.exploratory_search import FEATURES, equal_groups, load_clusters  # noqa: E402
from src.fwd_net_ret import (  # noqa: E402
    A_LIMIT, FIRST_AGE, K_CONSEC, L_STOP, LATENCY, PF, Q_SIZES,
    combine, flow_exit, load, net_pnl_vec, stop_exit,
)

SEED = 20260819
B = 2_000
ALPHA = 0.05
PRIOR_EVALUATIONS = 15_139       # cumulative before this step (test_log_atomic)


def expectancy_ci(tok, mn, y, n_boot=B, seed=SEED) -> dict:
    """Two-way cluster percentile CI for a weighted MEAN (expectancy)."""
    n_cells, n_needed, compact = [], [], []
    for col in (tok, mn):
        uniq, inv = np.unique(col, return_inverse=True)
        n_cells.append(int(col.max()) + 1)
        n_needed.append(len(uniq))
        compact.append(inv)
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for b in range(n_boot):
        w = np.ones(len(y))
        for nc, nn, inv in zip(n_cells, n_needed, compact):
            w = w * _restricted_multiplicities(rng, nc, nc, nn)[inv]
        tot = w.sum()
        draws[b] = (w @ y) / tot if tot > 0 else np.nan
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return {"lo": float(lo), "hi": float(hi), "above_zero": bool(lo > 0)}


def tail_stats(y: np.ndarray) -> dict:
    """Concentration of the positive P&L, plus Gini over all of it."""
    n = len(y)
    pos = y[y > 0]
    tot_pos = float(pos.sum())
    neg_sum = float(-y[y < 0].sum())
    srt = np.sort(y)[::-1]
    out = {"n": n, "share_positive": float((y > 0).mean()),
           "total_positive": tot_pos, "total_negative": neg_sum}
    for pct in (1, 5, 10):
        k = max(1, int(round(n * pct / 100)))
        out[f"top{pct}_of_positive"] = (float(srt[:k].sum()) / tot_pos
                                        if tot_pos > 0 else float("nan"))
    k1 = max(1, int(round(n * 0.01)))
    out["top1_over_abs_negative"] = (float(srt[:k1].sum()) / neg_sum
                                     if neg_sum > 0 else float("nan"))
    s = np.sort(y)
    cum = np.cumsum(s)
    out["gini"] = float((n + 1 - 2 * (cum.sum() / cum[-1])) / n) if cum[-1] != 0 \
        else float("nan")
    return out


def cell_stats(y, q, tok=None, mn=None, want_ci=False) -> dict:
    n = len(y)
    if n == 0:
        return {"n": 0, "expectancy": float("nan")}
    exp = float(y.mean())
    out = {"n": n, "expectancy": exp, "expectancy_per_sol": exp / q,
           "median": float(np.median(y)),
           "share_positive": float((y > 0).mean())}
    if want_ci and tok is not None:
        out["ci"] = expectancy_ci(tok, mn, y)
        out["ci_per_sol"] = {"lo": out["ci"]["lo"] / q, "hi": out["ci"]["hi"] / q}
    return out


def choose_set(sets: list[dict], marg: dict) -> dict:
    """Best marginal value per parameter, restricted to combinations that trade.

    Search 01's set (k=1, A=5, L=none, q=5, L3, pf=0) is UNTRADEABLE once the
    not-traded correction is applied: an age limit of 5 exits three slots before
    an 8-slot entry lands.  Parameters are therefore fixed greedily in descending
    order of marginal spread, and a value is only taken if at least one tradeable
    set is still consistent with the choices made so far.
    ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР.
    """
    live = [s for s in sets if s["n_traded"] > 0]
    order = sorted(marg, key=lambda k: -marg[k]["spread"])
    fixed: dict = {}
    for key in order:
        ranked = sorted(marg[key]["table"], key=lambda t: -t["mean"])
        for t in ranked:
            cand = fixed | {key: t["value"]}
            if any(all(s[k] == v for k, v in cand.items()) for s in live):
                fixed = cand
                break
    return fixed


def main() -> None:
    c = load()
    d, feats = load_clusters()
    flow_ex = {k: flow_exit(c.traj, k) for k in K_CONSEC}

    # ---------------------------------------------------------------- A + B2
    sets, tails = [], []
    for lat_name, lat in LATENCY.items():
        V = c.cumf[:, lat]
        for q in Q_SIZES:
            stops = {L: stop_exit(c, q, lat, L, "true") for L in L_STOP}
            for kc in K_CONSEC:
                for A in A_LIMIT:
                    age_ex = np.full(c.n, max(A, FIRST_AGE), dtype=np.int64)
                    for L in L_STOP:
                        a_exit, _ = combine(flow_ex[kc], age_ex, stops[L])
                        traded = a_exit > lat
                        W = c.cumf[np.arange(c.n), a_exit] - V + (c.xend - c.depth)
                        y0 = net_pnl_vec(c.depth, q, V, W, 0.0)[traded]
                        for pf in PF:
                            y = y0 - 2.0 * pf
                            rec = {"latency": lat_name, "q": q, "k": kc, "A": A,
                                   "L": L, "pf": pf, "n_traded": int(traded.sum())}
                            rec |= cell_stats(y, q) if len(y) else {
                                "n": 0, "expectancy": float("nan")}
                            if len(y):
                                rec["tail"] = tail_stats(y)
                            sets.append(rec)
                            if len(y):
                                tails.append(rec["tail"])
    print(f"параметрийн багц: {len(sets):,}  (арилжсан: "
          f"{sum(1 for s in sets if s['n_traded'] > 0):,})")

    tv = {k: np.array([t[k] for t in tails]) for k in
          ("top1_of_positive", "top5_of_positive", "top10_of_positive",
           "gini", "top1_over_abs_negative", "share_positive")}
    print("\nА. Сүүлийн төвлөрөл (арилжсан багцууд дээр):")
    for k, v in tv.items():
        v = v[np.isfinite(v)]
        print(f"  {k:24} min {v.min():.6f}  median {np.median(v):.6f}  max {v.max():.6f}")

    # ------------------------------------------------------------------- B1
    marg = {}
    for key in ("latency", "q", "k", "A", "L", "pf"):
        vals = sorted({s[key] for s in sets},
                      key=lambda v: (v is None, LATENCY.get(v, v)
                                     if key == "latency" else (v or 0)))
        tab = []
        for v in vals:
            e = [s["expectancy"] for s in sets if s[key] == v]
            e = [x for x in e if np.isfinite(x)]
            tab.append({"value": v, "mean": float(np.mean(e)) if e else float("nan"),
                        "n_sets": len(e)})
        seq = [t["mean"] for t in tab]
        marg[key] = {"table": tab, "spread": float(max(seq) - min(seq))}
    chosen = choose_set(sets, marg)
    print(f"\nсонгосон багц (арилжих боломжтой хязгаарлалттай): {chosen}")

    lat = LATENCY[chosen["latency"]]
    q = chosen["q"]
    a_exit, _ = combine(flow_ex[chosen["k"]],
                        np.full(c.n, max(chosen["A"], FIRST_AGE), dtype=np.int64),
                        stop_exit(c, q, lat, chosen["L"], "true"))
    traded = a_exit > lat
    V = c.cumf[:, lat]
    W = c.cumf[np.arange(c.n), a_exit] - V + (c.xend - c.depth)
    y = net_pnl_vec(c.depth, q, V, W, chosen["pf"])
    print(f"  арилжсан {traded.sum():,} / {c.n:,}  expectancy "
          f"{y[traded].mean():+.6f}  median {np.median(y[traded]):+.6f}")

    tok_t, mn_t = d.tok[traded], d.mn[traded]
    y_t = y[traded]

    cells = []
    for name in FEATURES:
        grp = equal_groups(feats[name][traded], 10)
        for gi in range(10):
            m = grp == gi
            st = cell_stats(y_t[m], q)
            st |= {"cell": f"{name}_d{gi+1}", "feature": name, "decile": gi + 1}
            cells.append(st)
    print(f"\nБ1. feature × decile нүд: {len(cells)}")

    # combination cells, both variants (search 01)
    top3 = sorted(
        [(n, abs(np.median(y_t[equal_groups(feats[n][traded], 10) == 9])
                 - np.median(y_t[equal_groups(feats[n][traded], 10) == 0])))
         for n in FEATURES], key=lambda x: -x[1])[:3]
    names = [t[0] for t in top3]
    for side in ("top", "favourable"):
        masks = []
        for n in names:
            v = feats[n][traded]
            ter = equal_groups(v, 3)
            if side == "top":
                g = 2
            else:
                hi = np.median(y_t[equal_groups(v, 10) == 9])
                lo = np.median(y_t[equal_groups(v, 10) == 0])
                g = 2 if hi > lo else 0
            masks.append(ter == g)
        both = masks[0] & masks[1] & masks[2]
        st = cell_stats(y_t[both], q)
        st |= {"cell": f"combo_{side}", "features": names}
        cells.append(st)
    print(f"Б3. хослолын нүд: 2  (нийт нүд {len(cells)})")

    # ------------------------------------------------------- bootstrap the +ve
    pos_sets = [s for s in sets if np.isfinite(s.get("expectancy", np.nan))
                and s["expectancy"] > 0]
    pos_cells = [x for x in cells if x["n"] > 0 and x["expectancy"] > 0]
    print(f"\nэерэг цэгтэй: багц {len(pos_sets):,} / {len(sets):,}, "
          f"нүд {len(pos_cells)} / {len(cells)}")

    above = {"sets": [], "cells": []}
    for x in pos_cells:
        if "feature" in x:
            m = equal_groups(feats[x["feature"]][traded], 10) == x["decile"] - 1
        else:
            m = None
            for n in x["features"]:
                v = feats[n][traded]
                ter = equal_groups(v, 3)
                hi = np.median(y_t[equal_groups(v, 10) == 9])
                lo = np.median(y_t[equal_groups(v, 10) == 0])
                g = 2 if (x["cell"] == "combo_top" or hi > lo) else 0
                m = ter == g if m is None else m & (ter == g)
        ci = expectancy_ci(tok_t[m], mn_t[m], y_t[m])
        x["ci"] = ci
        if ci["above_zero"]:
            above["cells"].append(x["cell"])
    print(f"CI тэгээс дээш нүд: {len(above['cells'])} — {above['cells']}")

    # parameter sets: bootstrap the positive ones on the same clustering
    for s in pos_sets:
        latN = LATENCY[s["latency"]]
        ae, _ = combine(flow_ex[s["k"]],
                        np.full(c.n, max(s["A"], FIRST_AGE), dtype=np.int64),
                        stop_exit(c, s["q"], latN, s["L"], "true"))
        tr = ae > latN
        VV = c.cumf[:, latN]
        WW = c.cumf[np.arange(c.n), ae] - VV + (c.xend - c.depth)
        yy = net_pnl_vec(c.depth, s["q"], VV, WW, s["pf"])[tr]
        ci = expectancy_ci(d.tok[tr], d.mn[tr], yy, n_boot=500)
        s["ci_b500"] = ci
        if ci["above_zero"]:
            above["sets"].append({k: s[k] for k in
                                  ("latency", "q", "k", "A", "L", "pf")}
                                 | {"expectancy": s["expectancy"], "ci": ci})
    print(f"CI тэгээс дээш багц: {len(above['sets']):,} / {len(pos_sets):,}")

    # ------------------------------------------------------------------- C
    top1_med = float(np.median(tv["top1_of_positive"][
        np.isfinite(tv["top1_of_positive"])]))
    cond_a = top1_med < 0.20
    cond_b = (len(above["cells"]) == 0 and len(above["sets"]) == 0)
    verdict = "KILL" if (cond_a and cond_b) else "ҮРГЭЛЖЛҮҮЛЭХ"
    n_tests = len(sets) + len(cells)
    fp = ALPHA * (PRIOR_EVALUATIONS + n_tests)
    print(f"\nВ. (а) дээд 1% median {top1_med:.6f} < 0.20 → {cond_a}")
    print(f"   (б) CI тэгээс дээш нүд/багц байхгүй → {cond_b}")
    print(f"   → {verdict}")
    print(f"\nГ. энэ алхам {n_tests:,}, хуримтлагдсан "
          f"{PRIOR_EVALUATIONS + n_tests:,}, α=0.05 дээр хүлээгдэх худал эерэг "
          f"{fp:,.1f}")

    out = {"n_rows": c.n, "sets": sets, "cells": cells, "marginals": marg,
           "chosen_set": chosen, "above_zero": above,
           "tail_summary": {k: {"min": float(np.nanmin(v)),
                                "median": float(np.nanmedian(v)),
                                "max": float(np.nanmax(v))}
                            for k, v in tv.items()},
           "kill": {"cond_a_top1_lt_20pct": bool(cond_a), "top1_median": top1_med,
                    "cond_b_no_ci_above_zero": bool(cond_b), "verdict": verdict},
           "counts": {"this_step": n_tests, "prior": PRIOR_EVALUATIONS,
                      "cumulative": PRIOR_EVALUATIONS + n_tests,
                      "expected_false_positives_at_005": fp,
                      "bonferroni_alpha": ALPHA / (PRIOR_EVALUATIONS + n_tests)}}
    p = config.RESULTS / "stage0_tail.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"-> {p}")


if __name__ == "__main__":
    main()
