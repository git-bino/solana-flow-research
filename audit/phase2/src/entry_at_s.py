"""New estimand: enter at `s`, not at `s+L`.

  python -m src.entry_at_s

Every earlier search entered `L` slots after the burst, by which point the move
was already in the price.  This asks the opposite question: enter as the burst
prints and try to RECOGNISE the next few seconds in advance.

Causal execution clock, same as `src/causal_rule.py`:

    decision at end(s)      -- knowing only what slot s closed with
    fill      at s+1
    entry price on `x_end_slot`, the reserve end(s) knows
    a flow exit's predicate is known at end(a) and fills at a+1
    a FIXED-HORIZON exit needs no new information, so it fills at H itself

No trade gate: with L = 0 the exit can never pre-empt the entry, so all 126,089
non-mayhem rows trade.

FEATURES ARE `s`-KNOWABLE, verified against sql/extract_v2.sql rather than
assumed.  The `pfx` window is `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`;
nf5/nf12/nf25 and `accel` are prefix-sum differences over it; `oh_*` come from
`wat`, which joins wallet state at or before the trigger row; `n_buyers_12slot`
covers slots s-11..s-1 plus the trigger's own slot restricted to rows at or
before the trigger; `burst_age_slot` is `slot - first_slot`.  **Nothing derived
from `nf3_traj_75_incl_pre` is used as a feature** -- that array is the future.

Arithmetic is float64 for speed and is checked against the Decimal path in
`src.causal_rule` on a sample at start-up.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.bootstrap_validation import _restricted_multiplicities  # noqa: E402
from src.causal_rule import FEE, K, TRAJ, net_pnl  # noqa: E402

SEED = 20260819
B = 2_000
FIRST_AGE = 3
H_GRID = (3, 5, 8, 12, 25)
Q_DEFAULT = 5.0
KF = float(K)
FEEF = float(FEE)

FEATURES = [
    "net_flow_5slot", "depth_x", "oh_ratio_a", "oh_conc_a", "oh_n_wallets_a",
    "n_buyers_12slot", "size_cv_25slot", "round_frac_25slot", "accel",
    "burst_age_slot", "net_flow_12slot", "net_flow_25slot",
]


def load():
    from src.load_clickhouse_v2 import client
    cols = client().query(
        "SELECT nf3_traj_75_incl_pre, nf3_excl_pre_1, nf3_excl_pre_2, "
        "       x_end_slot, depth_x, token_mint, "
        "       toDate(parseDateTimeBestEffort(token_created_at, 'UTC')) AS lday, "
        + ", ".join(FEATURES) +
        " FROM flow.burst_v2 WHERE NOT mayhem"
    ).result_columns
    traj = np.asarray([list(r) for r in cols[0]], dtype=np.float64)
    e1 = np.asarray(cols[1], dtype=np.float64)
    e2 = np.asarray(cols[2], dtype=np.float64)
    xend = np.asarray(cols[3], dtype=np.float64)
    depth = np.asarray(cols[4], dtype=np.float64)
    _, tok = np.unique(np.asarray(cols[5]), return_inverse=True)
    _, day = np.unique(np.asarray([str(d) for d in cols[6]]), return_inverse=True)
    feats = {}
    for i, n in enumerate(FEATURES):
        feats[n] = np.asarray([np.nan if v is None else v for v in cols[7 + i]],
                              dtype=np.float64)
    return traj, e1, e2, xend, depth, tok, day, feats


def cumulative(traj, e1, e2):
    """f(1..75) from the 3-slot rolling sum, then its running total."""
    n = traj.shape[0]
    f = np.empty((n, TRAJ + 1))
    f[:, 0] = 0.0
    f[:, 1] = e1
    f[:, 2] = e2 - e1
    f[:, 3] = traj[:, 2] - e2
    for a in range(4, TRAJ + 1):
        f[:, a] = traj[:, a - 1] - traj[:, a - 2] + f[:, a - 3]
    return np.cumsum(f, axis=1)          # cum[:, 0] = 0


def flow_exit_age(traj):
    """First age >= 3 with nf3 <= 0; 75 when it never happens."""
    bad = traj <= 0
    bad[:, :FIRST_AGE - 1] = False
    any_ = bad.any(axis=1)
    return np.where(any_, bad.argmax(axis=1) + 1, TRAJ)


def pnl_vec(x_entry, q, W, pf):
    dy = KF / x_entry - KF / (x_entry + q)
    x2 = x_entry + q + W
    out = dy * x2 * x2 / (KF + dy * x2)
    return out * (1.0 - FEEF) - q / (1.0 - FEEF) - 2.0 * pf


def variant_fill_age(a_flow, kind, H=None):
    """Age at which the exit FILLS under each variant."""
    if kind == "fixed":
        return np.full(len(a_flow), min(H, TRAJ), dtype=np.int64)
    flow_fill = np.minimum(a_flow + 1, TRAJ)
    if kind == "flow":
        return flow_fill
    return np.minimum(flow_fill, min(H, TRAJ))          # earlier of the two


def cluster_ci(tok, day, y, n_boot=B, seed=SEED) -> dict:
    cells, needed, compact = [], [], []
    for col in (tok, day):
        uniq, inv = np.unique(col, return_inverse=True)
        cells.append(len(uniq)); needed.append(len(uniq)); compact.append(inv)
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for b in range(n_boot):
        w = np.ones(len(y))
        for nc, nn, inv in zip(cells, needed, compact):
            w = w * _restricted_multiplicities(rng, nc, nc, nn)[inv]
        t = w.sum()
        draws[b] = (w @ y) / t if t > 0 else np.nan
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return {"point": float(y.mean()), "lo": float(lo), "hi": float(hi),
            "above_zero": bool(lo > 0), "n": int(len(y))}


def equal_groups(v, k):
    out = np.full(len(v), -1, dtype=np.int64)
    ok = np.where(np.isfinite(v))[0]
    order = ok[np.argsort(v[ok], kind="stable")]
    edges = np.linspace(0, len(order), k + 1).round().astype(int)
    for g in range(k):
        out[order[edges[g]:edges[g + 1]]] = g
    return out


def main() -> None:
    traj, e1, e2, xend, depth, tok, day, feats = load()
    cum = cumulative(traj, e1, e2)
    a_flow = flow_exit_age(traj)
    n = len(traj)
    print(f"мөр {n:,} (бүгд арилжигдана — L = 0 тул хаалга байхгүй)")

    # float vs Decimal cross-check on a sample
    rng = np.random.default_rng(SEED)
    idx = rng.choice(n, 200, replace=False)
    worst = 0.0
    for i in idx:
        a = min(a_flow[i] + 1, TRAJ)
        got = float(pnl_vec(np.array([xend[i]]), Q_DEFAULT,
                            np.array([cum[i, a]]), 0.0)[0])
        want = float(net_pnl(Decimal(str(xend[i])), Decimal(str(Q_DEFAULT)),
                             Decimal(0), Decimal(str(cum[i, a])), Decimal(0)))
        worst = max(worst, abs(got - want) / max(abs(want), 1.0))
    print(f"float vs Decimal, 200 мөр: max харьцангуй зөрүү {worst:.3e}")

    # ------------------------------------------------------------------ 1
    variants = [("flow", None)] + [("fixed", h) for h in H_GRID] \
        + [("earlier", h) for h in H_GRID]
    base = []
    for kind, H in variants:
        a_fill = variant_fill_age(a_flow, kind, H)
        y = pnl_vec(xend, Q_DEFAULT, cum[np.arange(n), a_fill], 0.0)
        hold = a_fill - 1                       # entry fills at age 1
        ci = cluster_ci(tok, day, y)
        r = {"kind": kind, "H": H, "n": n,
             "expectancy": float(y.mean()),
             "expectancy_per_sol": float(y.mean() / Q_DEFAULT),
             "median": float(np.median(y)),
             "share_positive": float((y > 0).mean()),
             "p10": float(np.percentile(y, 10)), "p25": float(np.percentile(y, 25)),
             "p75": float(np.percentile(y, 75)), "p90": float(np.percentile(y, 90)),
             "hold_mean": float(hold.mean()), "hold_median": float(np.median(hold)),
             "ci": ci}
        base.append(r)
        lab = kind if H is None else f"{kind} H={H}"
        print(f"  {lab:14} exp {r['expectancy']:+.6f}  /SOL {r['expectancy_per_sol']:+.6f}  "
              f"median {r['median']:+.6f}  >0 {100*r['share_positive']:5.2f}%  "
              f"CI [{ci['lo']:+.6f}, {ci['hi']:+.6f}]  барих {r['hold_mean']:.2f}")

    best = max(base, key=lambda r: r["expectancy"])
    lab = best["kind"] if best["H"] is None else f"{best['kind']} H={best['H']}"
    print(f"\nхамгийн өндөр expectancy-тэй хувилбар: {lab} ({best['expectancy']:+.6f})")
    a_fill = variant_fill_age(a_flow, best["kind"], best["H"])
    y = pnl_vec(xend, Q_DEFAULT, cum[np.arange(n), a_fill], 0.0)

    # ------------------------------------------------------------------ 2
    print("\n2. `s` дээр мэдэгдэх шинжүүд, 10 decile")
    cells = []
    for name in FEATURES:
        grp = equal_groups(feats[name], 10)
        rows = []
        for g in range(10):
            m = grp == g
            v = y[m]
            rows.append({"decile": g + 1, "n": int(m.sum()),
                         "expectancy": float(v.mean()),
                         "median": float(np.median(v)),
                         "share_positive": float((v > 0).mean()),
                         "feat_min": float(feats[name][m].min()),
                         "feat_max": float(feats[name][m].max())})
        # CI only where the point estimate is positive, plus d1 and d10 always:
        # a percentile CI cannot sit above zero when the point does not.
        for g in (0, 9):
            m = grp == g
            rows[g]["ci"] = cluster_ci(tok[m], day[m], y[m])
        for g in range(10):
            if "ci" not in rows[g] and rows[g]["expectancy"] > 0:
                m = grp == g
                rows[g]["ci"] = cluster_ci(tok[m], day[m], y[m])
        pos = [r for r in rows if r["expectancy"] > 0]
        above = [r for r in rows if r.get("ci", {}).get("above_zero")]
        delta = rows[9]["expectancy"] - rows[0]["expectancy"]
        cells.append({"feature": name, "deciles": rows, "delta_d10_d1": delta,
                      "n_positive_deciles": len(pos),
                      "n_ci_above_zero": len(above),
                      "n_nan": int((~np.isfinite(feats[name])).sum())})
        print(f"  {name:20} d1 {rows[0]['expectancy']:+.6f}  d10 {rows[9]['expectancy']:+.6f}  "
              f"Δ {delta:+.6f}  эерэг decile {len(pos)}  CI>0 {len(above)}")

    # ------------------------------------------------------------------ 3
    top3 = sorted(cells, key=lambda c: -abs(c["delta_d10_d1"]))[:3]
    names = [c["feature"] for c in top3]
    print(f"\n3. хослол — |Δ|-ээр хамгийн хүчтэй 3: {names}")
    combos = []
    for side in ("top", "bottom"):
        masks = []
        for c in top3:
            ter = equal_groups(feats[c["feature"]], 3)
            masks.append(ter == (2 if side == "top" else 0))
        m = masks[0] & masks[1] & masks[2]
        rec = {"side": side, "features": names, "n": int(m.sum())}
        if m.sum() >= 1000:
            v = y[m]
            rec |= {"expectancy": float(v.mean()), "median": float(np.median(v)),
                    "share_positive": float((v > 0).mean()),
                    "ci": cluster_ci(tok[m], day[m], y[m])}
            print(f"  {side}: n {rec['n']:,}  exp {rec['expectancy']:+.6f}  "
                  f"median {rec['median']:+.6f}  >0 {100*rec['share_positive']:.2f}%  "
                  f"CI [{rec['ci']['lo']:+.6f}, {rec['ci']['hi']:+.6f}]")
        else:
            rec["stopped"] = "n < 1,000"
            print(f"  {side}: n {rec['n']:,} < 1,000 — ЗОГСОВ")
        combos.append(rec)

    n_above = sum(c["n_ci_above_zero"] for c in cells) \
        + sum(1 for c in combos if c.get("ci", {}).get("above_zero"))
    print(f"\nCI нь тэгээс дээш нүд: {n_above}")

    n_tests = len(base) + sum(len(c["deciles"]) for c in cells) + len(combos)
    out = {"n_rows": n, "float_vs_decimal_max_rel": worst,
           "baseline": base, "best_variant": lab, "features": cells,
           "combos": combos, "n_ci_above_zero": n_above,
           "cluster": "token x launch-day",
           "counts": {"this_step": n_tests, "prior_evaluations": 19_658,
                      "cumulative_evaluations": 19_658 + n_tests}}
    p = config.RESULTS / "entry_at_s.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"\ntest {n_tests:,}, хуримтлагдсан үнэлгээ {19_658 + n_tests:,}\n-> {p}")


if __name__ == "__main__":
    main()
