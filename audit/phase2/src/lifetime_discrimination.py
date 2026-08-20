"""Can `s`-knowable features tell a long burst from a short one?

  python -m src.lifetime_discrimination

This is NOT a profit measurement.  There is no P&L, no expectancy, no cost model
and no latency here -- only classification.

Label:   death_age > T,  T in {5, 8, 12, 20}
Score:   each of twelve features, taken as-is

AUC is reported with its SIGN INTACT.  A value below 0.5 means the feature points
the other way; it is not flipped, because flipping would hide which direction the
data chose.  What matters is distance from 0.5, and that is reported alongside.

The permutation null shuffles `death_age` WITHIN launch-day, never across days:
98.98% of this cohort's bursts sit on ten launch dates, so a cross-day shuffle
would break the day-level clustering and manufacture signal.  The same within-day
restriction is what the token x launch-day bootstrap assumes.

Combination (§4) sums the three strongest features' deciles after orienting each
by the direction the data shows.  A logistic regression was NOT used: it would
fit coefficients on the same rows it is scored on.  The orientation and the
top-three selection both use the label, so the combination's null RE-DERIVES both
inside every permutation rather than freezing them from the real data.
ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (score form and null construction).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.bootstrap_validation import _restricted_multiplicities  # noqa: E402

SEED = 20260819
B_BOOT = 1_000
N_PERM = 200
THRESHOLDS = (5, 8, 12, 20)
FEATURES = [
    "net_flow_5slot", "net_flow_12slot", "net_flow_25slot", "depth_x",
    "oh_ratio_a", "oh_conc_a", "oh_n_wallets_a", "n_buyers_12slot",
    "size_cv_25slot", "round_frac_25slot", "accel", "burst_age_slot",
]
CENSORED_AGE = 75


def load():
    from src.load_clickhouse_v2 import client
    cols = client().query(
        "SELECT death_age_incl, token_mint, "
        "       toDate(parseDateTimeBestEffort(token_created_at, 'UTC')) AS lday, "
        + ", ".join(FEATURES) +
        " FROM flow.burst_v2 WHERE NOT mayhem"
    ).result_columns
    death = np.asarray([CENSORED_AGE if v is None else v for v in cols[0]],
                       dtype=np.float64)
    _, tok = np.unique(np.asarray(cols[1]), return_inverse=True)
    days = np.asarray([str(d) for d in cols[2]])
    _, day = np.unique(days, return_inverse=True)
    feats = {n: np.asarray([np.nan if v is None else v for v in cols[3 + i]],
                           dtype=np.float64)
             for i, n in enumerate(FEATURES)}
    return death, tok, day, feats


def ranks_of(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mid-ranks (ties averaged) and the sort order, computed once per feature."""
    order = np.argsort(v, kind="stable")
    s = v[order]
    r = np.empty(len(v), dtype=np.float64)
    i = 0
    pos = 1.0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        r[order[i:j + 1]] = pos + (j - i) / 2.0
        pos += (j - i + 1)
        i = j + 1
    return r, order


