"""Reference implementation of f1–f9 and the §4.2 forward labels — spec §3, §4.

Companion to `src.oh_reference` (which covers §1.2's OH family).  Together they
are the Python side that `sql/extract_schema_probe.sql` is checked against.

Deliberate design choice: every function takes the **whole** event list plus an
index, not a pre-truncated prefix.  Truncating first would make temporal leakage
structurally impossible and the leakage tests vacuous — they would pass on code
that cannot fail.  Restricting to `block_time ≤ t` is therefore something each
function does explicitly, and `tests/test_leakage.py` verifies it by corrupting
the future and demanding the answer not move.

Window convention: every trailing window is **(s − w, s]**, half-open below.
That is the convention spec v1.2 states for the flows and for nf3.  Note that
`sql/extract_schema_probe.sql` uses `RANGE BETWEEN w PRECEDING AND CURRENT ROW`
for f3, f8 and f9, which is **[s − w, s]** and so one slot wider; the parity
tests measure that difference rather than hiding it.
"""

from __future__ import annotations

from decimal import Decimal, getcontext
from statistics import pstdev

from src.oh_reference import Event, LAMPORTS

getcontext().prec = 60

ROUND_LAMPORTS = {100_000_000, 500_000_000, 1_000_000_000}   # 0.1 / 0.5 / 1.0 SOL


def _trailing(events: list[Event], i: int, window_slots: int,
              inclusive_lower: bool = False) -> list[Event]:
    """Events at or before i whose slot lies in the trailing window.

    `inclusive_lower=False` gives (s − w, s]; True gives [s − w, s], which is what
    the SQL's `RANGE BETWEEN w PRECEDING AND CURRENT ROW` produces.
    """
    s = events[i].slot
    lo = s - window_slots
    return [e for e in events[: i + 1] if (e.slot >= lo if inclusive_lower else e.slot > lo)]


def _forward(events: list[Event], i: int, window_slots: int) -> list[Event]:
    """Events strictly after i whose slot lies in [s + 1, s + w] — a label window."""
    s = events[i].slot
    return [e for e in events[i + 1:] if s < e.slot <= s + window_slots]


def net_flow(events: list[Event], i: int, window_slots: int) -> Decimal:
    """f1 — trailing (buy SOL − sell SOL) over (s − w, s].  spec §3 f1."""
    total = sum(e.signed_lam for e in _trailing(events, i, window_slots))
    return Decimal(total) / LAMPORTS


def accel(events: list[Event], i: int) -> Decimal | None:
    """f2 — net_flow_5slot / (net_flow_25slot / 5).  spec §3 f2."""
    denom = net_flow(events, i, 25) / 5
    return None if denom == 0 else net_flow(events, i, 5) / denom


def n_buyers(events: list[Event], i: int, window_slots: int = 12,
             inclusive_lower: bool = False) -> int:
    """f3 — distinct buying wallets in the trailing window.  spec §3 f3."""
    return len({e.wallet for e in _trailing(events, i, window_slots, inclusive_lower)
                if e.is_buy})


def depth_x(events: list[Event], i: int) -> Decimal:
    """f4 — current x, read straight off the row.  spec §3 f4, §2.3."""
    return Decimal(events[i].vsol) / LAMPORTS


def curve_progress(events: list[Event], i: int) -> Decimal:
    """f5 — (x − 30) / 85.  spec §3 f5."""
    return (depth_x(events, i) - 30) / 85


def size_cv(events: list[Event], i: int, window_slots: int = 25,
            inclusive_lower: bool = False) -> Decimal | None:
    """f8 — coefficient of variation of trade size over the trailing window.  §3 f8."""
    sizes = [float(e.lam) / 1e9 for e in _trailing(events, i, window_slots, inclusive_lower)]
    if not sizes:
        return None
    mean = sum(sizes) / len(sizes)
    if mean == 0:
        return None
    return Decimal(repr(pstdev(sizes) / mean))


def round_frac(events: list[Event], i: int, window_slots: int = 25,
               inclusive_lower: bool = False) -> Decimal | None:
    """f9 — share of trades at a round SOL size over the trailing window.  §3 f9."""
    window = _trailing(events, i, window_slots, inclusive_lower)
    if not window:
        return None
    hits = sum(1 for e in window if e.lam in ROUND_LAMPORTS)
    return Decimal(hits) / Decimal(len(window))


# --- §4.2 forward labels: these are SUPPOSED to see the future -------------

def fwd_net_flow(events: list[Event], i: int, window_slots: int) -> Decimal:
    """Next-τ net flow.  spec §4.2."""
    total = sum(e.signed_lam for e in _forward(events, i, window_slots))
    return Decimal(total) / LAMPORTS


def x_at_plus(events: list[Event], i: int, window_slots: int) -> Decimal:
    """x at the last event inside the forward window, else x now.  spec §4.2."""
    window = _forward(events, i, window_slots)
    return Decimal((window[-1] if window else events[i]).vsol) / LAMPORTS


def fwd_price_ret(events: list[Event], i: int, window_slots: int) -> Decimal:
    """P(t+τ)/P(t) − 1.  P ∝ x², so the ratio is (x_after / x_now)² − 1.  §4.2."""
    now = depth_x(events, i)
    return (x_at_plus(events, i, window_slots) / now) ** 2 - 1


#: Everything a feature must be blind to the future for (spec §3, §6.1).
CAUSAL_FEATURES = {
    "net_flow_5slot": lambda ev, i: net_flow(ev, i, 5),
    "net_flow_12slot": lambda ev, i: net_flow(ev, i, 12),
    "net_flow_25slot": lambda ev, i: net_flow(ev, i, 25),
    "accel": accel,
    "n_buyers_12slot": lambda ev, i: n_buyers(ev, i, 12),
    "depth_x": depth_x,
    "curve_progress": curve_progress,
    "size_cv_25slot": lambda ev, i: size_cv(ev, i, 25),
    "round_frac_25slot": lambda ev, i: round_frac(ev, i, 25),
}

#: Everything that must move when the future changes (spec §4.2, §4.3).
FORWARD_LABELS = {
    "fwd_net_flow_5slot": lambda ev, i: fwd_net_flow(ev, i, 5),
    "fwd_net_flow_12slot": lambda ev, i: fwd_net_flow(ev, i, 12),
    "fwd_net_flow_37slot": lambda ev, i: fwd_net_flow(ev, i, 37),
    "fwd_price_ret_12slot": lambda ev, i: fwd_price_ret(ev, i, 12),
    "x_at_plus12": lambda ev, i: x_at_plus(ev, i, 12),
}
