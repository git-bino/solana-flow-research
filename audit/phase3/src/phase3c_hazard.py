"""§3c and §3c-bis — discrete hazard of burst death, on chunk 1 only.

  python -m src.phase3c_hazard

Source: `flow.burst_v2`, non-mayhem, chunk 1.  Entirely local, no Dune.

Definitions are the brief's, computed from the trajectory rather than read off
the exported `death_age_*` columns (those are cross-checked instead):

    alive(a)      nf3_traj_75_incl_pre[a] > 0,  a = 1..75   (1-indexed)
    death_age     the smallest a with nf3(a) <= 0; censored if none

Discrete hazard is the usual life-table form: everyone enters at a = 1, the risk
set at `a` is whoever has not already died, and

    h(a) = deaths(a) / at_risk(a)        S(a) = prod_{k<=a} (1 - h(k))

Confidence intervals are Wilson score intervals on the binomial proportion.
**They ignore clustering entirely** -- one token can contribute many bursts and
one minute many tokens, and neither is accounted for here.  The screening CI
showed the two-way cluster bootstrap is 1.69x wider than i.i.d. on this data, so
these intervals are optimistic by roughly that order and are reported as
nominal.  ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (Wilson rather than Wald, because Wald
is degenerate at the near-zero hazards in the tail; the absence of clustering is
the brief's instruction).

Scope: hazard only.  No other §3d cell, no §3e, no oh_conc double sort, no
fwd_price_ret.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

TRAJ = 75
Z = 1.959963984540054          # two-sided 95%
TABLE = "flow.burst_v2"


def load():
    from src.load_clickhouse_v2 import client
    cols = client().query(
        "SELECT nf3_traj_75_incl_pre, oh_ratio_a, depth_x, net_flow_5slot, "
        "       death_age_incl "
        f"FROM {TABLE} WHERE NOT mayhem"
    ).result_columns
    traj = np.asarray([list(r) for r in cols[0]], dtype=np.float64)
    return (traj,
            np.asarray(cols[1], dtype=np.float64),
            np.asarray(cols[2], dtype=np.float64),
            np.asarray(cols[3], dtype=np.float64),
            np.asarray([np.nan if v is None else v for v in cols[4]], dtype=np.float64))


def death_age(traj: np.ndarray) -> np.ndarray:
    """First 1-indexed a with nf3(a) <= 0; NaN when the trajectory never dies."""
    dead = traj <= 0
    any_dead = dead.any(axis=1)
    first = np.where(any_dead, dead.argmax(axis=1) + 1, 0)
    return np.where(any_dead, first, np.nan).astype(np.float64)


def life_table(da: np.ndarray, n: int, start: int = 1) -> dict:
    """Life table over a = start..75 for the rows given.

    `start > 1` restarts the risk set at `start`: only rows still alive entering
    `start` are counted, which is how the a = 1..3 window artefact is excluded
    without deleting those rows from the cohort.
    """
    if start > 1:
        keep = np.isnan(da) | (da >= start)
        da = da[keep]
        n = int(keep.sum())
    ages = np.arange(start, TRAJ + 1)
    deaths = np.array([int(np.sum(da == a)) for a in ages])
    at_risk = n - np.concatenate([[0], np.cumsum(deaths)[:-1]])
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.where(at_risk > 0, deaths / at_risk, np.nan)
    lo, hi = wilson(deaths, at_risk)
    surv = np.cumprod(np.where(np.isnan(h), 1.0, 1.0 - h))
    med = int(ages[np.argmax(surv <= 0.5)]) if (surv <= 0.5).any() else None
    return {"ages": ages, "at_risk": at_risk, "deaths": deaths, "hazard": h,
            "lo": lo, "hi": hi, "survival": surv, "median_survival": med,
            "n": n, "censored": int(np.isnan(da).sum())}


def wilson(k: np.ndarray, n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    k = k.astype(np.float64)
    n = n.astype(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = k / n
        d = 1 + Z * Z / n
        c = (p + Z * Z / (2 * n)) / d
        half = Z * np.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return np.where(n > 0, c - half, np.nan), np.where(n > 0, c + half, np.nan)


def quantiles(da: np.ndarray) -> dict:
    finite = da[~np.isnan(da)]
    q = [10, 25, 50, 75, 90, 99]
    return {f"p{p}": float(np.percentile(finite, p)) for p in q} | {
        "n_died": int(len(finite)), "n_censored": int(np.isnan(da).sum()),
        "censored_share": float(np.isnan(da).mean())}


def equal_groups(v: np.ndarray, k: int) -> np.ndarray:
    order = np.argsort(v, kind="stable")
    out = np.empty(len(v), dtype=np.int64)
    edges = np.linspace(0, len(v), k + 1).round().astype(int)
    for g in range(k):
        out[order[edges[g]:edges[g + 1]]] = g
    return out


def logrank(da_a: np.ndarray, da_b: np.ndarray) -> dict:
    """Two-sample log-rank over a = 1..75.  No clustering (see module docstring)."""
    na, nb = len(da_a), len(da_b)
    o_e = 0.0
    var = 0.0
    for a in range(1, TRAJ + 1):
        ra = int(np.sum(np.isnan(da_a) | (da_a >= a)))
        rb = int(np.sum(np.isnan(da_b) | (da_b >= a)))
        d_a = int(np.sum(da_a == a))
        d_b = int(np.sum(da_b == a))
        r, d = ra + rb, d_a + d_b
        if r < 2 or d == 0:
            continue
        e_a = d * ra / r
        o_e += d_a - e_a
        var += d * (ra / r) * (rb / r) * (r - d) / (r - 1)
    z = o_e / np.sqrt(var) if var > 0 else float("nan")
    from math import erfc, sqrt
    p = erfc(abs(z) / sqrt(2)) if var > 0 else float("nan")
    return {"O_minus_E": float(o_e), "var": float(var), "z": float(z),
            "p_two_sided": float(p), "n_a": na, "n_b": nb}


def fmt_table(lt: dict, every: int = 1) -> str:
    out = ["| a | эрсдэлд | үхсэн | hazard | 95% CI (Wilson, кластергүй) | S(a) |",
           "|---|---|---|---|---|---|"]
    for i, a in enumerate(lt["ages"]):
        if a % every and a not in (1, 2, 3, TRAJ):
            continue
        h = lt["hazard"][i]
        out.append(f"| {a} | {lt['at_risk'][i]:,} | {lt['deaths'][i]:,} | "
                   f"{h:.6f} | [{lt['lo'][i]:.6f}, {lt['hi'][i]:.6f}] | "
                   f"{lt['survival'][i]:.6f} |")
    return "\n".join(out)


def main() -> None:
    traj, ratio, depth, nf5, da_incl = load()
    n = len(traj)
    da = death_age(traj)
    agree = int(np.sum(np.where(np.isnan(da), -1, da) ==
                       np.where(np.isnan(da_incl), -1, da_incl)))
    print(f"{TABLE}, NOT mayhem: {n:,} мөр")
    print(f"death_age (траекториос) vs экспортын death_age_incl: {agree:,} / {n:,} таарав")

    full = life_table(da, n, 1)
    excl = life_table(da, n, 4)
    q = quantiles(da)
    print(f"\nmedian survival (a=1..75): {full['median_survival']}, "
          f"censored {q['censored_share']*100:.4f}%")
    print("death_age квантиль:", {k: v for k, v in q.items() if k.startswith('p')})
    print(f"a=1,2,3 hazard: {full['hazard'][0]:.6f} {full['hazard'][1]:.6f} "
          f"{full['hazard'][2]:.6f}")
    print(f"a>=4 restart: n {excl['n']:,}, median survival {excl['median_survival']}")

    ter = equal_groups(ratio, 3)
    ter_out = {}
    for g in range(3):
        m = ter == g
        lt = life_table(da[m], int(m.sum()), 1)
        ter_out[g] = {
            "n": int(m.sum()),
            "ratio_min": float(ratio[m].min()), "ratio_max": float(ratio[m].max()),
            "median_survival": lt["median_survival"],
            "quantiles": quantiles(da[m]),
            "depth_x_mean": float(depth[m].mean()),
            "nf5_mean": float(nf5[m].mean()), "nf5_median": float(np.median(nf5[m])),
            "hazard": lt["hazard"].tolist(), "survival": lt["survival"].tolist(),
            "at_risk": lt["at_risk"].tolist(), "deaths": lt["deaths"].tolist(),
        }
        print(f"T{g+1}: n {m.sum():,} median surv {lt['median_survival']} "
              f"depth_x {depth[m].mean():.4f} nf5 mean {nf5[m].mean():.4f}")
    lr = logrank(da[ter == 2], da[ter == 0])
    print(f"log-rank T3 vs T1: z {lr['z']:.4f}  p {lr['p_two_sided']:.3e}")

    # mechanical confound: absolute burst size deciles, terciles inside each
    size = equal_groups(nf5, 10)
    conf = []
    for s in range(10):
        ms = size == s
        row = {"size_decile": s + 1, "n": int(ms.sum()),
               "nf5_min": float(nf5[ms].min()), "nf5_max": float(nf5[ms].max()),
               "depth_x_mean": float(depth[ms].mean())}
        inner = equal_groups(ratio[ms], 3)
        sub = np.where(ms)[0]
        for g in range(3):
            idx = sub[inner == g]
            lt = life_table(da[idx], len(idx), 1)
            row[f"T{g+1}_n"] = len(idx)
            row[f"T{g+1}_median_surv"] = lt["median_survival"]
            row[f"T{g+1}_overall_hazard"] = float(
                np.nansum(lt["deaths"]) / len(idx)) if len(idx) else float("nan")
        lr_s = logrank(da[sub[inner == 2]], da[sub[inner == 0]])
        row["logrank_z"] = lr_s["z"]
        row["logrank_p"] = lr_s["p_two_sided"]
        conf.append(row)
        print(f"size d{s+1}: n {row['n']:,} nf5 [{row['nf5_min']:.3f}, "
              f"{row['nf5_max']:.3f}] T1/T2/T3 med surv "
              f"{row['T1_median_surv']}/{row['T2_median_surv']}/{row['T3_median_surv']} "
              f"z {row['logrank_z']:+.3f}")

    res = {
        "n_rows": n, "death_age_agreement": agree,
        "full": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                 for k, v in full.items()},
        "excl_123": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                     for k, v in excl.items()},
        "quantiles": q, "terciles": ter_out, "logrank_T3_T1": lr,
        "confound": conf,
    }
    p = config.RESULTS / "phase3c_hazard.json"
    p.write_text(json.dumps(res, indent=2))
    (config.RESULTS / "phase3c_tables.md").write_text(
        "### §3c бүтэн (a = 1..75)\n\n" + fmt_table(full) +
        "\n\n### §3c a >= 4 (risk set дахин эхэлсэн)\n\n" + fmt_table(excl))
    print(f"\n-> {p}")


if __name__ == "__main__":
    main()
