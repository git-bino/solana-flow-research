"""Parameterised synthetic event streams for the §8.2 requirement-8 tests.

Curve state is generated with `src.curve`'s integer helpers rather than made up,
so `vsol` on every row is the reserve a real trade would have produced.  That
matters for the leakage tests: a feature reading x(t) must see a plausible
series, otherwise a test could pass for the wrong reason.

The perturbation helpers are the other half of the design.  A leakage test is
only meaningful if the code under test *could* leak, so features are computed
from the whole event list plus an index (see `src.features_reference`), and these
helpers corrupt strictly the part of that list which lies after t.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from src.curve import X0_LAMPORTS, Y0_UNITS, sol_out_for_tokens_in, tokens_out_for_sol_in
from src.oh_reference import Event


@dataclass(frozen=True)
class SyntheticConfig:
    n_tokens: int = 3
    n_events: int = 60          # per token
    slot_density: float = 1.5   # mean events per occupied slot
    empty_slot_share: float = 0.3   # share of slot steps that advance with no trade
    mayhem_share: float = 0.0   # share of tokens flagged mayhem
    sell_share: float = 0.35
    round_share: float = 0.2    # share of trades at exactly 0.1/0.5/1.0 SOL
    n_wallets: int = 12
    seed: int = 1234
    #: legs inside ONE transaction.  Separate from `n_tx_per_slot` because the two
    #: break different things: legs are simultaneous, transactions are ordered.
    n_events_per_tx: int = 1
    #: transactions per occupied slot.  None keeps the historical `slot_density`
    #: behaviour, so every stream built before 2026-08-19 is bit-identical.
    n_tx_per_slot: int | None = None


def make_token(config: SyntheticConfig, token_index: int) -> list[Event]:
    """One token's event stream, with exact curve reserves."""
    rng = random.Random(config.seed * 1000 + token_index)
    mint = f"MINT{token_index:04d}" + "z" * 30
    wallets = [f"W{i:03d}" + "y" * 38 for i in range(config.n_wallets)]
    x, y = X0_LAMPORTS, Y0_UNITS
    held: dict[str, int] = {}
    events: list[Event] = []
    slot = 400_000_000 + token_index * 10_000
    tx_index = 0
    while len(events) < config.n_events:
        # advance the slot, sometimes leaving gaps so empty-slot handling is exercised
        step = 1
        while rng.random() < config.empty_slot_share:
            step += 1
        slot += step
        if config.n_tx_per_slot is None and config.n_events_per_tx == 1:
            # historical path, kept byte-for-byte so existing streams do not move
            plan = [(t, 0) for t in range(1 + int(rng.random() < (config.slot_density - 1)))]
        else:
            n_tx = config.n_tx_per_slot or 1
            plan = [(t, leg) for t in range(n_tx)
                    for leg in range(config.n_events_per_tx)]
        last_tx = None
        for t_idx, k in plan:
            if len(events) >= config.n_events:
                break
            if t_idx != last_tx:
                tx_index += 1
                last_tx = t_idx
            wallet = rng.choice(wallets)
            sellable = held.get(wallet, 0)
            if sellable > 0 and rng.random() < config.sell_share:
                units = rng.randint(1, sellable)
                lam = sol_out_for_tokens_in(x, y, units)
                if lam <= 0 or x - lam < X0_LAMPORTS:
                    continue
                x, y = x - lam, y + units
                held[wallet] = sellable - units
                is_buy = False
            else:
                if rng.random() < config.round_share:
                    lam = rng.choice([100_000_000, 500_000_000, 1_000_000_000])
                else:
                    lam = rng.randint(5_000_000, 2_000_000_000)
                units = tokens_out_for_sol_in(x, y, lam)
                x, y = x + lam, y - units
                held[wallet] = sellable + units
                is_buy = True
            events.append(Event(
                mint=mint, slot=slot, tx_index=tx_index, ix_index=k * 64,
                wallet=wallet, is_buy=is_buy, lam=lam, units=units, vsol=x,
                x0_lam=X0_LAMPORTS, y0_units=Y0_UNITS,
            ))
    return events


def make_events(config: SyntheticConfig | None = None) -> list[Event]:
    config = config or SyntheticConfig()
    out: list[Event] = []
    for i in range(config.n_tokens):
        out.extend(make_token(config, i))
    return out


# --- perturbations: touch only what lies strictly after index t ------------

def _after(events: list[Event], t: int) -> list[int]:
    return [i for i in range(len(events)) if i > t]


def perturb_scale_sol(events: list[Event], t: int, factor: int = 100) -> list[Event]:
    """Multiply every later trade's SOL amount and its resulting reserve.

    `vsol` is scaled as well, otherwise the corrupted future stays internally
    consistent in x and the price-based forward labels (§4.2 fwd_price_ret) have
    nothing to react to — the counter-test would fail for a reason that has
    nothing to do with lookahead.  Keys and ordering are untouched.
    """
    out = list(events)
    for i in _after(events, t):
        out[i] = replace(out[i], lam=out[i].lam * factor,
                         vsol=out[i].vsol + out[i].lam * (factor - 1))
    return out


