"""`fwd_net_ret` — the §12.4 exit rules priced with the Phase 1 path arithmetic.

  python -m src.fwd_net_ret

This builds the machine and reports the UNCONDITIONAL baseline.  It does not
search: no deciles, no filters, no strategy.  Every parameter set evaluated here
is counted in test_log_atomic.md, because chunk 1 is the search sample and the
count feeds the next stage's multiplicity correction.

Where the numbers come from
---------------------------
`depth_x` is x at the signal -- what the trader can see at the trigger row.
`x_end_slot` is the reserve at the END of slot s, and it is the base the reserve
path actually follows: `x_end_slot + cumf[a]` reproduces the exported
`x_at_plus{5,12,37}` to float precision on all 126,089 rows, while
`depth_x + cumf[a]` misses on 72.3% of them.  The gap is same-slot trades landing
after the trigger, median 1.03 SOL, and it is large next to the 0.657 breakeven,
so BOTH conventions are computed and reported rather than one being chosen:

    obs    x2 = depth_x     + V + q + W     the spec's fill algebra taken literally
    true   x2 = x_end_slot  + V + q + W     the reserve the data actually follows

The entry fill is `depth_x + V` under both, because that is what §5 specifies and
what a trader can observe.  Which convention the study adopts is a research
decision and is left open.  `v_latency_{1,2,3,7,8}slot` is the flow that lands
during latency -- the SQL builds it as `RANGE BETWEEN 1 FOLLOWING AND L
FOLLOWING`, i.e. exactly the sum of per-slot flows over s+1..s+L, which is
checked here against the trajectory rather than assumed.

Per-slot net flow f(1..75) is recovered from `nf3_traj_75_incl_pre` with
`src.reconstruct_label.reconstruct_slot_flows`.  The post-entry flow the P&L
needs is then W = cumf[a_exit] - cumf[latency], and the reserve at any age is
x(a) = depth_x + V + q + (cumf[a] - cumf[latency]).  The exported
`x_at_plus{5,12,37}` are used only to MEASURE that reconstruction, not to drive
it: they exist at three ages and the exit can land on any of 75.

Exit rules (§12.4), all evaluated from a >= 3
---------------------------------------------
§3c measured that `nf3_traj_75_incl_pre[a]` covers slots s+a-2..s+a, so a = 1 and
a = 2 still contain the trigger's own slot s, and the hazard jumps 0.017643 ->
0.544678 at a = 3 when it leaves.  Starting the rules at a = 1 would therefore
read the trigger's own buy as "flow has not reversed".  **The rules start at
a = 3.**

    flow reversal   nf3(a) <= 0 on k consecutive ages, exit at the k-th
    age limit       the literal condition `a > A`, so the exit age is A + 1
    hard stop       price at a <= (1 - L) x the entry price

Entry price is the spec §5 fill, avg_price = x_eff (x_eff + q) / k with
x_eff = depth_x + V, and the price at age a is x(a)^2 / k.  So the stop fires
where x(a) <= sqrt((1 - L) x_eff (x_eff + q)).

A row where no rule fires by a = 75 is CENSORED: it is priced with a forced exit
at 75 and counted separately.  Rows are never dropped -- dropping them would be
survivorship.

Arithmetic
----------
`src.cost_model` is Decimal and exact; 2,160 parameter sets x 126,089 rows is
272 million evaluations, which Decimal cannot do in reasonable time.  The float64
vectorisation here is checked against the Decimal implementation in
tests/test_fwd_net_ret.py rather than trusted.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.cost_model import FEE_RATE, K_DEFAULT  # noqa: E402
from src.reconstruct_label import reconstruct_slot_flows  # noqa: E402

TRAJ = 75
FIRST_AGE = 3          # §3c: a = 1, 2 still contain the trigger's own slot
K = float(K_DEFAULT)
FEE = float(FEE_RATE)

K_CONSEC = (1, 2, 3)
A_LIMIT = (5, 12, 25, 37, 75)
L_STOP = (0.05, 0.10, 0.20, None)       # None = no hard stop
#: spec.md:567 and cost_model.Q_GRID both name four sizes.  The brief's grid
#: arithmetic assumed three; the documented grid is used and the count reported
#: accordingly (2,160, not 1,620).
Q_SIZES = (0.5, 1.0, 2.0, 5.0)
LATENCY = {"L1": 1, "L2": 3, "L3": 8}   # slots; L2 is 2.5 rounded up
PF = (0.0, 0.001, 0.01)


@dataclass
class Cell:
    traj: np.ndarray        # (n, 75) nf3
    f: np.ndarray           # (n, 75) per-slot net flow, f(1..75)
    cumf: np.ndarray        # (n, 76) cumulative, cumf[:, 0] = 0
    depth: np.ndarray
    xend: np.ndarray
    vlat: dict              # name -> (n,) observed flow during latency
    xplus: dict             # age -> (n,) exported reserve
    n: int


def load() -> Cell:
    from src.load_clickhouse_v2 import client
    cols = client().query(
        "SELECT nf3_traj_75_incl_pre, nf3_excl_pre_1, nf3_excl_pre_2, depth_x, "
        "       x_end_slot, "
        "       v_latency_1slot, v_latency_2slot, v_latency_3slot, "
        "       v_latency_7slot, v_latency_8slot, "
        "       x_at_plus5, x_at_plus12, x_at_plus37 "
        "FROM flow.burst_v2 WHERE NOT mayhem"
    ).result_columns
    traj = np.asarray([list(r) for r in cols[0]], dtype=np.float64)
    e1 = np.asarray(cols[1], dtype=np.float64)
    e2 = np.asarray(cols[2], dtype=np.float64)
    f = reconstruct_slot_flows(traj, e1, e2, TRAJ)
    cumf = np.concatenate([np.zeros((len(f), 1)), np.cumsum(f, axis=1)], axis=1)
    vlat = {f"v{n}": np.asarray(cols[5 + i], dtype=np.float64)
            for i, n in enumerate((1, 2, 3, 7, 8))}
    xplus = {a: np.asarray(cols[10 + i], dtype=np.float64)
             for i, a in enumerate((5, 12, 37))}
    return Cell(traj, f, cumf, np.asarray(cols[3], dtype=np.float64),
                np.asarray(cols[4], dtype=np.float64), vlat, xplus, len(traj))


def check_reconstruction(c: Cell) -> dict:
    """Two independent checks of the reconstructed flow, both measured."""
    out = {}
    for name, L in (("v1", 1), ("v2", 2), ("v3", 3), ("v7", 7), ("v8", 8)):
        got = c.cumf[:, L]
        want = c.vlat[name]
        den = np.maximum(np.maximum(np.abs(got), np.abs(want)), 1.0)
        rel = np.abs(got - want) / den
        out[f"latency_{L}slot"] = {"max_abs": float(np.max(np.abs(got - want))),
                                   "max_rel": float(rel.max()),
                                   "n_exceeding_1e-9": int((rel > 1e-9).sum())}
    for a, x in c.xplus.items():
        ok = np.isfinite(x)
        for nm, base in (("depth_x", c.depth), ("x_end_slot", c.xend)):
            recon = base + c.cumf[:, a]
            den = np.maximum(np.maximum(np.abs(recon[ok]), np.abs(x[ok])), 1.0)
            rel = np.abs(recon[ok] - x[ok]) / den
            out[f"x_at_plus{a}__{nm}"] = {
                "n": int(ok.sum()),
                "max_abs": float(np.max(np.abs(recon[ok] - x[ok]))),
                "max_rel": float(rel.max()),
                "n_exceeding_1e-9": int((rel > 1e-9).sum())}
    gap = c.xend - c.depth
    out["x_end_slot_minus_depth_x"] = {
        "n_equal": int((gap == 0).sum()), "share_equal": float((gap == 0).mean()),
        "abs_median": float(np.median(np.abs(gap))),
        "abs_p90": float(np.percentile(np.abs(gap), 90)),
        "abs_max": float(np.abs(gap).max())}
    return out


def first_true_age(mask: np.ndarray) -> np.ndarray:
    """First 1-indexed age where `mask` (n, 75) is True; 0 when never."""
    any_ = mask.any(axis=1)
    return np.where(any_, mask.argmax(axis=1) + 1, 0)


def flow_exit(traj: np.ndarray, k: int) -> np.ndarray:
    """Age at which nf3 <= 0 has held for k consecutive ages, counting from FIRST_AGE."""
    nonpos = traj <= 0
    nonpos[:, :FIRST_AGE - 1] = False
    if k == 1:
        run = nonpos
    else:
        run = nonpos.copy()
        for shift in range(1, k):
            run[:, shift:] &= nonpos[:, :-shift]
        run[:, :k - 1] = False
    return first_true_age(run)


def stop_exit(c: Cell, q: float, lat: int, L: float | None,
              base: str = "obs") -> np.ndarray:
    if L is None:
        return np.zeros(c.n, dtype=np.int64)
    x_eff = c.depth + c.cumf[:, lat]                       # §5 fill, observable
    entry_px_num = x_eff * (x_eff + q)                     # avg fill price x k
    thresh = np.sqrt(np.maximum((1.0 - L) * entry_px_num, 0.0))
    root = (c.depth if base == "obs" else c.xend) + c.cumf[:, lat]
    x_a = (root + q)[:, None] + (c.cumf[:, 1:] - c.cumf[:, lat][:, None])
    hit = x_a <= thresh[:, None]
    hit[:, :FIRST_AGE - 1] = False
    return first_true_age(hit)


def combine(*ages: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Earliest firing rule; 0 means "never fired".  Returns (exit_age, censored)."""
    stacked = np.stack(ages)
    stacked = np.where(stacked == 0, TRAJ + 1, stacked)
    first = stacked.min(axis=0)
    censored = first > TRAJ
    return np.where(censored, TRAJ, first), censored


