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
        in_slot = 1 + int(rng.random() < (config.slot_density - 1))
        for k in range(in_slot):
            if len(events) >= config.n_events:
                break
            tx_index += 1
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
