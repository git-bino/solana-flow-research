"""Phase 3b SCREENING — one pre-registered cell on chunk 1 only.

  python -m src.phase3b_screening

Cell (decisions.md 2026-08-19, registered before any result was seen):
threshold 0.10x, tau = 12 slots, non-mayhem, row-level deciles of `oh_ratio_a`,
statistic median(d10) - median(d1), pigeonhole two-way bootstrap over
token x minute, B = 2,000, seed 20260819, 95% percentile CI.

Stop rule, same registration: STOP if the CI lies entirely inside
(-0.657, +0.657) SOL; CONTINUE otherwise.  Two-sided -- no direction was
pre-specified.

The CI machinery is `src/bootstrap_validation.Estimator`, unchanged: the
restricted-multinomial resampling it implements was validated by simulation
(docs/bootstrap_validation.md) and re-implementing it here would put an
unvalidated copy on the critical path.

Screening is ONE cell.  No hazard curves, no oh_conc double sort, no other
threshold/tau cells, no oh_b repeat, no rug split, no placebo -- those belong to
the confirmatory stage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.bootstrap_validation import Data, Estimator  # noqa: E402

SEED = 20260819
B = 2_000
BREAKEVEN = 0.657231
N_DECILES = 10
TABLE = "flow.burst_v2"


def load_cell() -> tuple[Data, np.ndarray, np.ndarray]:
    """The primary cell from `flow.burst_v2`: non-mayhem rows, chunk 1 only."""
    from src.load_clickhouse_v2 import client
    cols = client().query(
        "SELECT fwd_net_flow_12slot, oh_ratio_a, token_mint, "
        "       toUnixTimestamp(toStartOfMinute("
        "           parseDateTimeBestEffort(block_time, 'UTC'))) AS minute_utc, "
        "       trigger_wallet, depth_x "
        f"FROM {TABLE} WHERE NOT mayhem"
    ).result_columns
    y = np.asarray(cols[0], dtype=np.float64)
    ratio = np.asarray(cols[1], dtype=np.float64)
    _, tok = np.unique(np.asarray(cols[2]), return_inverse=True)
    minute = np.asarray(cols[3], dtype=np.int64)
    _, mn = np.unique(minute, return_inverse=True)
    _, wal = np.unique(np.asarray(cols[4]), return_inverse=True)
    _, blk5 = np.unique(minute // 300, return_inverse=True)
    depth = np.asarray(cols[5], dtype=np.float64)
    return Data(y, tok, mn, wal, blk5, len(y)), ratio, depth


def deciles(ratio: np.ndarray) -> np.ndarray:
    """Equal-sized row-level deciles, 0 = lowest.

    The brief says ten EQUAL groups, so the split is by rank rather than by
    quantile value: quantile cuts on a variable with ties leave unequal groups.
    Ties are therefore broken by sort position, and the per-decile min/max of
    `oh_ratio_a` is reported so any group straddling a tied value is visible.
    ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (tie handling; the cell itself is registered).
    """
    order = np.argsort(ratio, kind="stable")
    out = np.empty(len(ratio), dtype=np.int64)
    edges = np.linspace(0, len(ratio), N_DECILES + 1).round().astype(int)
    for g in range(N_DECILES):
        out[order[edges[g]:edges[g + 1]]] = g
    return out


def trimmed_mean(v: np.ndarray, frac: float = 0.10) -> float:
    v = np.sort(v)
    k = int(len(v) * frac)
    return float(v[k:len(v) - k].mean()) if len(v) - 2 * k > 0 else float("nan")


def main() -> None:
    d, ratio, depth = load_cell()
    grp = deciles(ratio)
    print(f"cell: {TABLE}, NOT mayhem, {d.n_rows:,} мөр, "
          f"{len(np.unique(d.tok)):,} токен, {len(np.unique(d.mn)):,} минут\n")

    rows = []
    for g in range(N_DECILES):
        m = grp == g
        y = d.y[m]
        rows.append({
            "decile": g + 1, "n": int(m.sum()),
            "ratio_min": float(ratio[m].min()), "ratio_max": float(ratio[m].max()),
            "median": float(np.median(y)),
            "trimmed_mean_10": trimmed_mean(y),
            "p25": float(np.percentile(y, 25)), "p75": float(np.percentile(y, 75)),
            "share_positive": float((y > 0).mean()),
            "depth_x_mean": float(depth[m].mean()),
            "n_tokens": int(len(np.unique(d.tok[m]))),
            "n_minutes": int(len(np.unique(d.mn[m]))),
        })
        r = rows[-1]
        print(f"d{r['decile']:<2} n={r['n']:>7,}  ratio [{r['ratio_min']:.6g}, "
              f"{r['ratio_max']:.6g}]  median {r['median']:+.6f}  "
              f"trim10 {r['trimmed_mean_10']:+.6f}  p25 {r['p25']:+.4f}  "
              f"p75 {r['p75']:+.4f}  >0 {100*r['share_positive']:.2f}%  "
              f"depth_x {r['depth_x_mean']:.4f}  tok {r['n_tokens']:,}  "
              f"min {r['n_minutes']:,}")

    idx1 = np.where(grp == 0)[0]
    idx10 = np.where(grp == N_DECILES - 1)[0]

    schemes = {
        "token_minute": (d.tok, d.mn),
        "iid": (),
        "token_minute_wallet": (d.tok, d.mn, d.wal),
    }
    out = {}
    for name, cl in schemes.items():
        est = Estimator(d, cl, idx1, idx10, iid=(name == "iid"))
        lo, hi, draws = est.ci(np.random.default_rng(SEED), B)
        out[name] = {"point": est.point, "lo": lo, "hi": hi,
                     "width": hi - lo, "se": float(np.nanstd(draws, ddof=1))}
        print(f"\n{name:20} point {est.point:+.6f}  95% CI [{lo:+.6f}, {hi:+.6f}] "
              f" width {hi - lo:.6f}  se {out[name]['se']:.6f}")

    prim = out["token_minute"]
    inside = prim["lo"] > -BREAKEVEN and prim["hi"] < BREAKEVEN
    verdict = "ЗОГСОХ" if inside else "ҮРГЭЛЖЛҮҮЛЭХ"
    print(f"\nзогсох дүрэм: CI [{prim['lo']:+.6f}, {prim['hi']:+.6f}] "
          f"vs (-{BREAKEVEN}, +{BREAKEVEN})  ->  {verdict}")

    res = {"n_rows": d.n_rows, "n_tokens": int(len(np.unique(d.tok))),
           "n_minutes": int(len(np.unique(d.mn))), "deciles": rows,
           "ci": out, "breakeven": BREAKEVEN, "verdict": verdict,
           "B": B, "seed": SEED}
    p = config.RESULTS / "phase3b_screening.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, indent=2))
    print(f"\n-> {p}")


if __name__ == "__main__":
    main()
