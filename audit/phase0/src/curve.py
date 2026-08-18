"""Bonding-curve state reconstruction — spec §1.1, §2.3.

Causality (spec §6.1, §8.2.2)
-----------------------------
Every entry point here is causal by construction.  Curve state is advanced one
event at a time through `CurveState.apply`, which sees a single event and the
state produced by strictly earlier events — there is no argument through which a
future event could reach it.  `replay_token` *asserts* the ordering it needs
(non-decreasing `(slot, tx_index, ix_index)`, spec §2.4) rather than sorting
silently, so a caller handing over shuffled or future-mixed rows fails loudly
instead of quietly leaking lookahead.

Arithmetic
----------
Money is integer base units end to end: lamports for SOL, base units for tokens
(6 decimals).  The on-chain program mutates the virtual reserves by exact u64
addition/subtraction, so integer replay is *exact* — the reconstruction carries
no floating-point drift over any number of events.  Human units (SOL, tokens)
are produced only at the boundary, as `Decimal`.  `FloatCurveState` exists only
to quantify the error the integer path avoids (§0.4) and must not be used for
reconstruction.

Fee convention
--------------
The state update uses the SOL amount that actually enters/leaves the curve.
Whether a source's `sol_amount` field *is* that amount (NET) or includes the
platform fee (GROSS) is a property of the data source, determined empirically in
Phase 0 §0.3 and passed in explicitly as `SolAmountConvention`.  Nothing here
guesses: `CurveState.apply` requires the convention as an argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable, Iterator, Literal

# --- constants (spec §1.1) ------------------------------------------------
# spec §1.1 pins x0 = 30 SOL, y0 = 1,073,000,191 tokens.  Both are stated there
# as fixed and non-controversial, so they are used as given; `validate_phase0`
# additionally re-derives the pre-trade reserves of each token's first observed
# event from on-chain state and reports any disagreement (some public sources
# quote y0 = 1,073,000,000).  Do not "fix" these from memory — fix them from the
# reported empirical value, and record the change in decisions.md.

LAMPORTS_PER_SOL = 1_000_000_000
TOKEN_DECIMALS = 6
TOKEN_UNITS_PER_TOKEN = 10**TOKEN_DECIMALS

X0_SOL = Decimal(30)
Y0_TOKENS = Decimal(1_073_000_191)

X0_LAMPORTS = int(X0_SOL) * LAMPORTS_PER_SOL              # 30e9
Y0_UNITS = int(Y0_TOKENS) * TOKEN_UNITS_PER_TOKEN         # 1.073000191e15
K_UNITS = X0_LAMPORTS * Y0_UNITS                          # k in base units
K_HUMAN = X0_SOL * Y0_TOKENS                              # k in SOL * tokens

MIGRATION_REAL_SOL = Decimal(85)                          # spec §1.1: x ~ 115
FEE_BPS_DEFAULT = 100                                     # pump.fun 1% per side


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class SolAmountConvention(str, Enum):
    """What a source's `sol_amount` field measures."""

    #: the amount that enters/leaves the curve (fee accounted for elsewhere)
    NET_OF_FEE = "net_of_fee"
    #: what the trader paid (buy) or received (sell), fee included
    GROSS_INCLUDES_FEE = "gross_includes_fee"


class CurveViolation(ValueError):
    """Reconstructed state left the region the curve can occupy."""


class OrderingViolation(ValueError):
    """Events were not presented in causal order (spec §2.4)."""


@dataclass(frozen=True, slots=True)
class CurveEvent:
    """One trade, in integer base units, with its ordering key.

    `ix_index` breaks ties inside a single transaction: one transaction can hold
    several pump.fun trades (bundles, aggregators), and `(slot, tx_index)` alone
    does not order them.  See decisions.md — this column is a superset of the
    §2.3 schema, not a replacement for it.
    """

    slot: int
    tx_index: int
    ix_index: int
    side: Side
    sol_amount: int      # lamports, as reported by the source
    token_amount: int    # token base units

    @property
    def order_key(self) -> tuple[int, int, int]:
        return (self.slot, self.tx_index, self.ix_index)


@dataclass(frozen=True, slots=True)
class Reconstruction:
    """State around one applied event.  All fields integer base units."""

    x_pre: int
    y_pre: int
    x_post: int
    y_post: int
    curve_sol: int       # signed lamports through the curve (+buy / -sell)
    fee_lamports: int    # fee implied by the convention, 0 when NET_OF_FEE

    @property
    def x_pre_sol(self) -> Decimal:
        return lamports_to_sol(self.x_pre)

    @property
    def x_post_sol(self) -> Decimal:
        return lamports_to_sol(self.x_post)


# --- unit helpers ---------------------------------------------------------

