"""Round-trip cost model from the exact reserve path — Phase 1.

  python -m src.cost_model        # prints the reference table

Replaces the §1.1 closed-form breakeven, which an external audit showed is wrong
(decisions.md, 2026-08-19).  Its counter-example: with V = 0 and no fees, buying
q SOL and immediately selling back moves the reserve x → x+q → x, so gross P&L is
exactly zero — yet `BE = (1+V/x)²(1+q/x)²(1+fees) − 1` charges `(1+q/x)² − 1 > 0`.
Own price impact was counted as a loss on both legs of the round trip when it is
recovered on the way out.  `curve.breakeven_legacy` keeps that formula for the
audit trail; nothing here calls it.

Everything is `Decimal` at 60 digits.  The zero-fee round trip has to come back
exactly zero, and in float64 the cancellation in `k/x₁ − k/(x₁+q)` followed by
adding `k/(x₁+q)` back leaves ~1e-14 SOL of noise — larger than the tolerance the
audit's counter-example deserves.

Notation: `k = x₀·y₀` is constant; at any reserve `x` the token side is `y = k/x`.
`x` is in SOL and `y` in tokens, so `k` is SOL·tokens.

The path, in order (spec §5 fill model, corrected):

    1. observation      reserve = x_obs
    2. latency          V SOL of other flow lands first    → x₁ = x_obs + V
    3. own buy          q SOL enters the curve             → x_e = x₁ + q
                        tokens received  Δy = k/x₁ − k/x_e
    4. next flow        W SOL net, the quantity solved for → x₂ = x_e + W
    5. own exit         sell Δy back
                        y_state = k/x₂,  x_f = k/(y_state + Δy)
                        gross SOL out = x₂ − x_f

Fees: pump.fun 95bp + creator 30bp = 1.25% PER SIDE (§1.1, §5).  On entry `q` is
what reaches the curve, so the wallet spends `q/(1 − f)`.  On exit the curve pays
`x₂ − x_f` and the wallet keeps `(x₂ − x_f)·(1 − f)`.  Priority fee / tip is `pf`
SOL on each side.

FIXED COSTS (added 2026-08-21).  Everything above is PROPORTIONAL to `q`.  A real
round trip also pays SOL that does not scale with size:

    ATA rent            ~0.002 SOL   (refundable, but paid first)
    base signature fee   0.000005 SOL x 2 transactions
    priority fee / tip   0 … 0.001 SOL

`fixed_cost_per_leg` is that cost, in SOL, PER LEG -- the entry pays it and the
exit pays it again (research lead, decisions.md 2026-08-21).  ATA rent, base
signature fee and priority fee are all charged per TRANSACTION, and the round
trip is two transactions.  It was `fixed_cost_per_trade` and per ROUND TRIP until
2026-08-21; the rename makes the unit readable from the name.

Because it is fixed, its effect on the RETURN is `2·fixed / q`: at q = 0.05 SOL a
0.001 SOL per-leg cost is 4% of the position.

    net P&L = (x₂ − x_f)·(1 − f) − q/(1 − f) − 2·pf − 2·fixed_cost_per_leg
"""

from __future__ import annotations

from decimal import Decimal, getcontext

getcontext().prec = 60

#: Empirical launch reserves (§1.1, docs/phase0_size_estimate.md): 81,052 of
#: 81,052 tokens declared x₀ = 30 SOL and y₀ = 1,073,000,000 tokens.
X0_SOL = Decimal(30)
Y0_TOKENS = Decimal(1_073_000_000)
K_DEFAULT = X0_SOL * Y0_TOKENS          # 3.219e10 SOL·tokens

#: 95bp platform + 30bp creator, one side (§1.1).  The legacy formula used the
#: two-sided 0.025 as a single multiplier; here each side is charged separately.
FEE_RATE = Decimal("0.0125")

#: V at 2.5 slots, p75, cited from docs/phase3a_baseline_power.md.  Not recomputed
#: here: Phase 1 does not look at new data.
V_P75_SOL = Decimal("0.409886")


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def tokens_bought(x_obs, q, V=0, k=K_DEFAULT) -> Decimal:
    """Δy = k/x₁ − k/(x₁+q), the tokens the buy takes off the curve."""
    x1 = _d(x_obs) + _d(V)
    return _d(k) / x1 - _d(k) / (x1 + _d(q))


def gross_sol_out(dy: Decimal, x2: Decimal, k=K_DEFAULT) -> Decimal:
    """SOL the curve pays for selling `dy` tokens at reserve `x2`.

    x_f = k·x₂/(k + Δy·x₂), so x₂ − x_f = Δy·x₂²/(k + Δy·x₂).  Written in that
    form rather than as a difference of two large reserves, which cancels.
    """
    k = _d(k)
    return dy * x2 * x2 / (k + dy * x2)


