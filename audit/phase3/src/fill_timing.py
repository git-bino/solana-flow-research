"""The fill-timing convention of the asymmetric-barrier analysis, in one place.

The analysis itself runs in SQL (`sql/holder_anchor.sql`,
`sql/asymmetric_barriers.sql`, `sql/asym_passage.sql`).  This module states the
convention those queries implement, so `tests/test_fill_timing.py` can lock it
against the defect class that killed the previous candidate:

    the old rule priced ENTRY on the trigger ROW's reserve but EXIT on the end of
    the trigger SLOT, so flow that landed after the trigger became post-entry
    profit.  Expectancy went +0.450435 -> -0.168718 once that was fixed, and
    134.73% of the old gross P&L was that gap.

THE CONVENTION HERE (both ends, identically):

    A signal is known only when the event that produced it has COMPLETED.  The
    earliest price anyone can transact at is therefore the reserve LEFT BY that
    event -- its post-trade reserve -- and the forward search starts strictly
    after it.

`virtual_sol_reserves` on pump.fun's TradeEvent is the POST-trade reserve.  That
is not assumed: `sql/phase0_kill_gate.sql` derives x_pre as
`if(is_buy, vsol - lam, vsol + lam)` and checks it equals exactly 30 SOL on every
token's first trade -- 74,733 / 74,733 matched (results/phase0_measurements.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ev:
    """One event.  `x` is the reserve AFTER this event, per the TradeEvent
    convention.  A transfer carries `x = None`: it moves units, not reserves."""
    seq: int
    x: float | None
    wallet: str | None = None
    d_units: float = 0.0


def holder_anchor(events: list[Ev], n_target: int) -> int | None:
    """Index of the first event at whose END the holder count reaches n_target.

    The event itself is COUNTED -- it is the event that made the count reach the
    target, so the condition is true only once it has completed.
    """
    bal: dict[str, float] = {}
    holders = 0
    for i, e in enumerate(events):
        if e.wallet is not None:
            before = bal.get(e.wallet, 0.0)
            after = before + e.d_units
            bal[e.wallet] = after
            if after > 0 >= before:
                holders += 1
            elif after <= 0 < before:
                holders -= 1
        if holders >= n_target:
            return i
    return None


def reserve_after(events: list[Ev], idx: int) -> float:
    """The reserve left by event `idx`.  A transfer does not move the reserve, so
    the last trade's post-reserve is carried forward."""
    for j in range(idx, -1, -1):
        if events[j].x is not None:
            return events[j].x
    raise ValueError("no reserve known at or before this event")


def entry_reserve(events: list[Ev], anchor_idx: int) -> float:
    """Entry is priced on the reserve the ANCHOR EVENT LEFT, never on the one it
    started from -- the anchor condition did not exist before it completed."""
    return reserve_after(events, anchor_idx)


def first_crossing(events: list[Ev], anchor_idx: int, level: float,
                   direction: int) -> int | None:
    """First event STRICTLY AFTER the anchor whose post-reserve crosses `level`."""
    for i in range(anchor_idx + 1, len(events)):
        x = events[i].x
        if x is None:
            continue
        if (direction > 0 and x >= level) or (direction < 0 and x <= level):
            return i
    return None


def exit_reserve(events: list[Ev], crossing_idx: int) -> float:
    """Exit is priced on the reserve the CROSSING EVENT LEFT -- symmetric with
    `entry_reserve`.  Using the pre-crossing reserve would be a one-event
    lookahead in the opposite direction."""
    return reserve_after(events, crossing_idx)


def gross_price_ratio(x_entry: float, x_exit: float) -> float:
    """P = x^2/k on a constant-product curve, so the gross price ratio is
    (x_exit / x_entry)^2."""
    return (x_exit / x_entry) ** 2