def lamports_to_sol(lamports: int) -> Decimal:
    return Decimal(lamports) / LAMPORTS_PER_SOL


def sol_to_lamports(sol: Decimal | int | str) -> int:
    return int((Decimal(sol) * LAMPORTS_PER_SOL).to_integral_value())


def units_to_tokens(units: int) -> Decimal:
    return Decimal(units) / TOKEN_UNITS_PER_TOKEN


# --- closed-form curve formulas (spec §1.1) ------------------------------
# These take state explicitly and are pure; they are used for the *prediction*
# side of validation check 2, never to advance state.

def spot_price(x_sol: Decimal) -> Decimal:
    """P(x) = x^2 / k, SOL per token — spec §1.1, exact-invariant form."""
    return Decimal(x_sol) ** 2 / K_HUMAN


def spot_price_from_reserves(x: int, y: int) -> Decimal:
    """P = x / y from the *observed* reserve pair, in SOL per token.

    Preferred over `spot_price` on real data: the on-chain program computes one
    side from the other with integer truncation, so x*y drifts a few parts per
    10^15 away from k and x/y is the price that actually cleared.
    """
    return (Decimal(x) / LAMPORTS_PER_SOL) / (Decimal(y) / TOKEN_UNITS_PER_TOKEN)


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


# Rounding convention for the two helpers below: the remaining reserve is
# rounded *up*, so the amount handed to the trader is the floor of the exact
# value and truncation can never pay the trader more than the curve owes.  The
# deployed program's own ±1-lamport rounding differs in detail (it adds 1 lamport
# to a buy's cost and floors a sell's reserve); at the 0.01 SOL tolerance of
# validation check 1 the difference is 10^-7 of the budget, and reconstruction
# never depends on it — `CurveState` moves reserves by *observed* amounts.

def tokens_out_for_sol_in(x: int, y: int, sol_in: int) -> int:
    """Buy: Δy = y − k/(x+q), floored toward the reserve."""
    if sol_in <= 0:
        raise ValueError("sol_in must be positive")
    return y - _ceil_div(x * y, x + sol_in)


def sol_out_for_tokens_in(x: int, y: int, tokens_in: int) -> int:
    """Sell: Δx = x − k/(y+Δy), floored toward the reserve."""
    if tokens_in <= 0:
        raise ValueError("tokens_in must be positive")
    return x - _ceil_div(x * y, y + tokens_in)


def avg_price_buy(x_sol: Decimal, q_sol: Decimal) -> Decimal:
    """Average price paid for a q-SOL buy: x(x+q)/k — spec §1.1."""
    x_sol, q_sol = Decimal(x_sol), Decimal(q_sol)
    return x_sol * (x_sol + q_sol) / K_HUMAN


def own_slippage(q_sol: Decimal, x_sol: Decimal) -> Decimal:
    """slip(q, x) = q / x — spec §1.1."""
    return Decimal(q_sol) / Decimal(x_sol)


def latency_cost(v_sol: Decimal, x_sol: Decimal) -> Decimal:
    """lat(V, x) = (1 + V/x)^2 − 1 — spec §1.1."""
    return (1 + Decimal(v_sol) / Decimal(x_sol)) ** 2 - 1


def round_trip_breakeven(
    v_sol: Decimal, q_sol: Decimal, x_sol: Decimal, fees: Decimal = Decimal("0.02")
) -> Decimal:
    """BE = (1+V/x)^2 (1+q/x)^2 (1+fees) − 1 — spec §1.1."""
    x_sol = Decimal(x_sol)
    return (
        (1 + Decimal(v_sol) / x_sol) ** 2
        * (1 + Decimal(q_sol) / x_sol) ** 2
        * (1 + Decimal(fees))
    ) - 1


def curve_progress(x_sol: Decimal) -> Decimal:
    """(x − 30) / 85 — spec §3 f5."""
    return (Decimal(x_sol) - X0_SOL) / MIGRATION_REAL_SOL


# --- convention handling (spec §0.3) -------------------------------------

def curve_sol_amount(
    reported_sol: int,
    side: Side,
    convention: SolAmountConvention,
    fee_bps: int = FEE_BPS_DEFAULT,
) -> tuple[int, int]:
    """Map a reported SOL amount onto (amount through curve, implied fee).

    NET_OF_FEE      → the reported amount *is* the curve amount.
    GROSS_INCLUDES_FEE → a buyer paid curve + fee, a seller received curve − fee,
                         so the curve amount is recovered by dividing out the fee.
    """
    if convention is SolAmountConvention.NET_OF_FEE:
        return reported_sol, 0
    denom = 10_000 + fee_bps if side is Side.BUY else 10_000 - fee_bps
    curve = (reported_sol * 10_000) // denom
    return curve, abs(reported_sol - curve)