def net_pnl(x_obs, q, V=0, W=0, fee_rate=FEE_RATE, pf=0, k=K_DEFAULT,
            fixed_cost_per_leg=0) -> Decimal:
    """Net P&L in SOL of the full path.  See the module docstring for the steps.

    `fixed_cost_per_leg` is SOL per LEG and is charged TWICE -- entry and exit.
    It does not scale with `q`, so it costs `2·fixed / q` of return.  Default 0
    keeps every earlier result identical.
    """
    x_obs, q, V, W = _d(x_obs), _d(q), _d(V), _d(W)
    f, pf, k = _d(fee_rate), _d(pf), _d(k)
    x1 = x_obs + V
    dy = k / x1 - k / (x1 + q)
    x2 = x1 + q + W
    out = gross_sol_out(dy, x2, k)
    return out * (1 - f) - q / (1 - f) - 2 * pf - 2 * _d(fixed_cost_per_leg)


def net_pnl_path(x_obs, q, V, w_steps, fee_rate=FEE_RATE, pf=0, k=K_DEFAULT) -> Decimal:
    """The same P&L with the post-entry flow applied as a sequence of steps.

    Walks (x, y) through each step instead of jumping straight to x₂.  Constant
    product makes this identical to `net_pnl` with W = Σ steps; the test uses it
    to check that claim on the actual arithmetic rather than on the algebra.
    """
    x_obs, q, V = _d(x_obs), _d(q), _d(V)
    f, pf, k = _d(fee_rate), _d(pf), _d(k)
    x = x_obs + V
    y = k / x
    dy = y - k / (x + q)
    x = x + q
    y = k / x
    for w in w_steps:
        x = x + _d(w)
        y = k / x
    x_f = k / (y + dy)
    return (x - x_f) * (1 - f) - q / (1 - f) - 2 * pf


def breakeven_w(x_obs, q, V=0, fee_rate=FEE_RATE, pf=0, k=K_DEFAULT) -> Decimal:
    """The net post-entry flow W at which `net_pnl` is exactly zero.

    CLOSED FORM, no root-finding.  Setting the gross proceeds equal to what the
    fees demand,

        R = (q/(1−f) + 2·pf) / (1−f)          required gross SOL out
        Δy·x₂² / (k + Δy·x₂) = R
        Δy·x₂² − R·Δy·x₂ − R·k = 0
        x₂ = [ R + √(R² + 4·R·k/Δy) ] / 2      (positive root)
        W  = x₂ − x_e

    `Decimal.sqrt` is exact to the working precision, so the result is good to
    far better than the 1e-12 SOL the brief allows; `tests/test_cost_model.py`
    verifies it by substitution rather than trusting the algebra.
    """
    x_obs, q, V = _d(x_obs), _d(q), _d(V)
    f, pf, k = _d(fee_rate), _d(pf), _d(k)
    x1 = x_obs + V
    x_e = x1 + q
    dy = k / x1 - k / x_e
    R = (q / (1 - f) + 2 * pf) / (1 - f)
    x2 = (R + (R * R + 4 * R * k / dy).sqrt()) / 2
    return x2 - x_e


def breakeven_w_limit_small_q(x_obs, V=0, fee_rate=FEE_RATE) -> Decimal:
    """The q → 0, pf = 0 limit of `breakeven_w`: (x_obs+V)·f/(1−f).

    Price is x²/k, so clearing a round trip that pays f on each side needs the
    price up by 1/(1−f)², i.e. the reserve up by 1/(1−f).  The move is therefore
    x₁·(1/(1−f) − 1).  Used as an independent check, not in the model.
    """
    f = _d(fee_rate)
    return (_d(x_obs) + _d(V)) * f / (1 - f)


# --- reference table ---------------------------------------------------------

X_OBS_GRID = [Decimal(35), Decimal(50), Decimal(70), Decimal(100)]
Q_GRID = [Decimal("0.5"), Decimal(1), Decimal(2), Decimal(5)]
V_GRID = [Decimal(0), V_P75_SOL]
PF_GRID = [Decimal(0), Decimal("0.001"), Decimal("0.01")]


def reference_table() -> list[dict]:
    rows = []
    for x_obs in X_OBS_GRID:
        for q in Q_GRID:
            for V in V_GRID:
                for pf in PF_GRID:
                    rows.append({
                        "x_obs": x_obs, "q": q, "V": V, "pf": pf,
                        "breakeven_w": breakeven_w(x_obs, q, V, pf=pf),
                    })
    return rows


def main() -> None:
    print(f"k = {K_DEFAULT:.6e} SOL*tokens   fee_rate = {FEE_RATE} per side   "
          f"V_p75 = {V_P75_SOL} SOL (cited)")
    print(f"{'x_obs':>6}{'q':>6}{'V':>10}{'pf':>7}{'breakeven_W (SOL)':>20}")
    for r in reference_table():
        print(f"{r['x_obs']:>6}{r['q']:>6}{r['V']:>10}{r['pf']:>7}"
              f"{r['breakeven_w']:>20.9f}")


if __name__ == "__main__":
    main()
