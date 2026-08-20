"""Recover per-slot net flow from the exported nf3 trajectory, and rebuild the label.

  python -m src.reconstruct_label        # runs the flow.burst pass

The extract carries `nf3_traj_75_incl_pre[a]`, a 3-slot rolling sum centred so
that index `a` covers slots `s+a-2 … s+a`, plus `nf3_excl_pre_1` and
`nf3_excl_pre_2`, which are the forward-only parts at a = 1 and a = 2.  Writing
`f(a)` for the net flow in slot `s+a`:

    nf3(1) = f(-1) + f(0) + f(1)          excl_1 = f(1)
    nf3(2) = f( 0) + f(1) + f(2)          excl_2 = f(1) + f(2)
    nf3(a) = f(a-2) + f(a-1) + f(a)

so the first three slots come straight out,

    f(1) = excl_1
    f(2) = excl_2 − excl_1
    f(3) = nf3(3) − excl_2

and everything after them follows from differencing the rolling sum, since
nf3(a) − nf3(a−1) = f(a) − f(a−3):

    f(a) = nf3(a) − nf3(a−1) + f(a−3),    a ≥ 4

That recursion is exact in real arithmetic.  In float64 it is a chain of
additions with no damping, so error accumulates; `measure_error_growth` reports
how much, and the label the study actually uses only needs a ≤ 12.

Nothing here touches OH_ratio, deciles, hazard or any Phase 3b question: this is
label arithmetic and the size of one bias, nothing else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TAU = 12
TRAJ_LEN = 75


def trajectory_from_slot_flows(flows: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Forward direction, for testing the inverse.

    `flows` is shaped (rows, 77): columns 0 and 1 are f(−1) and f(0), then
    f(1) … f(75).  Returns (nf3, excl_1, excl_2) exactly as the extract emits them.
    """
    n = flows.shape[0]
    nf3 = np.empty((n, TRAJ_LEN), dtype=np.float64)
    for a in range(1, TRAJ_LEN + 1):
        nf3[:, a - 1] = flows[:, a - 1] + flows[:, a] + flows[:, a + 1]
    return nf3, flows[:, 2].copy(), flows[:, 2] + flows[:, 3]


def reconstruct_slot_flows(nf3: np.ndarray, excl_1: np.ndarray, excl_2: np.ndarray,
                           upto: int = TAU) -> np.ndarray:
    """Per-slot net flow f(1) … f(upto), one row per burst.

    `nf3` may be sliced to `upto` columns; nothing past that is read.
    """
    if upto < 3:
        raise ValueError("the closed-form seed covers a = 1..3")
    n = nf3.shape[0]
    out = np.empty((n, upto), dtype=np.float64)
    out[:, 0] = excl_1
    out[:, 1] = excl_2 - excl_1
    out[:, 2] = nf3[:, 2] - excl_2
    for a in range(4, upto + 1):
        out[:, a - 1] = nf3[:, a - 1] - nf3[:, a - 2] + out[:, a - 4]
    return out


def forward_flow(nf3: np.ndarray, excl_1: np.ndarray, excl_2: np.ndarray,
                 tau: int = TAU) -> np.ndarray:
    """Σ f(1..tau) — the label under a window that opens after the trigger's slot."""
    return reconstruct_slot_flows(nf3, excl_1, excl_2, tau).sum(axis=1)


def measure_error_growth(rows: int = 20_000, seed: int = 20260819) -> dict:
    """Round-trip random slot flows through nf3 and back; report the drift.

    Amounts are drawn on the scale the real data lives on (tens of SOL, heavy
    tails) so the measured drift is comparable to the one in `flow.burst`.
    """
    rng = np.random.default_rng(seed)
    flows = rng.standard_t(df=3, size=(rows, TRAJ_LEN + 2)) * 5.0
    nf3, e1, e2 = trajectory_from_slot_flows(flows)
    got = reconstruct_slot_flows(nf3, e1, e2, TRAJ_LEN)
    err = np.abs(got - flows[:, 2:])
    per_a = err.max(axis=0)
    return {
        "rows": rows,
        "max_abs_error_overall": float(err.max()),
        "max_abs_error_at_a12": float(per_a[TAU - 1]),
        "max_abs_error_at_a75": float(per_a[TRAJ_LEN - 1]),
        "median_abs_error_at_a12": float(np.median(err[:, TAU - 1])),
        "median_abs_error_at_a75": float(np.median(err[:, TRAJ_LEN - 1])),
        "max_error_by_a": [float(v) for v in per_a],
        "label_max_abs_error": float(np.abs(got[:, :TAU].sum(axis=1)
                                            - flows[:, 2:2 + TAU].sum(axis=1)).max()),
    }


def main() -> None:
    from src.load_clickhouse import client

    ch = client()
    cols = ch.query(
        "SELECT arraySlice(nf3_traj_75_incl_pre, 1, 12), nf3_excl_pre_1, "
        "       nf3_excl_pre_2, fwd_net_flow_12slot "
        "FROM flow.burst"
    ).result_columns

    nf3 = np.asarray(cols[0], dtype=np.float64)
    e1 = np.asarray(cols[1], dtype=np.float64)
    e2 = np.asarray(cols[2], dtype=np.float64)
    current = np.asarray(cols[3], dtype=np.float64)

    corrected = forward_flow(nf3, e1, e2, TAU)
    diff = current - corrected
    finite = np.isfinite(corrected)

    print(f"rows                        {len(current):,}")
    print(f"non-reconstructable rows    {int((~finite).sum()):,}")
    print(f"diff == 0 exactly           {float((diff == 0).mean()) * 100:.4f}%")
    for name, arr in [("|diff|", np.abs(diff))]:
        for q in (50, 90, 99, 100):
            print(f"{name} p{q:<24} {np.percentile(arr, q):.9f}")
    nz = np.abs(corrected) > 0
    ratio = np.abs(diff[nz]) / np.abs(corrected[nz])
    print(f"|diff|/|corrected| p50      {np.percentile(ratio, 50):.9f}")
    print(f"|diff|/|corrected| p90      {np.percentile(ratio, 90):.9f}")
    print("\nerror growth (synthetic round trip):")
    for k, v in measure_error_growth().items():
        if k != "max_error_by_a":
            print(f"  {k:<28} {v}")


if __name__ == "__main__":
    main()
