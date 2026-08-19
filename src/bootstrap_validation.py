"""Does the 3b confidence interval actually cover 95%, and does it deliver 80% power?

  python -m src.bootstrap_validation [section]

Audit finding 6 (decisions.md, 2026-08-19).  Owen's pigeonhole bootstrap is
justified for means and linearised statistics under crossed random effects; it
does not carry to a MEDIAN by theorem.  Phase 3a also averaged eight per-design
SEs of 250 replicates each, which is not the sampling variance of the estimator
under a fixed sorting variable.  So the procedure is checked by simulation
instead of by citation.

Source: `flow.burst`, mayhem excluded, 616,668 rows.  Timestamps are parsed with
an explicit 'UTC' — the server runs in Asia/Ulaanbaatar.

THE PROHIBITION: the real `OH_ratio` is never read.  Deciles here are assigned at
random, which is what makes this a calibration study rather than a preview of
Phase 3b.

Exactness note on the resampling.  A bootstrap replicate needs multiplicities for
every cluster, but only the clusters appearing in the two decile groups can move
the statistic.  Drawing multiplicities for those clusters alone is EXACT, not an
approximation: under Multinomial(n, uniform over N cells), the counts restricted
to a subset S have the same law as "draw k ~ Binomial(n, |S|/N), then spread k
draws uniformly over S".  `_restricted_multiplicities` does exactly that, and
`compare_restricted_to_naive` checks it against the naive full-width draw.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

Z95 = 1.959964

#: Simulation replicates per configuration.  The brief allows 200 when a
#: configuration would otherwise run past ten minutes; measured at 3.73 ms per
#: bootstrap replicate before optimisation, every configuration would have.
N_SIM = 200
#: Bootstrap replicates inside each simulation, except in the section D sweep.
N_BOOT = 1000
SEED = 20260819


@dataclass
class Data:
    y: np.ndarray
    tok: np.ndarray
    mn: np.ndarray
    wal: np.ndarray
    blk5: np.ndarray          # 5-minute block id
    n_rows: int


def load(cache: Path | None = None) -> Data:
    """Pull the primary cell once and cache it; the CI study re-reads it often."""
    cache = cache or (Path(__file__).resolve().parent.parent
                      / "data" / "cache" / "bootstrap_cell.npz")
    if cache.exists():
        z = np.load(cache)
        return Data(z["y"], z["tok"], z["mn"], z["wal"], z["blk5"], len(z["y"]))

    from src.load_clickhouse import client
    cols = client().query(
        "SELECT fwd_net_flow_12slot, token_mint, "
        "       toUnixTimestamp(toStartOfMinute("
        "           parseDateTimeBestEffort(block_time, 'UTC'))) AS minute_utc, "
        "       trigger_wallet "
        "FROM flow.burst WHERE NOT mayhem"
    ).result_columns
    y = np.asarray(cols[0], dtype=np.float64)
    _, tok = np.unique(np.asarray(cols[1]), return_inverse=True)
    minute_unix = np.asarray(cols[2], dtype=np.int64)
    _, mn = np.unique(minute_unix, return_inverse=True)
    _, wal = np.unique(np.asarray(cols[3]), return_inverse=True)
    _, blk5 = np.unique(minute_unix // 300, return_inverse=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, y=y, tok=tok, mn=mn, wal=wal, blk5=blk5)
    return Data(y, tok, mn, wal, blk5, len(y))


def _restricted_multiplicities(rng, n_draws: int, n_cells: int, n_needed: int
                               ) -> np.ndarray:
    """Multiplicities for `n_needed` of `n_cells` cells under Multinomial(n_draws, uniform).

    Exact: the restriction of a multinomial to a subset of cells is itself
    "how many draws land in the subset" times "uniform spread within it".
    """
    k = int(rng.binomial(n_draws, n_needed / n_cells))
    if k == 0:
        return np.zeros(n_needed, dtype=np.float64)
    return np.bincount(rng.integers(0, n_needed, k),
                       minlength=n_needed).astype(np.float64)


class Estimator:
    """median(d10) − median(d1) with a resampling CI, for one fixed assignment."""

    def __init__(self, d: Data, cluster_cols: tuple[np.ndarray, ...],
                 idx1: np.ndarray, idx10: np.ndarray, iid: bool = False):
        self.iid = iid
        self.n_rows = d.n_rows
        # sort each group once; the weighted median is then a cumsum + searchsorted
        self.o1 = idx1[np.argsort(d.y[idx1], kind="stable")]
        self.o10 = idx10[np.argsort(d.y[idx10], kind="stable")]
        self.y1, self.y10 = d.y[self.o1], d.y[self.o10]
        self.point = float(np.median(d.y[idx10]) - np.median(d.y[idx1]))

        if iid:
            used = np.concatenate([self.o1, self.o10])
            self.n_cells = [d.n_rows]
            self.compact = [(np.arange(len(self.o1)),
                             np.arange(len(self.o1), len(used)))]
            self.n_needed = [len(used)]
        else:
            self.n_cells, self.compact, self.n_needed = [], [], []
            for col in cluster_cols:
                both = np.concatenate([col[self.o1], col[self.o10]])
                uniq, inv = np.unique(both, return_inverse=True)
                self.n_cells.append(int(col.max()) + 1)
                self.n_needed.append(len(uniq))
                self.compact.append((inv[:len(self.o1)], inv[len(self.o1):]))

    def _weights(self, rng):
        w1 = np.ones(len(self.o1))
        w10 = np.ones(len(self.o10))
        for n_cells, n_needed, (c1, c10) in zip(self.n_cells, self.n_needed,
                                                self.compact):
            m = _restricted_multiplicities(rng, self.n_rows if self.iid else n_cells,
                                           n_cells, n_needed)
            w1 = w1 * m[c1]
            w10 = w10 * m[c10]
        return w1, w10

    @staticmethod
    def _wmedian(y_sorted, w):
        total = w.sum()
        if total <= 0:
            return np.nan
        return y_sorted[np.searchsorted(np.cumsum(w), total / 2.0, side="left")]

    def ci(self, rng, n_boot: int) -> tuple[float, float, np.ndarray]:
        """Percentile CI.  Returns (lo, hi, the replicate draws)."""
        draws = np.empty(n_boot)
        for b in range(n_boot):
            w1, w10 = self._weights(rng)
            draws[b] = self._wmedian(self.y10, w10) - self._wmedian(self.y1, w1)
        lo, hi = np.nanpercentile(draws, [2.5, 97.5])
        return float(lo), float(hi), draws


def _assign(rng, n: int, tok: np.ndarray | None = None,
            level: str = "row") -> tuple[np.ndarray, np.ndarray]:
    """Random decile assignment.  `OH_ratio` is never consulted (the prohibition).

    `level="row"` draws independently per row, which is what section A specifies.
    `level="token"` draws once per token and gives every burst of that token the
    same decile.

    THIS IS CLAUDE CODE'S DECISION: the token level was added after the row-level
    run returned 100% coverage.  Under row-level assignment a cluster-wide shock
    lands on both decile groups at once and cancels in their difference, so a
    cluster bootstrap is bound to look conservative — the calibration question is
    only sharp when the grouping is aligned with the clusters, which is how a
    real sorting variable behaves.  The assignment stays random, so nothing about
    Phase 3b is previewed.
    """
    if level == "row":
        u = rng.random(n)
    elif level == "token":
        u = rng.random(int(tok.max()) + 1)[tok]
    else:
        raise ValueError(level)
    return np.where(u < 0.10)[0], np.where(u >= 0.90)[0]


def _clusters(d: Data, scheme: str) -> tuple[np.ndarray, ...]:
    if scheme == "token_minute":
        return (d.tok, d.mn)
    if scheme == "token_block5":
        return (d.tok, d.blk5)
    if scheme == "token_minute_wallet":
        return (d.tok, d.mn, d.wal)
    if scheme == "iid":
        return ()
    raise ValueError(scheme)


def run_config(d: Data, scheme: str, delta: float, n_sim: int, n_boot: int,
               seed: int) -> dict:
    """One configuration: n_sim random assignments, each with its own CI.

    `delta` is added to the outcome of every row assigned to decile 10, so the
    true effect is exactly `delta` by construction.
    """
    rng = np.random.default_rng(seed)
    covers = detects = 0
    widths, points = [], []
    t0 = time.time()
    for _ in range(n_sim):
        idx1, idx10 = _assign(rng, d.n_rows)
        dd = d
        if delta != 0.0:
            y = d.y.copy()
            y[idx10] += delta
            dd = Data(y, d.tok, d.mn, d.wal, d.blk5, d.n_rows)
        est = Estimator(dd, _clusters(dd, scheme), idx1, idx10,
                        iid=(scheme == "iid"))
        lo, hi, _ = est.ci(rng, n_boot)
        covers += (lo <= delta <= hi)
        detects += not (lo <= 0.0 <= hi)
        widths.append(hi - lo)
        points.append(est.point)
    cov = covers / n_sim
    pw = detects / n_sim
    return {
        "scheme": scheme, "delta": delta, "n_sim": n_sim, "n_boot": n_boot,
        "coverage": cov,
        "coverage_mc_se": float(np.sqrt(cov * (1 - cov) / n_sim)),
        "power": pw,
        "power_mc_se": float(np.sqrt(pw * (1 - pw) / n_sim)),
        "ci_width_median": float(np.median(widths)),
        "point_mean": float(np.mean(points)),
        "seconds": time.time() - t0,
    }


def compare_restricted_to_naive(d: Data, n_boot: int = 400, seed: int = 7) -> dict:
    """Check the restricted draw against the naive full-width one.

    Both are run on the same assignment.  They are different random sequences, so
    the draws cannot match pointwise; what must match is the spread.
    """
    rng = np.random.default_rng(seed)
    idx1, idx10 = _assign(rng, d.n_rows)
    est = Estimator(d, (d.tok, d.mn), idx1, idx10)
    _, _, fast = est.ci(np.random.default_rng(seed + 1), n_boot)

    o1, o10 = est.o1, est.o10
    y1, y10 = d.y[o1], d.y[o10]
    ord1, ord10 = np.argsort(y1, kind="stable"), np.argsort(y10, kind="stable")
    y1s, y10s = y1[ord1], y10[ord10]
    t1, t10 = d.tok[o1][ord1], d.tok[o10][ord10]
    m1, m10 = d.mn[o1][ord1], d.mn[o10][ord10]
    n_tok, n_mn = int(d.tok.max()) + 1, int(d.mn.max()) + 1
    rng2 = np.random.default_rng(seed + 2)
    slow = np.empty(n_boot)
    for b in range(n_boot):
        wt = np.bincount(rng2.integers(0, n_tok, n_tok), minlength=n_tok).astype(float)
        wm = np.bincount(rng2.integers(0, n_mn, n_mn), minlength=n_mn).astype(float)
        slow[b] = (Estimator._wmedian(y10s, wt[t10] * wm[m10])
                   - Estimator._wmedian(y1s, wt[t1] * wm[m1]))
    return {
        "n_boot": n_boot,
        "sd_restricted": float(np.nanstd(fast, ddof=1)),
        "sd_naive": float(np.nanstd(slow, ddof=1)),
        "ratio": float(np.nanstd(fast, ddof=1) / np.nanstd(slow, ddof=1)),
    }


# --- parallel driver ---------------------------------------------------------

def _one_sim(args) -> tuple[int, int, float, float]:
    """One simulation replicate: assign at random, plant `delta`, build the CI.

    A module-level function so it can be sent to a process pool.  Each worker
    seeds from (config seed, replicate index), so the whole study is
    reproducible and the replicates are independent.
    """
    scheme, delta, n_boot, seed, i, level = args
    d = load()
    rng = np.random.default_rng([seed, i])
    idx1, idx10 = _assign(rng, d.n_rows, d.tok, level)
    if delta != 0.0:
        y = d.y.copy()
        y[idx10] += delta
        d = Data(y, d.tok, d.mn, d.wal, d.blk5, d.n_rows)
    est = Estimator(d, _clusters(d, scheme), idx1, idx10, iid=(scheme == "iid"))
    lo, hi, _ = est.ci(rng, n_boot)
    return int(lo <= delta <= hi), int(not (lo <= 0.0 <= hi)), hi - lo, est.point


def run_config_parallel(scheme: str, delta: float, n_sim: int, n_boot: int,
                        seed: int, workers: int = 8, level: str = "row") -> dict:
    from multiprocessing import Pool
    t0 = time.time()
    args = [(scheme, delta, n_boot, seed, i, level) for i in range(n_sim)]
    with Pool(workers) as pool:
        out = pool.map(_one_sim, args, chunksize=1)
    cov = sum(o[0] for o in out) / n_sim
    pw = sum(o[1] for o in out) / n_sim
    return {
        "scheme": scheme, "delta": delta, "n_sim": n_sim, "n_boot": n_boot,
        "level": level,
        "coverage": cov,
        "coverage_mc_se": float(np.sqrt(cov * (1 - cov) / n_sim)),
        "power": pw,
        "power_mc_se": float(np.sqrt(pw * (1 - pw) / n_sim)),
        "ci_width_median": float(np.median([o[2] for o in out])),
        "point_sd": float(np.std([o[3] for o in out], ddof=1)),
        "point_mean": float(np.mean([o[3] for o in out])),
        "seconds": time.time() - t0,
    }
