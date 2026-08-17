"""Reference implementation of OH / OH_ratio / OH_conc — spec §1.2.

Deliberately independent of the Dune SQL in `sql/oh_prototype.sql`: this module
knows nothing about that query, reads raw events only, and is written the way
§1.2 is worded rather than the way the SQL is shaped.  Its purpose is to be the
thing the SQL is checked *against*, so any shared bug would have to be invented
twice.

Arithmetic is exact where §1.2 allows it: amounts stay integer base units
(lamports, token units) and the two ratios that are genuinely rational — cost
basis and spot price — are `Decimal` at 60 digits.  Reducing the formulas first
means each is a single division of integers:

    cb(w) = Σ buy_lamports / (Σ buy_units × 1000)         SOL per token
    P(t)  = vsol² / (x₀_lamports × y₀_units × 1000)       SOL per token

both from (lam/1e9)/(units/1e6) and (vsol/1e9)²/((x₀/1e9)(y₀/1e6)).  No
intermediate float appears anywhere.

Causality: state is advanced event by event in (slot, tx_index, ix_index) order
and OH is read off *after* applying the event at t, so it uses exactly the events
with key ≤ t (spec §6.1).  Sells never touch cost basis (§1.2).
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Iterable, Iterator

getcontext().prec = 60

THOUSAND = Decimal(1000)
TOKEN_UNITS = Decimal(10**6)
LAMPORTS = Decimal(10**9)

#: §4.1 (spec v1.2), in slots
BURST_WINDOW_SLOTS = 5
BURST_QUIET_SLOTS = 25
BURST_MIN_SOL = Decimal(3)
BURST_X_FRACTION = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class Event:
    mint: str
    slot: int
    tx_index: int
    ix_index: int
    wallet: str
    is_buy: bool
    lam: int            # sol_amount, lamports (NET of fee — verified §0.3)
    units: int          # token_amount, base units
    vsol: int           # virtual_sol_reserves after the trade, lamports
    x0_lam: int         # this token's createevent virtual_sol_reserves
    y0_units: int       # this token's createevent virtual_token_reserves

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.slot, self.tx_index, self.ix_index)

    @property
    def signed_lam(self) -> int:
        return self.lam if self.is_buy else -self.lam


@dataclass(slots=True)
class WalletState:
    """§1.2: cost basis is a buy-weighted average; selling does not change it."""

    buy_lam: int = 0
    buy_units: int = 0
    held_units: int = 0

    def apply(self, ev: Event) -> None:
        if ev.is_buy:
            self.buy_lam += ev.lam
            self.buy_units += ev.units
            self.held_units += ev.units
        else:
            self.held_units -= ev.units      # cost basis untouched

    def cost_basis(self) -> Decimal | None:
        """SOL per token, or None for a wallet that has only ever sold."""
        if self.buy_units == 0:
            return None
        return Decimal(self.buy_lam) / (Decimal(self.buy_units) * THOUSAND)


@dataclass(slots=True)
class TokenState:
    x0_lam: int
    y0_units: int
    wallets: dict[str, WalletState] = field(default_factory=dict)

    def apply(self, ev: Event) -> None:
        self.wallets.setdefault(ev.wallet, WalletState()).apply(ev)

    def spot_price(self, vsol: int) -> Decimal:
        return (Decimal(vsol) * Decimal(vsol)) / (
            Decimal(self.x0_lam) * Decimal(self.y0_units) * THOUSAND
        )

    def overhead(self, vsol: int) -> tuple[Decimal, Decimal, Decimal, int]:
        """OH, OH_ratio, OH_conc and the qualifying wallet count at this state."""
        price = self.spot_price(vsol)
        contributions: list[Decimal] = []
        for state in self.wallets.values():
            if state.held_units <= 0:
                continue
            cb = state.cost_basis()
            if cb is None or cb >= price:
                continue
            contributions.append(
                (Decimal(state.held_units) / TOKEN_UNITS) * (price - cb)
            )
        oh = sum(contributions, Decimal(0))
        x_sol = Decimal(vsol) / LAMPORTS
        oh_ratio = oh / x_sol
        if oh > 0:
            top3 = sum(sorted(contributions, reverse=True)[:3], Decimal(0))
            oh_conc = top3 / oh
        else:
            oh_conc = Decimal(0)
        return oh, oh_ratio, oh_conc, len(contributions)


def _burst_keys(events: list[Event]) -> list[int]:
    """Indices of events that open a burst — §4.1 in slots.

    net_flow_5slot(t) is the signed flow over slot ∈ (s−5, s] up to and including
    the event at t; the trailing deque holds exactly that window.  A qualifying
    event opens a burst when the previous qualifying event is more than 25 slots
    back (the same sessionisation the SQL uses, and the same one behind the
    published burst counts).
    """
    opened: list[int] = []
    window: deque[Event] = deque()
    running = 0
    last_qualifying_slot: int | None = None
    for i, ev in enumerate(events):
        window.append(ev)
        running += ev.signed_lam
        while window and window[0].slot <= ev.slot - BURST_WINDOW_SLOTS:
            running -= window.popleft().signed_lam
        net_sol = Decimal(running) / LAMPORTS
        x_sol = Decimal(ev.vsol) / LAMPORTS
        if net_sol >= max(BURST_MIN_SOL, BURST_X_FRACTION * x_sol):
            if last_qualifying_slot is None or ev.slot - last_qualifying_slot > BURST_QUIET_SLOTS:
                opened.append(i)
            last_qualifying_slot = ev.slot
    return opened


HAZARD_SLOTS = 75
NF3_WINDOW_SLOTS = 3


def _nf3_by_slot(events: list[Event]) -> dict[int, int]:
    """Per-slot net_flow_3slot in lamports: the value at the *last* event of each slot.

    Written independently of the SQL: a trailing deque over slot ∈ (s−3, s], and
    later writes to the same slot simply overwrite earlier ones, which is what
    "the value at that slot" means when a slot holds several trades.
    """
    out: dict[int, int] = {}
    window: deque[Event] = deque()
    running = 0
    for ev in events:
        window.append(ev)
        running += ev.signed_lam
        while window and window[0].slot <= ev.slot - NF3_WINDOW_SLOTS:
            running -= window.popleft().signed_lam
        out[ev.slot] = running
    return out


def _trajectory(nf3: dict[int, int], burst_slot: int) -> list[Decimal]:
    """§4.3 trajectory, slot-indexed: element a-1 is net_flow_3slot at slot+a.

    Exactly `HAZARD_SLOTS` long by construction; a slot with no event is 0, as
    specified.  Note that is the *specified* quantity, not the trailing window's
    mathematical value at an eventless slot, which would generally be non-zero.
    """
    return [
        Decimal(nf3.get(burst_slot + a, 0)) / LAMPORTS
        for a in range(1, HAZARD_SLOTS + 1)
    ]


def replay_token(events: Iterable[Event]) -> Iterator[dict]:
    """Yield one record per burst_start for a single token's event stream."""
    ordered = sorted(events, key=lambda e: e.key)
    if not ordered:
        return
    state = TokenState(ordered[0].x0_lam, ordered[0].y0_units)
    burst_at = set(_burst_keys(ordered))
    nf3 = _nf3_by_slot(ordered)
    for i, ev in enumerate(ordered):
        state.apply(ev)
        if i not in burst_at:
            continue
        oh, oh_ratio, oh_conc, n_wallets = state.overhead(ev.vsol)
        yield {
            "mint": ev.mint,
            "slot": ev.slot,
            "tx_index": ev.tx_index,
            "ix_index": ev.ix_index,
            "x_sol": Decimal(ev.vsol) / LAMPORTS,
            "price": state.spot_price(ev.vsol),
            "oh": oh,
            "oh_ratio": oh_ratio,
            "oh_conc": oh_conc,
            "n_wallets": n_wallets,
            "n_wallets_total": len(state.wallets),
            "nf3_traj_75": _trajectory(nf3, ev.slot),
        }