def net_pnl_vec(x_obs, q, V, W, pf) -> np.ndarray:
    """Vectorised `cost_model.net_pnl`; checked against the Decimal version."""
    x1 = x_obs + V
    dy = K / x1 - K / (x1 + q)
    x2 = x1 + q + W
    out = dy * x2 * x2 / (K + dy * x2)
    return out * (1.0 - FEE) - q / (1.0 - FEE) - 2.0 * pf


def trimmed_mean(v: np.ndarray, frac: float = 0.10) -> float:
    v = np.sort(v)
    k = int(len(v) * frac)
    return float(v[k:len(v) - k].mean()) if len(v) - 2 * k > 0 else float("nan")


def run(c: Cell) -> list[dict]:
    flow_ex = {k: flow_exit(c.traj, k) for k in K_CONSEC}
    rows: list[dict] = []
    gap = c.xend - c.depth
    for base in ("obs", "true"):
        for lat_name, lat in LATENCY.items():
            V = c.cumf[:, lat]
            for q in Q_SIZES:
                stops = {L: stop_exit(c, q, lat, L, base) for L in L_STOP}
                for kc in K_CONSEC:
                    for A in A_LIMIT:
                        age_ex = np.full(c.n, A + 1 if A + 1 <= TRAJ else 0,
                                         dtype=np.int64)
                        for L in L_STOP:
                            a_exit, censored = combine(flow_ex[kc], age_ex, stops[L])
                            W = c.cumf[np.arange(c.n), a_exit] - V
                            if base == "true":
                                W = W + gap
                            y = net_pnl_vec(c.depth, q, V, W, 0.0)
                            for pf in PF:
                                y_pf = y - 2.0 * pf
                                rows.append({
                                    "base": base,
                                    "latency": lat_name, "lat_slots": lat, "q": q,
                                    "k": kc, "A": A, "L": L, "pf": pf,
                                    "n": c.n,
                                    "median": float(np.median(y_pf)),
                                    "trimmed_mean_10": trimmed_mean(y_pf),
                                    "p10": float(np.percentile(y_pf, 10)),
                                    "p25": float(np.percentile(y_pf, 25)),
                                    "p75": float(np.percentile(y_pf, 75)),
                                    "p90": float(np.percentile(y_pf, 90)),
                                    "share_positive": float((y_pf > 0).mean()),
                                    "a_exit_mean": float(a_exit.mean()),
                                    "a_exit_median": float(np.median(a_exit)),
                                    "censored_share": float(censored.mean()),
                                })
    return rows


