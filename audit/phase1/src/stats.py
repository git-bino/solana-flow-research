"""Reporting statistics — spec §6.4.

Fat tails everywhere in this data, so a bare mean is forbidden by the spec.  Any
distribution reported anywhere in this project goes through `describe`, which
returns median, 10% trimmed mean and a bootstrap 95% CI together.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class Summary:
    n: int
    median: float
    trimmed_mean_10pct: float
    ci_lo: float
    ci_hi: float
    p01: float
    p50: float
    p90: float
    p99: float
    p999: float
    maximum: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)

    def line(self, unit: str = "") -> str:
        u = f" {unit}" if unit else ""
        return (
            f"n={self.n:,}  median={self.median:.6g}{u}  "
            f"trimmed10%={self.trimmed_mean_10pct:.6g}{u}  "
            f"bootstrap 95% CI [{self.ci_lo:.6g}, {self.ci_hi:.6g}]{u}"
        )


def trimmed_mean(values: np.ndarray, proportion: float = 0.10) -> float:
    """Symmetric trimmed mean: drop `proportion` from each tail."""
    if values.size == 0:
        return float("nan")
    ordered = np.sort(values)
    cut = int(np.floor(values.size * proportion))
    kept = ordered[cut: values.size - cut] if values.size - 2 * cut > 0 else ordered
    return float(kept.mean())


def bootstrap_ci(
    values: np.ndarray,
    statistic=np.median,
    iterations: int = 2_000,
    alpha: float = 0.05,
    seed: int = 20260817,
) -> tuple[float, float]:
    """Percentile bootstrap CI of `statistic`.

    Note for later phases: this is an *i.i.d.* bootstrap, valid only for the
    Phase 0 error distributions it is used on here.  Anything reported per burst
    or per token must instead resample clusters (token and minute, spec §6.3).
    """
    if values.size == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, values.size, size=(iterations, values.size))
    stats = statistic(values[idx], axis=1)
    lo, hi = np.quantile(stats, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def describe(values: Sequence[float] | np.ndarray, iterations: int = 2_000) -> Summary:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        nan = float("nan")
        return Summary(0, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan)
    lo, hi = bootstrap_ci(arr, iterations=iterations)
    q = np.quantile(arr, [0.01, 0.50, 0.90, 0.99, 0.999])
    return Summary(
        n=int(arr.size),
        median=float(np.median(arr)),
        trimmed_mean_10pct=trimmed_mean(arr),
        ci_lo=lo,
        ci_hi=hi,
        p01=float(q[0]),
        p50=float(q[1]),
        p90=float(q[2]),
        p99=float(q[3]),
        p999=float(q[4]),
        maximum=float(arr.max()),
    )


def quantile_table(values: Sequence[float] | np.ndarray,
                   probs: Sequence[float] = (0.5, 0.9, 0.99, 0.999, 0.9999, 1.0)) -> list[tuple[str, float]]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return []
    return [(f"p{p * 100:g}", float(np.quantile(arr, p))) for p in probs]