def perturb_flip_side(events: list[Event], t: int) -> list[Event]:
    """Reverse the direction of every later trade."""
    out = list(events)
    for i in _after(events, t):
        out[i] = replace(out[i], is_buy=not out[i].is_buy)
    return out


def perturb_insert(events: list[Event], t: int, n: int = 3) -> list[Event]:
    """Insert brand-new trades immediately after t, in the slots that follow."""
    out = list(events[: t + 1])
    anchor = events[t]
    for k in range(n):
        out.append(replace(
            anchor,
            slot=anchor.slot + 1 + k,
            tx_index=anchor.tx_index + 1000 + k,
            ix_index=0,
            wallet="INJECT" + "q" * 38,
            is_buy=True,
            lam=1_500_000_000,
            units=10_000_000,
        ))
    out.extend(events[t + 1:])
    return out


PERTURBATIONS = {
    "scale_sol_x100": perturb_scale_sol,
    "flip_side": perturb_flip_side,
    "insert_events": perturb_insert,
}


# ===========================================================================
# Audit-driven extensions (2026-08-19).
#
# The external audit found four classes of defect that none of the existing 157
# tests caught.  The tests were not at fault: this generator never produced the
# conditions, so nothing could look at them.  Everything below exists to make
# those conditions constructible.
#
# `Event` (src/oh_reference) carries neither the token-side reserve nor the raw
# instruction indices, and src/oh_reference must not be modified, so the richer
# facts live in `RawEvent` here and are projected down with `.to_event()`.
# ===========================================================================

from dataclasses import fields as _dc_fields  # noqa: E402

#: The packing the extract applies: ix_index = coalesce(outer,0)*64 + coalesce(inner,0).
IX_PACK_BASE = 64


@dataclass(frozen=True)
class RawEvent:
    """One pump.fun event with everything the extract sees before it is flattened.

    `outer` / `inner` are the raw instruction indices; either may be None, which
    the extract coalesces to 0.  `vtok` is the token-side virtual reserve, which
    `Event` drops — it is the only way to compute an instantaneous k.
    """
    mint: str
    slot: int
    tx_index: int
    outer: int | None
    inner: int | None
    wallet: str
    is_buy: bool
    lam: int
    units: int
    vsol: int
    vtok: int
    x0_lam: int = X0_LAMPORTS
    y0_units: int = Y0_UNITS
    mayhem: bool = False

    @property
    def packed_ix(self) -> int:
        return (self.outer or 0) * IX_PACK_BASE + (self.inner or 0)

    @property
    def raw_order_key(self) -> tuple:
        """The ordering the raw pair supports, which the packed value cannot."""
        return (self.slot, self.tx_index, self.outer or 0, self.inner or 0)

    def to_event(self) -> Event:
        return Event(mint=self.mint, slot=self.slot, tx_index=self.tx_index,
                     ix_index=self.packed_ix, wallet=self.wallet, is_buy=self.is_buy,
                     lam=self.lam, units=self.units, vsol=self.vsol,
                     x0_lam=self.x0_lam, y0_units=self.y0_units)


@dataclass(frozen=True)
class Transfer:
    """An SPL token transfer.  Emits NO TradeEvent, so the ledger cannot see it."""
    mint: str
    slot: int
    tx_index: int
    sender: str
    recipient: str
    units: int


MINT = "MINT" + "z" * 40
W = {k: f"W{k}" + "y" * 40 for k in "ABCD"}


def _raw(slot, tx_index, outer, inner, wallet, is_buy, lam, units, vsol, vtok,
         mayhem=False) -> RawEvent:
    return RawEvent(mint=MINT, slot=slot, tx_index=tx_index, outer=outer, inner=inner,
                    wallet=wallet, is_buy=is_buy, lam=lam, units=units, vsol=vsol,
                    vtok=vtok, mayhem=mayhem)


# --- 1. several events per transaction, several transactions per slot -------

def same_slot_stream(n_tx_per_slot: int, n_events_per_tx: int, slot: int = 500,
                     lam: int = 100_000_000) -> list[RawEvent]:
    """`n_tx_per_slot` transactions in ONE slot, each carrying `n_events_per_tx` legs.

    The two counts are separate parameters because they break different things:
    legs inside one transaction are simultaneous, whereas separate transactions in
    a slot are ordered but still share the slot a RANGE window keys on.
    """
    out: list[RawEvent] = []
    x, y = X0_LAMPORTS, Y0_UNITS
    for t in range(n_tx_per_slot):
        for leg in range(n_events_per_tx):
            units = tokens_out_for_sol_in(x, y, lam)
            x, y = x + lam, y - units
            out.append(_raw(slot, t, 0, leg + 1, W["A"], True, lam, units, x, y))
    return out


# --- 2. mayhem reparameterisation -------------------------------------------

