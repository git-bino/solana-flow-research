"""The tolerance a SQL↔Python parity check should use, and why it is relative.

Before 2026-08-20 parity compared at a fixed number of decimals: 12 for the OH
family, 9 for trajectory elements.  That is an ABSOLUTE bound, and it silently
demands more than double precision can deliver once a value grows.

The measured case: `oh_a` on one of 88 bursts differed by 1.120e-15 on a value of
0.5738670139916…, which is about nine float64 ulps and roughly 1.95e-15 in
relative terms.  Nothing was semantically wrong -- OH is a sum over wallets of
`held x (P - cb)`, where `cb` is of order 1e-8 SOL per token and `held` of order
1e14 base units, so the product accumulates rounding across the wallets.  A
12-decimal absolute test on a number near 1 is a ~1e-12 relative test; on a
number near 300 it is a ~3e-15 one, tighter than the arithmetic allows.

So the bound is relative, with a floor of 1 in the denominator so that values at
or near zero are still compared absolutely:

    |a - b| / max(|a|, |b|, 1) < 1e-12
"""

from __future__ import annotations

from decimal import Decimal

#: Relative tolerance for every SQL↔Python comparison of a real-valued column.
REL_TOL = Decimal("1e-12")


def close(a, b, rel_tol: Decimal = REL_TOL) -> bool:
    """True when `a` and `b` agree to `rel_tol`, absolutely below magnitude 1.

    `None` is compared by identity: both missing is agreement, one missing is not.
    """
    if a is None or b is None:
        return a is None and b is None
    a, b = Decimal(str(a)), Decimal(str(b))
    denom = max(abs(a), abs(b), Decimal(1))
    return abs(a - b) / denom < rel_tol


def rel_gap(a, b) -> Decimal:
    """The quantity `close` thresholds, for reporting how far apart two values are."""
    if a is None or b is None:
        return Decimal(0) if (a is None and b is None) else Decimal("Infinity")
    a, b = Decimal(str(a)), Decimal(str(b))
    return abs(a - b) / max(abs(a), abs(b), Decimal(1))