def replay(events: Iterable[Event]) -> list[dict]:
    by_token: dict[str, list[Event]] = {}
    for ev in events:
        by_token.setdefault(ev.mint, []).append(ev)
    out: list[dict] = []
    for token_events in by_token.values():
        out.extend(replay_token(token_events))
    return out


def load_events(path: str | Path) -> list[Event]:
    """Read the raw event rows pulled from Dune (JSON lines or a JSON array)."""
    text = Path(path).read_text()
    rows = json.loads(text) if text.lstrip().startswith("[") else [
        json.loads(l) for l in text.splitlines() if l.strip()
    ]
    return [
        Event(
            mint=r["mint"],
            slot=int(r["slot"]),
            tx_index=int(r["txi"]),
            ix_index=int(r["ixi"]),
            wallet=r["wallet"],
            is_buy=bool(r["is_buy"]),
            lam=int(r["lam"]),
            units=int(r["units"]),
            vsol=int(r["vsol"]),
            x0_lam=int(r["x0_lam"]),
            y0_units=int(r["y0_units"]),
        )
        for r in rows
    ]


if __name__ == "__main__":
    import sys

    rows = replay(load_events(sys.argv[1]))
    for r in rows:
        print(json.dumps({k: (str(v) if isinstance(v, Decimal) else v)
                          for k, v in r.items()}))