def mayhem_reparameterised(jump_factor: float = 1.5) -> list[RawEvent]:
    """Two segments; at the boundary `vsol` jumps and `vtok` does not.

    Matches what the KILL gate measured (docs/phase0_kill_gate.md): on mayhem
    pairs the token side reconciles with the trade 100% of the time while the SOL
    side does not, so the product x·y moves.  After the jump the instantaneous k
    is `jump_factor` times the launch k.
    """
    out: list[RawEvent] = []
    x, y = X0_LAMPORTS, Y0_UNITS
    lam = 10_000_000_000                      # 10 SOL, well clear of launch
    units = tokens_out_for_sol_in(x, y, lam)
    x, y = x + lam, y - units
    out.append(_raw(600, 0, 0, 1, W["A"], True, lam, units, x, y))

    x_jump = int(x * jump_factor)             # SOL side jumps, token side does not
    lam2 = 1_000_000_000
    units2 = tokens_out_for_sol_in(x_jump, y, lam2)
    x2, y2 = x_jump + lam2, y - units2
    out.append(_raw(601, 0, 0, 1, W["B"], True, lam2, units2, x2, y2, mayhem=True))
    return out


# --- 3. SPL transfer --------------------------------------------------------

def transfer_then_sell(buy_units: int = 100_000_000,
                       transfer_units: int = 60_000_000
                       ) -> tuple[list[RawEvent], list[Transfer]]:
    """A buys, moves part of the balance to B off-curve, then B sells that part.

    The ledger sees A's buy and B's sell but never the transfer, so A keeps credit
    for tokens it no longer holds and B goes negative.
    """
    x, y = X0_LAMPORTS, Y0_UNITS
    lam_in = 2_000
    x_a, y_a = x + lam_in, y - buy_units
    a_buy = _raw(700, 0, 0, 1, W["A"], True, lam_in, buy_units, x_a, y_a)

    move = Transfer(MINT, 701, 0, W["A"], W["B"], transfer_units)

    lam_out = 1_000
    x_b, y_b = x_a - lam_out, y_a + transfer_units
    b_sell = _raw(702, 0, 0, 1, W["B"], False, lam_out, transfer_units, x_b, y_b)
    return [a_buy, b_sell], [move]


# --- 4. full exit, then re-entry --------------------------------------------

def exit_then_rebuy(first_sol: int = 1_000_000_000,
                    second_sol: int = 10_000_000_000,
                    units_each: int = 1_000_000) -> list[RawEvent]:
    """Buy → sell the whole balance → buy again, one token's worth each time.

    Sizes are chosen so each buy takes exactly one token (1e6 base units): that
    makes the two cost-basis conventions hand-computable, 5.5 against 10.
    """
    x, y = X0_LAMPORTS, Y0_UNITS
    x1, y1 = x + first_sol, y - units_each
    x2, y2 = x1 - first_sol, y1 + units_each
    x3, y3 = x2 + second_sol, y2 - units_each
    return [
        _raw(800, 0, 0, 1, W["A"], True, first_sol, units_each, x1, y1),
        _raw(801, 0, 0, 1, W["A"], False, first_sol, units_each, x2, y2),
        _raw(802, 0, 0, 1, W["A"], True, second_sol, units_each, x3, y3),
    ]


# --- 5. raw (outer, inner), including inner >= 64 ---------------------------

def packing_collision_pair() -> tuple[RawEvent, RawEvent]:
    """(outer=0, inner=64) and (outer=1, inner=0): distinct legs, identical packing."""
    x, y = X0_LAMPORTS, Y0_UNITS
    return (_raw(900, 0, 0, 64, W["A"], True, 1_000_000, 1_000, x, y),
            _raw(900, 0, 1, 0, W["B"], True, 1_000_000, 1_000, x, y))


def packing_null_inner() -> RawEvent:
    """`inner` absent — the extract coalesces it to 0."""
    x, y = X0_LAMPORTS, Y0_UNITS
    return _raw(901, 0, 3, None, W["A"], True, 1_000_000, 1_000, x, y)


# --- label-boundary fixture --------------------------------------------------

def trigger_with_same_slot_neighbours(n_before: int = 2, n_after: int = 3,
                                      slot: int = 1000, lam: int = 500_000_000
                                      ) -> tuple[list[RawEvent], int]:
    """Trades before and after a trigger, all sharing the trigger's slot.

    Each is its own transaction, so they are ordered but not simultaneous.
    Returns the stream and the trigger's index in it.
    """
    out: list[RawEvent] = []
    x, y = X0_LAMPORTS, Y0_UNITS
    tx = 0
    for _ in range(n_before):
        units = tokens_out_for_sol_in(x, y, lam)
        x, y = x + lam, y - units
        out.append(_raw(slot, tx, 0, 1, W["B"], True, lam, units, x, y))
        tx += 1
    units = tokens_out_for_sol_in(x, y, lam)
    x, y = x + lam, y - units
    out.append(_raw(slot, tx, 0, 1, W["A"], True, lam, units, x, y))
    trigger = len(out) - 1
    tx += 1
    for _ in range(n_after):
        units = tokens_out_for_sol_in(x, y, lam)
        x, y = x + lam, y - units
        out.append(_raw(slot, tx, 0, 1, W["C"], True, lam, units, x, y))
        tx += 1
    return out, trigger


def config_field_names() -> set[str]:
    return {f.name for f in _dc_fields(SyntheticConfig)}