def auc_from_ranks(rank: np.ndarray, pos: np.ndarray) -> float:
    """Mann-Whitney AUC, ties handled by mid-ranks.  NaN scores excluded."""
    n1 = int(pos.sum())
    n0 = int((~pos).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((rank[pos].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def weighted_auc(order: np.ndarray, pos: np.ndarray, w: np.ndarray) -> float:
    """Weighted AUC in sorted-score order: negative weight accumulated below."""
    p = pos[order]
    ww = w[order]
    wpos = ww * p
    wneg = ww * (~p)
    below = np.concatenate([[0.0], np.cumsum(wneg)[:-1]])
    num = float((wpos * (below + 0.5 * wneg)).sum())
    den = float(wpos.sum() * wneg.sum())
    return num / den if den > 0 else float("nan")


def cluster_weights(rng, tok_cells, tok_inv, day_cells, day_inv, n):
    w = np.ones(n)
    w *= _restricted_multiplicities(rng, tok_cells, tok_cells, tok_cells)[tok_inv]
    w *= _restricted_multiplicities(rng, day_cells, day_cells, day_cells)[day_inv]
    return w


def shuffle_within_day(rng, death, day):
    out = death.copy()
    for d in np.unique(day):
        m = day == d
        out[m] = rng.permutation(death[m])
    return out


def main() -> None:
    death, tok, day, feats = load()
    n = len(death)
    print(f"мөр {n:,}  токен {len(np.unique(tok)):,}  launch өдөр {len(np.unique(day))}")

    base = {}
    for T in THRESHOLDS:
        base[T] = float((death > T).mean())
        print(f"  T={T:>2}: «урт» суурь хувь {100*base[T]:.4f}%  "
              f"(n_урт {int((death > T).sum()):,})")

    rank, order = {}, {}
    for f in FEATURES:
        v = feats[f]
        if not np.isfinite(v).all():
            v = np.where(np.isfinite(v), v, np.nanmedian(v))
            feats[f] = v
        rank[f], order[f] = ranks_of(v)

    # ------------------------------------------------------------------ 2
    print("\n2. AUC (тэмдэг хэвээр)")
    auc = {}
    for f in FEATURES:
        row = []
        for T in THRESHOLDS:
            a = auc_from_ranks(rank[f], death > T)
            auc[(f, T)] = a
            row.append(a)
        print(f"  {f:20} " + "  ".join(f"T{T}={a:.4f}" for T, a in zip(THRESHOLDS, row))
              + f"   max|Δ0.5| {max(abs(x - 0.5) for x in row):.4f}")

    strength = {f: max(abs(auc[(f, T)] - 0.5) for T in THRESHOLDS) for f in FEATURES}
    top3 = sorted(FEATURES, key=lambda f: -strength[f])[:3]
    print(f"\nхамгийн хүчтэй 3 (|AUC−0.5|-ээр): {top3}")

    # decile tables
    dec = {}
    for f in FEATURES:
        v = feats[f]
        o = np.argsort(v, kind="stable")
        g = np.empty(n, dtype=np.int64)
        edges = np.linspace(0, n, 11).round().astype(int)
        for k in range(10):
            g[o[edges[k]:edges[k + 1]]] = k
        rows = []
        for k in range(10):
            m = g == k
            rows.append({"decile": k + 1, "n": int(m.sum()),
                         "feat_min": float(v[m].min()), "feat_max": float(v[m].max()),
                         **{f"long_T{T}": float((death[m] > T).mean())
                            for T in THRESHOLDS}})
        dec[f] = rows

    # ------------------------------------------------------------- 2c CI
    print("\n2c. AUC-ийн 95% CI (token × launch-day, B = 1,000)")
    tok_cells, day_cells = int(tok.max()) + 1, int(day.max()) + 1
    rng = np.random.default_rng(SEED)
    draws = {k: np.empty(B_BOOT) for k in auc}
    for b in range(B_BOOT):
        w = cluster_weights(rng, tok_cells, tok, day_cells, day, n)
        for f in FEATURES:
            for T in THRESHOLDS:
                draws[(f, T)][b] = weighted_auc(order[f], death > T, w)
    ci = {}
    for k, v in draws.items():
        lo, hi = np.nanpercentile(v, [2.5, 97.5])
        ci[k] = {"lo": float(lo), "hi": float(hi),
                 "excludes_half": bool(lo > 0.5 or hi < 0.5)}
    n_excl = sum(1 for v in ci.values() if v["excludes_half"])
    print(f"  0.5-ыг үл агуулах нүд: {n_excl} / {len(ci)}")

    # ------------------------------------------------------------------ 3
    print(f"\n3. permutation null ({N_PERM} удаа, launch-day ДОТОР холисон)")
    rng = np.random.default_rng(SEED + 1)
    null_all = []
    null_by = {f: [] for f in FEATURES}
    null_combo = []
    for p in range(N_PERM):
        dp = shuffle_within_day(rng, death, day)
        best = 0.0
        st_p = {}
        for f in FEATURES:
            s_f = 0.0
            for T in THRESHOLDS:
                a = auc_from_ranks(rank[f], dp > T)
                null_all.append(a)
                d = abs(a - 0.5)
                best = max(best, d)
                s_f = max(s_f, d)
            null_by[f].append(s_f)
            st_p[f] = s_f
        # combination null: re-select AND re-orient inside the permutation
        t3 = sorted(FEATURES, key=lambda f: -st_p[f])[:3]
        sc = np.zeros(n)
        for f in t3:
            sgn = 1.0 if auc_from_ranks(rank[f], dp > THRESHOLDS[0]) >= 0.5 else -1.0
            sc += sgn * rank[f]
        r_c, o_c = ranks_of(sc)
        null_combo.append(max(abs(auc_from_ranks(r_c, dp > T) - 0.5)
                              for T in THRESHOLDS))
        best_all = best
    na = np.abs(np.array(null_all) - 0.5)
    real_best = max(strength.values())
    print(f"  null |AUC−0.5|: median {np.median(na):.4f}  p95 {np.percentile(na,95):.4f}  "
          f"p99 {np.percentile(na,99):.4f}  max {na.max():.4f}")
    nb = np.array([max(v) for v in zip(*[null_by[f] for f in FEATURES])])
    p_sel = float((nb >= real_best).mean())
    print(f"  бодит хамгийн өндөр |AUC−0.5| = {real_best:.4f}; "
          f"null-ийн 48-аас хамгийн өндөр нь median {np.median(nb):.4f}, "
          f"p95 {np.percentile(nb,95):.4f}, max {nb.max():.4f}")
    print(f"  → сонголтыг залруулсан p = {p_sel:.4f}")

    # ------------------------------------------------------------------ 4
    print(f"\n4. хослол — {top3}")
    score = np.zeros(n)
    orient = {}
    for f in top3:
        sgn = 1.0 if auc[(f, THRESHOLDS[0])] >= 0.5 else -1.0
        orient[f] = sgn
        score += sgn * rank[f]
    r_c, o_c = ranks_of(score)
    combo = {}
    for T in THRESHOLDS:
        a = auc_from_ranks(r_c, death > T)
        combo[T] = a
        print(f"  T={T:>2}: AUC {a:.4f}  |Δ0.5| {abs(a-0.5):.4f}")
    combo_best = max(abs(v - 0.5) for v in combo.values())
    nc = np.array(null_combo)
    p_combo = float((nc >= combo_best).mean())
    print(f"  null (дахин сонголт+чиглэлтэй): median {np.median(nc):.4f}  "
          f"p95 {np.percentile(nc,95):.4f}  max {nc.max():.4f}  → p = {p_combo:.4f}")
    g = np.empty(n, dtype=np.int64)
    o = np.argsort(score, kind="stable")
    edges = np.linspace(0, n, 11).round().astype(int)
    for k in range(10):
        g[o[edges[k]:edges[k + 1]]] = k
    combo_dec = [{"decile": k + 1, "n": int((g == k).sum()),
                  **{f"long_T{T}": float((death[g == k] > T).mean())
                     for T in THRESHOLDS}} for k in range(10)]
    for T in THRESHOLDS:
        print(f"  T={T:>2}: d10 {100*combo_dec[9][f'long_T{T}']:.4f}%  "
              f"d1 {100*combo_dec[0][f'long_T{T}']:.4f}%  суурь {100*base[T]:.4f}%  "
              f"d10/суурь {combo_dec[9][f'long_T{T}']/base[T]:.4f}")

    n_tests = len(auc) + len(combo)
    out = {"n_rows": n, "base_rate": base,
           "auc": {f"{f}|{T}": auc[(f, T)] for f, T in auc},
           "auc_ci": {f"{f}|{T}": ci[(f, T)] for f, T in ci},
           "strength": strength, "top3": top3, "deciles": dec,
           "null": {"median": float(np.median(na)),
                    "p95": float(np.percentile(na, 95)),
                    "p99": float(np.percentile(na, 99)),
                    "max": float(na.max()),
                    "max_of_48_median": float(np.median(nb)),
                    "max_of_48_p95": float(np.percentile(nb, 95)),
                    "max_of_48_max": float(nb.max()),
                    "real_best": real_best, "p_selection_corrected": p_sel,
                    "per_feature_p95": {f: float(np.percentile(null_by[f], 95))
                                        for f in FEATURES}},
           "combo": {"features": top3, "orientation": orient,
                     "auc": combo, "best_abs": combo_best,
                     "null_median": float(np.median(nc)),
                     "null_p95": float(np.percentile(nc, 95)),
                     "null_max": float(nc.max()), "p": p_combo,
                     "deciles": combo_dec},
           "n_ci_excluding_half": n_excl,
           "counts": {"this_step": n_tests, "prior": 19_791,
                      "cumulative": 19_791 + n_tests}}
    p = config.RESULTS / "lifetime_discrimination.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"\ntest {n_tests}, хуримтлагдсан {19_791 + n_tests:,}\n-> {p}")


if __name__ == "__main__":
    main()
