"""Launch-day cluster CI for the early-identification AUCs.

STRUCTURAL FINDING (ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР):
The task asked for a two-way (token x launch-day) cluster bootstrap, B = 1,000.
In THIS dataset the unit of observation is the token and every token has exactly
one launch day, so token and launch-day are NESTED, not crossed.  The pigeonhole
two-way construction (Owen 2007) has no second dimension to work on here and
reduces algebraically to a one-way cluster bootstrap over launch days.  That is
what this script runs.  It is a one-way day-cluster bootstrap, B = 1,000, and it
must be read as such -- it is NOT the two-way bootstrap used on burst_v2, where
token x minute really were crossed.

There are only 9 launch days, i.e. 9 clusters.  A cluster bootstrap on 9 clusters
is thin; the interval width below is dominated by that, not by the 254k tokens.
"""
import json
import numpy as np

B, SEED = 1000, 20260821
rows = json.load(open("results/early_dayauc.json"))
out = {}

for T, v in rows.items():
    day = [r for r in v["rows"] if r["kind"] == "AUC_DAY"]
    feats = sorted({r["name"] for r in day})
    days = sorted({r["k"] for r in day})
    res = {}
    for nm in feats:
        d = {r["k"]: r for r in day if r["name"] == nm}
        auc = np.array([float(d[k]["auc"]) for k in days])
        w = np.array([float(d[k]["n_pos"]) * float(d[k]["n_neg"]) for k in days])
        point = float((auc * w).sum() / w.sum())          # pair-weighted pooled AUC
        rng = np.random.default_rng(SEED)
        idx = rng.integers(0, len(days), size=(B, len(days)))
        bw, ba = w[idx], auc[idx]
        boot = (ba * bw).sum(1) / bw.sum(1)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        res[nm] = {"auc_pooled": point, "ci_lo": float(lo), "ci_hi": float(hi),
                   "per_day": {k: float(d[k]["auc"]) for k in days}}
    out[T] = {"n_clusters": len(days), "days": days, "features": res}

json.dump({"B": B, "seed": SEED, "clustering": "launch_day (one-way; token is nested in day)",
           "points": out}, open("results/early_cluster_ci.json", "w"), indent=2)

for T, v in out.items():
    print(f"\n=== T={T}s ===  кластер {v['n_clusters']} (launch өдөр), B={B}")
    print(f"{'шинж':<16}{'AUC':>8}{'CI бага':>10}{'CI их':>9}{'өргөн':>8}   өдөр тус бүр")
    for nm, r in sorted(v["features"].items(), key=lambda x: -x[1]["auc_pooled"]):
        pd = " ".join(f"{x:.2f}" for x in r["per_day"].values())
        print(f"{nm:<16}{r['auc_pooled']:>8.4f}{r['ci_lo']:>10.4f}{r['ci_hi']:>9.4f}"
              f"{r['ci_hi']-r['ci_lo']:>8.4f}   {pd}")