def main() -> None:
    c = load()
    print(f"flow.burst_v2, NOT mayhem: {c.n:,} мөр")
    chk = check_reconstruction(c)
    for k, v in chk.items():
        if "max_rel" in v:
            print(f"  {k:24} max_rel {v['max_rel']:.3e}  "
                  f">1e-9: {v['n_exceeding_1e-9']:,}")
        else:
            print(f"  {k:24} тэнцүү {v['share_equal']*100:.4f}%  "
                  f"|зөрүү| median {v['abs_median']:.6f}  max {v['abs_max']:.6f}")

    # unconditional reference: the label with no exit rule at all
    ref12 = c.cumf[:, 12] - c.cumf[:, 0]
    print(f"\nгаралтын дүрэмгүй fwd_net_flow_12 (сэргээсэн): "
          f"p10 {np.percentile(ref12, 10):.6f}  median {np.median(ref12):.6f}")

    rows = run(c)
    print(f"\nпараметрийн багц: {len(rows):,}")
    for r in rows:
        r["ref_p10_fwd_net_flow_12"] = float(np.percentile(ref12, 10))
    out = {"n_rows": c.n, "n_param_sets": len(rows),
           "reconstruction_check": chk,
           "ref_fwd_net_flow_12": {"p10": float(np.percentile(ref12, 10)),
                                   "median": float(np.median(ref12))},
           "grid": {"k": K_CONSEC, "A": A_LIMIT, "L": L_STOP, "q": Q_SIZES,
                    "latency": LATENCY, "pf": PF, "first_age": FIRST_AGE},
           "rows": rows}
    p = config.RESULTS / "fwd_net_ret_baseline.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"-> {p}")


if __name__ == "__main__":
    main()
