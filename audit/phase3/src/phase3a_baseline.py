"""Phase 3a — baseline distribution and power analysis.  Spec §7 Phase 3a.

  python -m src.phase3a_baseline

Runs on the frozen local table `flow.burst` (§7 v1.3: Phase 3 never touches Dune).

Cell: the §4.1 primary cell — burst threshold 0.10x, τ = 12 slots, mayhem
excluded.  Every row in the table already clears 0.10x, since that is the burst
definition in the extract (`nf5 >= greatest(3.0, 0.10 * x)`); `qual_005` and
`qual_020` flag the §3d sensitivity thresholds and are not used here.

Deliberately NOT computed here (Phase 3b/3c): any OH_ratio decile split, any
correlation with OH_ratio, any hazard curve, any fwd_price_ret or x_at_plus
distribution.  Part A is the unconditional outcome distribution only.

The mean of fwd_net_flow is not reported (§6.4): the distribution is heavy
tailed on both sides, so median and a 10% trimmed mean are the location
statistics this study uses.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.load_clickhouse import client  # noqa: E402

TABLE = "flow.burst"
TAU = 12
Y = f"fwd_net_flow_{TAU}slot"

# --- §7 kill criterion (ii) reference conditions -----------------------------
X_REF = 50.0       # SOL, reference curve depth
Q_REF = 1.0        # SOL, own order size
FEES = 0.025       # 95bp pump.fun + 30bp creator, both sides (§1.1, §5)
L2_SLOTS = 2.5     # L2 = 1000ms at 400ms/slot (§5)

# --- power ------------------------------------------------------------------
ALPHA_Z = 1.959964    # two-sided 5%
POWER_Z = 0.841621    # 80%
MDE_MULT = ALPHA_Z + POWER_Z          # 2.8016
N_ASSIGNMENTS = 8
N_BOOT_PER_ASSIGNMENT = 250
SEED = 20260819


@dataclass
class Data:
    y: np.ndarray          # fwd_net_flow_12slot, SOL, sorted ascending
    token: np.ndarray      # token cluster id, in y's sorted order
    minute: np.ndarray     # minute cluster id, in y's sorted order
    v_lat2: np.ndarray     # unsorted; only medians are taken from these
    v_lat3: np.ndarray
    n_tokens: int
    n_minutes: int
    tokens_per: np.ndarray   # bursts per token
    minutes_per: np.ndarray  # bursts per minute


def fetch() -> Data:
    """Pull the primary cell.  Timestamps are parsed with an explicit 'UTC'.

    The server runs in Asia/Ulaanbaatar, so a bare parseDateTimeBestEffort would
    shift these UTC strings by +8h and put bursts in the wrong minute bucket
    (docs/phase0_clickhouse_load.md).
    """
    ch = client()
    rows = ch.query(
        f"SELECT {Y}, token_mint, "
        f"       toUnixTimestamp(toStartOfMinute("
        f"           parseDateTimeBestEffort(block_time, 'UTC'))) AS minute_utc, "
        f"       v_latency_2slot, v_latency_3slot "
        f"FROM {TABLE} WHERE NOT mayhem"
    ).result_columns

    y = np.asarray(rows[0], dtype=np.float64)
    token_raw = np.asarray(rows[1])
    minute_raw = np.asarray(rows[2], dtype=np.int64)
    v2 = np.asarray(rows[3], dtype=np.float64)
    v3 = np.asarray(rows[4], dtype=np.float64)

    order = np.argsort(y, kind="stable")
    _, token = np.unique(token_raw, return_inverse=True)
    _, minute = np.unique(minute_raw, return_inverse=True)

    return Data(
        y=y[order], token=token[order], minute=minute[order],
        v_lat2=v2, v_lat3=v3,
        n_tokens=int(token.max()) + 1, n_minutes=int(minute.max()) + 1,
        tokens_per=np.bincount(token), minutes_per=np.bincount(minute),
    )


# --- A: unconditional distribution ------------------------------------------

def trimmed_mean(sorted_y: np.ndarray, frac: float = 0.10) -> float:
    k = int(round(len(sorted_y) * frac))
    return float(sorted_y[k:len(sorted_y) - k].mean())


def part_a(d: Data) -> dict:
    y = d.y                       # already sorted
    qs = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    out = {"n": len(y),
           "median": float(np.median(y)),
           "trimmed_mean_10pct": trimmed_mean(y),
           "min": float(y[0]), "max": float(y[-1]),
           "share_positive": float((y > 0).mean())}
    for q in qs:
        out[f"p{q}"] = float(np.percentile(y, q))
    return out


# --- B: cluster counts ------------------------------------------------------

def part_b(d: Data) -> dict:
    return {
        "distinct_tokens": d.n_tokens,
        "distinct_minutes": d.n_minutes,
        "bursts_per_token_median": float(np.median(d.tokens_per)),
        "bursts_per_token_p90": float(np.percentile(d.tokens_per, 90)),
        "bursts_per_token_max": int(d.tokens_per.max()),
        "bursts_per_minute_median": float(np.median(d.minutes_per)),
        "bursts_per_minute_p90": float(np.percentile(d.minutes_per, 90)),
        "bursts_per_minute_max": int(d.minutes_per.max()),
    }


# --- C: two-way cluster bootstrap -------------------------------------------

def _weighted_median(sorted_y: np.ndarray, w: np.ndarray) -> float:
    """Median of `sorted_y` under non-negative weights `w` (same order)."""
    total = w.sum()
    if total <= 0:
        return np.nan
    cum = np.cumsum(w)
    return float(sorted_y[np.searchsorted(cum, total / 2.0, side="left")])


def bootstrap_se(d: Data, token_level_deciles: bool, rng: np.random.Generator
                 ) -> tuple[float, list[float]]:
    """SE of median(d10) − median(d1) under H0, by pigeonhole bootstrap.

    Owen's (2007) pigeonhole bootstrap for two-way CROSSED clusters: resample
    token clusters with replacement AND minute clusters with replacement, and
    weight each row by the product of its two multiplicities.  A plain i.i.d.
    bootstrap over rows is not valid here — bursts repeat within a token and pile
    up within a minute, and resampling rows would treat both as independent.

    H0 is "the sorting variable carries no information", so decile membership is
    assigned at random and the outcome is left untouched.  The assignment is
    drawn once per design and held fixed while the clusters are resampled, which
    mirrors the real estimator (deciles fixed by OH_ratio, sampling noise from
    the data).  Two assignment schemes bracket the answer — see the report.
    """
    ses: list[float] = []
    for _ in range(N_ASSIGNMENTS):
        if token_level_deciles:
            u_tok = rng.random(d.n_tokens)
            u = u_tok[d.token]
        else:
            u = rng.random(len(d.y))
        in_d1 = u < 0.10
        in_d10 = u >= 0.90

        deltas = np.empty(N_BOOT_PER_ASSIGNMENT)
        for b in range(N_BOOT_PER_ASSIGNMENT):
            w_tok = np.bincount(rng.integers(0, d.n_tokens, d.n_tokens),
                                minlength=d.n_tokens).astype(np.float64)
            w_min = np.bincount(rng.integers(0, d.n_minutes, d.n_minutes),
                                minlength=d.n_minutes).astype(np.float64)
            w = w_tok[d.token] * w_min[d.minute]
            deltas[b] = (_weighted_median(d.y, np.where(in_d10, w, 0.0))
                         - _weighted_median(d.y, np.where(in_d1, w, 0.0)))
        ses.append(float(np.nanstd(deltas, ddof=1)))
    return float(np.mean(ses)), ses


def economic_threshold(d: Data) -> dict:
    """BE at the §7 reference point, and the ΔV that would just clear it.

    §7 (ii) states the test directly: the price move implied by decile 10's
    median fwd_net_flow, `(1 + ΔV/x)² − 1`, must exceed BE.  Inverting,
    ΔV_required = x·(√(1+BE) − 1).

    V is the flow that lands during L2 latency.  L2 is 1000ms = 2.5 slots, and
    the extract carries whole-slot windows either side of it, so V is
    interpolated per row between v_latency_2slot and v_latency_3slot before the
    median is taken.  Both endpoints are reported so the interpolation's weight
    is visible rather than hidden.
    """
    v_interp = d.v_lat2 + (L2_SLOTS - 2.0) * (d.v_lat3 - d.v_lat2)
    v = float(np.median(v_interp))
    be = (1 + v / X_REF) ** 2 * (1 + Q_REF / X_REF) ** 2 * (1 + FEES) - 1
    dv_req = X_REF * (np.sqrt(1 + be) - 1)
    return {
        "v_lat2_median": float(np.median(d.v_lat2)),
        "v_lat3_median": float(np.median(d.v_lat3)),
        "V_median_2p5slot": v,
        "V_p75": float(np.percentile(v_interp, 75)),
        "V_p90": float(np.percentile(v_interp, 90)),
        "V_p99": float(np.percentile(v_interp, 99)),
        "V_share_exactly_zero": float((v_interp == 0).mean()),
        "BE": float(be),
        "dV_required_sol": float(dv_req),
    }


def iid_reference_se(d: Data) -> float:
    """Analytic i.i.d. SE of the same statistic, for the design effect only.

    NOT used for inference -- an i.i.d. bootstrap is invalid here and is ruled
    out by the pre-registered method.  This is the textbook median SE,
    1 / (2 f(m) sqrt(n)), with the density at the median read off the sample, and
    it exists purely to show how much the two-way clustering inflates the answer.
    """
    n_dec = len(d.y) // 10
    m = float(np.median(d.y))
    h = float(np.percentile(d.y, 55) - np.percentile(d.y, 45))   # 0.10 mass
    f_m = 0.10 / h
    se_one = 1.0 / (2 * f_m * np.sqrt(n_dec))
    return float(np.sqrt(2) * se_one)


def main() -> None:
    rng = np.random.default_rng(SEED)
    d = fetch()

    a = part_a(d)
    b = part_b(d)
    econ = economic_threshold(d)

    se_row, ses_row = bootstrap_se(d, token_level_deciles=False, rng=rng)
    se_tok, ses_tok = bootstrap_se(d, token_level_deciles=True, rng=rng)
    mde_row, mde_tok = MDE_MULT * se_row, MDE_MULT * se_tok

    print("=== A. unconditional fwd_net_flow_12slot (SOL), mayhem excluded ===")
    for k in ["n", "median", "trimmed_mean_10pct", "p1", "p5", "p10", "p25",
              "p50", "p75", "p90", "p95", "p99", "min", "max", "share_positive"]:
        v = a[k]
        print(f"  {k:<20} {v:,.6f}" if isinstance(v, float) else f"  {k:<20} {v:,}")

    print("\n=== B. clusters ===")
    for k, v in b.items():
        print(f"  {k:<28} {v:,.2f}" if isinstance(v, float) else f"  {k:<28} {v:,}")

    print("\n=== C. power ===")
    print(f"  bootstrap: pigeonhole two-way (token x minute), "
          f"{N_ASSIGNMENTS} assignments x {N_BOOT_PER_ASSIGNMENT} replicates "
          f"= {N_ASSIGNMENTS * N_BOOT_PER_ASSIGNMENT:,}")
    print(f"  SE(d10-d1 median), row-level deciles    {se_row:.6f} SOL "
          f"(per-assignment {min(ses_row):.4f}-{max(ses_row):.4f})")
    print(f"  SE(d10-d1 median), token-level deciles  {se_tok:.6f} SOL "
          f"(per-assignment {min(ses_tok):.4f}-{max(ses_tok):.4f})")
    print(f"  MDE = {MDE_MULT:.4f} x SE   row {mde_row:.6f} SOL | token {mde_tok:.6f} SOL")
    for k, v in econ.items():
        print(f"  {k:<22} {v:,.6f}")
    se_iid = iid_reference_se(d)
    print(f"  [reference only, not inference] analytic i.i.d. SE {se_iid:.6f} SOL "
          f"-> design effect {(se_tok / se_iid) ** 2:.1f}x in variance")

    print("\n=== D. verdict ===")
    for name, mde in [("row-level", mde_row), ("token-level", mde_tok)]:
        ok = mde <= econ["dV_required_sol"]
        mult = (mde / econ["dV_required_sol"]) ** 2
        from math import erf, sqrt as _sqrt
        z = econ["dV_required_sol"] / (mde / MDE_MULT) - ALPHA_Z
        power = 0.5 * (1 + erf(z / _sqrt(2)))
        print(f"  {name:<12} MDE {mde:.4f} vs required dV {econ['dV_required_sol']:.4f} "
              f"({100 * mde / econ['dV_required_sol']:.1f}% of it) "
              f"-> power at the threshold {power * 100:.2f}%; >= 80%: {'YES' if ok else 'NO'}"
              + ("" if ok else f"; needs {mult:.1f}x the clusters"))


if __name__ == "__main__":
    main()
