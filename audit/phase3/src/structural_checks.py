"""§3 -- launch-day cluster bootstrap, trimming and leave-one-day-out.

  python -m src.structural_checks

LOCAL, 0 credit.  Reads the per-(cell, pair, launch-day) sums that
`sql/struct_cluster.sql` returned.

CLUSTER STRUCTURE.  The row is a TOKEN and each token has exactly ONE launch
day, so token is NESTED inside launch-day.  Owen's two-way pigeonhole
construction has no second, crossed factor here and reduces to a ONE-WAY
launch-day cluster bootstrap -- which is what this runs, B = 1,000.  There are
only NINE clusters: the interval width is set by those nine day-means, not by
the ~39,000 tokens, and it should be read that way.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.holder_anchor import load  # noqa: E402

B, SEED = 1000, 20260821


def main() -> None:
    rows = load()["struct_cluster"]["rows"]
    keys = sorted({(r["cell"], r["tbk"], r["lab"]) for r in rows})
    labs = {"3_3to10s": "3–10 с", "4_gt10s": "> 10 с"}
    out = {}

    hdr = (f"{'нүд':<26}{'хос':<22}{'n':>7}{'дундаж':>9}{'CI бага':>10}{'CI их':>10}"
           f"{'trim1%':>9}{'trim5%':>9}{'trim10%':>9}{'x≤115':>9}{'LOO муж':>18}")
    print(hdr)
    for cell, tbk, lab in keys:
        tot = [r for r in rows if r["cell"] == cell and r["tbk"] == tbk
               and r["lab"] == lab and r["ld"] is None]
        day = [r for r in rows if r["cell"] == cell and r["tbk"] == tbk
               and r["lab"] == lab and r["ld"] is not None]
        if not tot or not day:
            continue
        tot = tot[0]
        n = np.array([float(r["n"]) for r in day])
        s = np.array([float(r["s_ret"]) for r in day])
        rng = np.random.default_rng(SEED)
        idx = rng.integers(0, len(day), size=(B, len(day)))
        boot = s[idx].sum(1) / n[idx].sum(1)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        loo = [(s.sum() - s[i]) / (n.sum() - n[i]) for i in range(len(day))]
        name = f"{cell} × {labs[tbk]}"
        g = lambda k: float(tot[k])
        print(f"{name:<26}{lab:<22}{int(g('n')):>7,}{100*g('mean_ret'):>8.2f}%"
              f"{100*lo:>9.2f}%{100*hi:>9.2f}%"
              f"{100*g('trim01'):>8.2f}%{100*g('trim05'):>8.2f}%{100*g('trim10'):>8.2f}%"
              f"{100*g('mean_cap'):>8.2f}%"
              f"{100*min(loo):>8.2f}%..{100*max(loo):>6.2f}%")
        out[f"{cell}|{tbk}|{lab}"] = {
            "n": g("n"), "n_clusters": len(day), "mean": g("mean_ret"),
            "ci_lo": float(lo), "ci_hi": float(hi),
            "ci_excludes_zero": bool(lo > 0 or hi < 0),
            "trim01": g("trim01"), "trim05": g("trim05"), "trim10": g("trim10"),
            "mean_capped_115": g("mean_cap"),
            "loo_min": float(min(loo)), "loo_max": float(max(loo)),
            "per_day": {r["ld"]: float(r["mean_ret"]) for r in day},
        }
    Path("results/structural_checks.json").write_text(
        json.dumps({"B": B, "seed": SEED,
                    "clustering": "launch_day (one-way; token nested in day)",
                    "n_clusters": 9, "cells": out}, indent=2))

    n_pos = sum(1 for v in out.values() if v["ci_lo"] > 0)
    n_t10 = sum(1 for v in out.values() if v["trim10"] > 0)
    print(f"\nCI бүхэлдээ тэгээс ДЭЭШ: {n_pos} / {len(out)}")
    print(f"дээд 10% хассаны дараа эерэг: {n_t10} / {len(out)}")


if __name__ == "__main__":
    main()