# --- causal state machine ------------------------------------------------

class CurveState:
    """Virtual reserves of one token, advanced event by event.

    Holds no history and no future: `apply` sees one event plus the state that
    earlier events produced.
    """

    __slots__ = ("x", "y", "n_applied", "_last_key")

    def __init__(self, x: int = X0_LAMPORTS, y: int = Y0_UNITS) -> None:
        self.x = x
        self.y = y
        self.n_applied = 0
        self._last_key: tuple[int, int, int] | None = None

    def apply(
        self,
        event: CurveEvent,
        convention: SolAmountConvention,
        fee_bps: int = FEE_BPS_DEFAULT,
    ) -> Reconstruction:
        """Advance one event and return the state around it.

        The reserve update mirrors the program: virtual SOL moves by the curve
        SOL amount and virtual tokens move by the traded token amount.  It is
        additive, so `x_post` of one event is `x_pre` of the next by identity —
        which is what validation check 5 verifies against on-chain state.
        """
        if self._last_key is not None and event.order_key < self._last_key:
            raise OrderingViolation(
                f"event {event.order_key} precedes already-applied {self._last_key}; "
                "events must arrive in (slot, tx_index, ix_index) order"
            )
        if event.sol_amount < 0 or event.token_amount < 0:
            raise ValueError(f"negative amount in {event!r}")

        curve_sol, fee = curve_sol_amount(
            event.sol_amount, event.side, convention, fee_bps
        )
        x_pre, y_pre = self.x, self.y
        if event.side is Side.BUY:
            x_post = x_pre + curve_sol
            y_post = y_pre - event.token_amount
            signed = curve_sol
        else:
            x_post = x_pre - curve_sol
            y_post = y_pre + event.token_amount
            signed = -curve_sol

        if x_post < X0_LAMPORTS:
            raise CurveViolation(
                f"x_post {x_post} < x0 {X0_LAMPORTS}: implies negative real SOL "
                "reserve (missing earlier buys, or wrong fee convention)"
            )
        if y_post <= 0:
            raise CurveViolation(f"y_post {y_post} <= 0")

        self.x, self.y = x_post, y_post
        self.n_applied += 1
        self._last_key = event.order_key
        return Reconstruction(x_pre, y_pre, x_post, y_post, signed, fee)


def replay_token(
    events: Iterable[CurveEvent],
    convention: SolAmountConvention,
    fee_bps: int = FEE_BPS_DEFAULT,
    on_violation: Literal["raise", "record"] = "raise",
    initial: CurveState | None = None,
) -> Iterator[tuple[CurveEvent, Reconstruction | None, str | None]]:
    """Replay one token's events in order, yielding (event, reconstruction, error).

    Ordering is asserted, never repaired: an out-of-order event raises
    `OrderingViolation` regardless of `on_violation`, because silently sorting
    would hide the bug that produced it.  `on_violation="record"` only tolerates
    *state* violations (`CurveViolation`), which validation needs to count; the
    offending event is skipped and state is left untouched so the remaining
    events stay interpretable.
    """
    state = initial if initial is not None else CurveState()
    for event in events:
        try:
            yield event, state.apply(event, convention, fee_bps), None
        except CurveViolation as exc:
            if on_violation == "raise":
                raise
            yield event, None, str(exc)


# --- diagnostic only: float arithmetic (spec §0.4) -----------------------

class FloatCurveState:
    """Same recursion in float64 SOL, to *measure* accumulated error.

    Never use for reconstruction.  `validate_phase0` replays real tokens through
    both this and `CurveState` and reports the divergence after 10^5 events.
    """

    __slots__ = ("x", "y", "n_applied")

    def __init__(self) -> None:
        self.x = float(X0_LAMPORTS) / LAMPORTS_PER_SOL
        self.y = float(Y0_UNITS) / TOKEN_UNITS_PER_TOKEN
        self.n_applied = 0

    def apply(self, event: CurveEvent, convention: SolAmountConvention,
              fee_bps: int = FEE_BPS_DEFAULT) -> float:
        reported = event.sol_amount / LAMPORTS_PER_SOL
        if convention is SolAmountConvention.NET_OF_FEE:
            curve = reported
        else:
            fee_mult = 1 + fee_bps / 10_000 if event.side is Side.BUY else 1 - fee_bps / 10_000
            curve = reported / fee_mult
        tokens = event.token_amount / TOKEN_UNITS_PER_TOKEN
        if event.side is Side.BUY:
            self.x += curve
            self.y -= tokens
        else:
            self.x -= curve
            self.y += tokens
        self.n_applied += 1
        return self.x
