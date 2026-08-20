"""Execution-gap report: delayed fills, corrected E[ret], cluster CI.

  python -m src.execution_gap

LOCAL, 0 credit.  Reads the rows `sql/execution_gap_agg.sql` returned.

CLUSTER STRUCTURE: the row is a TOKEN and each token has exactly one launch day,
so token is NESTED inside launch-day -- a ONE-WAY launch-day cluster bootstrap,
B = 1,000, on NINE clusters.  Nine is thin and the interval width reflects those
nine day-means, not the ~30,000 tokens.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.holder_anchor import load  # noqa: E402

B, SEED = 1000, 20260821
LABS = {"3_3to10s": "3–10 с", "4_gt10s": "> 10 с"}
ORDER = ["e0 (одоогийн)", "e1 (1 event)", "e3 (3 event)", "e8 (8 event)",
         "t04 (0.4 с)", "t12 (1.2 с)", "t32 (3.2 с)",
         "e0 × гарц 1", "e0 × гарц 3", "РЕАЛИСТИК e3 × гарц 3"]


def boot(day_rows):
    n = np.array([float(r["n"]) - float(r["n_nofill"]) for r in day_rows])
    s = np.array([float(r["s_ret"] or 0.0) for r in day_rows])
    ok = n > 0
    n, s = n[ok], s[ok]
    if n.size < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, n.size, size=(B, n.size))
    bs = s[idx].sum(1) / n[idx].sum(1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(lo), float(hi)


def main() -> None:
    rows = load()["gap_agg"]["rows"]
    tot = [r for r in rows if r["ld"] is None and r["common8"] is None]
    com = [r for r in rows if r["common8"] is True]
    out = {}

    print("=== §1  Саатлын зай — орох fill (бүх нүд нэгтгэсэн, +76% мөрөөс) ===")
    print(f"{'саатал':<24}{'n':>8}{'дүүрээгүй%':>12}{'fill p10':>10}{'p50':>9}{'p90':>9}"
          f"{'үнэ p50':>10}{'үнэ p90':>10}")
    seen = set()
    for lab in ORDER[:7]:
        rs = [r for r in tot if r["lab"] == lab and r["tgt"] == "+76%"]
        if not rs:
            continue
        n = sum(float(r["n"]) for r in rs)
        nf = sum(float(r["n_nofill"]) for r in rs)
        f10 = np.mean([float(r["fr10"]) for r in rs if r["fr10"] is not None])
        f50 = np.mean([float(r["fr50"]) for r in rs if r["fr50"] is not None])
        f90 = np.mean([float(r["fr90"]) for r in rs if r["fr90"] is not None])
        print(f"{lab:<24}{n:>8,.0f}{100*nf/n:>11.2f}%{f10:>10.4f}{f50:>9.4f}{f90:>9.4f}"
              f"{100*(f50**2-1):>9.2f}%{100*(f90**2-1):>9.2f}%")
        seen.add(lab)

    print("\n=== §2  E[ret] саатал тутам (q = 1, зогсоолгүй) ===")
    print(f"{'нүд':<24}{'зорилт':<8}{'хувилбар':<24}{'E[ret]':>9}{'нийт поп':>10}"
          f"{'trim1':>9}{'trim5':>9}{'trim10':>9}{'CI бага':>10}{'CI их':>9}")
    for cell in ("gini g1", "creator c1"):
        for tbk in ("3_3to10s", "4_gt10s"):
            for tgt in ("+76%", "+135%"):
                base = None
                for lab in ORDER:
                    r = [z for z in tot if z["cell"] == cell and z["tbk"] == tbk
                         and z["tgt"] == tgt and z["lab"] == lab]
                    if not r:
                        continue
                    r = r[0]
                    m = float(r["mean_ret"])
                    if lab == ORDER[0]:
                        base = m
                    cm = [z for z in com if z["cell"] == cell and z["tbk"] == tbk
                          and z["tgt"] == tgt and z["lab"] == lab]
                    mc = float(cm[0]["mean_ret"]) if cm else float("nan")
                    ci = ("", "")
                    if lab in ("e3 (3 event)", "e8 (8 event)",
                               "РЕАЛИСТИК e3 × гарц 3"):
                        d = [z for z in rows if z["ld"] is not None and z["common8"] is None and z["common8"] is None
                             and z["cell"] == cell and z["tbk"] == tbk
                             and z["tgt"] == tgt and z["lab"] == lab]
                        lo, hi = boot(d)
                        ci = (f"{100*lo:+.2f}%", f"{100*hi:+.2f}%")
                        out[f"{cell}|{tbk}|{tgt}|{lab}"] = {
                            "mean": m, "ci_lo": lo, "ci_hi": hi,
                            "trim05": float(r["trim05"]),
                            "trim10": float(r["trim10"]),
                            "n_clusters": len(d)}
                    print(f"{cell+' × '+LABS[tbk]:<24}{tgt:<8}{lab:<24}"
                          f"{100*m:>8.2f}%{100*mc:>9.2f}%{100*(m-base):>+8.2f}"
                          f"{100*float(r['trim01']):>8.2f}%{100*float(r['trim05']):>8.2f}%"
                          f"{100*float(r['trim10']):>8.2f}%{ci[0]:>10}{ci[1]:>9}")
    Path("results/execution_gap.json").write_text(json.dumps(
        {"B": B, "seed": SEED, "n_clusters": 9, "cells": out}, indent=2))
    pos = sum(1 for v in out.values() if v["ci_lo"] > 0)
    t5 = sum(1 for v in out.values() if v["trim05"] > 0)
    print(f"\nCI тэгээс дээш: {pos} / {len(out)}   trim5 эерэг: {t5} / {len(out)}")


if __name__ == "__main__":
    main()
