"""Pre-registered pipeline configuration — spec §2.2, §2.4, §6.1.

Everything here that affects the universe is a *pre-registration commitment*:
window, holdout boundary, sampling rule and rate.  Changing a value in this file
after data has been looked at is visible in git history (spec §6.2) and must be
accompanied by a decisions.md entry saying why.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# --- universe window (spec §2.2) -----------------------------------------
# Tokens are selected by *creation* time in [T_START, T_END).  Exactly 90 days.
T_START = datetime(2026, 5, 10, tzinfo=timezone.utc)
T_END = datetime(2026, 8, 8, tzinfo=timezone.utc)

#: Trades are fetched past T_END so that tokens created near the boundary keep a
#: complete history.  pump.fun tokens are short-lived; the tail that this still
#: truncates is reported in results/phase0_report.md.
EVENT_TAIL = timedelta(days=7)
EVENT_FETCH_END = T_END + EVENT_TAIL

#: Frozen holdout: the last 30% of the window (spec §6.1).  Split by *token
#: creation* time, not event time, so that every event of a token lands on one
#: side of the boundary (spec §8.4.4 assertion).
HOLDOUT_FRACTION = Decimal("0.30")
_span_days = (T_END - T_START).days
HOLDOUT_START = T_START + timedelta(
    days=int((Decimal(_span_days) * (1 - HOLDOUT_FRACTION)).to_integral_value())
)

# --- §0.1 size probe -----------------------------------------------------
# A 3-day *launch cohort* inside the dev period, followed for 7 days so each
# token's history is complete.  Deliberately mid-window: not a boundary, not the
# holdout.
PROBE_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
PROBE_END = datetime(2026, 6, 4, tzinfo=timezone.utc)
PROBE_TAIL_END = PROBE_END + EVENT_TAIL
PROBE_DAYS = (PROBE_END - PROBE_START).days

#: Sample rates priced in the §0.1 report (the chosen one is decided afterwards).
CANDIDATE_RATES = (Decimal("0.10"), Decimal("0.20"), Decimal("0.40"))

# --- sampling (spec §2.2) ------------------------------------------------
# Random *by token*, via mint hash.  Never by activity, volume, lifetime or
# migration status — those re-introduce survivorship.  Set once in Phase 0.1
# from the size estimate and frozen thereafter; see decisions.md.
SAMPLE_RATE: Decimal | None = None   # None = keep the full universe

SAMPLE_SALT = "solana-flow-research/phase0"

#: The sampling filter must run *inside* Dune SQL — filtering client-side would
#: pay the export cost of the whole universe and save nothing.  This expression is
#: the exact SQL twin of `mint_hash_fraction` below: first 4 bytes of
#: sha256("salt:mint") over 2^32.  Kept as one string so the two can never drift;
#: `ingest_dune estimate` verifies them against each other on real mints.
SAMPLE_SQL_FRACTION = (
    "from_base(substr(lower(to_hex(sha256(to_utf8(concat('"
    + SAMPLE_SALT
    + ":', {mint}))))), 1, 8), 16) / 4294967296.0"
)


def mint_hash_fraction(mint: str) -> Decimal:
    """Deterministic uniform-in-[0,1) value from a mint address.

    Salted so the rule can be re-derived anywhere but coincides with no hash the
    venue itself uses.  Four bytes, not eight, so that `SAMPLE_SQL_FRACTION` can
    reproduce it exactly with Trino's `from_base` (bigint) arithmetic.
    """
    digest = hashlib.sha256(f"{SAMPLE_SALT}:{mint}".encode()).digest()
    return Decimal(int.from_bytes(digest[:4], "big")) / Decimal(2**32)


def in_sample(mint: str, rate: Decimal | None = ...) -> bool:  # type: ignore[assignment]
    """Whether a mint is in the frozen random token sample."""
    if rate is ...:
        rate = SAMPLE_RATE
    return True if rate is None else mint_hash_fraction(mint) < rate


def split_of(created_at: datetime) -> str:
    """'dev' or 'holdout' for a token, from its creation time."""
    return "holdout" if created_at >= HOLDOUT_START else "dev"


# --- paths ---------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
RAW = DATA / "raw"                 # unmodified Dune pulls
DEV = DATA / "dev"                 # working universe
HOLDOUT = DATA / "holdout"         # sealed until Phase 7
RESULTS = REPO / "results"

# --- ClickHouse (spec §2.4) ---------------------------------------------
CH_BINARY = Path.home() / "clickhouse-bin" / "clickhouse"
CH_DATA = DATA / "clickhouse"
CH_HOST = "localhost"
CH_PORT = 8123
CH_DATABASE = "flow"

# --- Dune ----------------------------------------------------------------
DUNE_API = "https://api.dune.com/api/v1"
DUNE_NAMESPACE = "pumpdotfun_solana"   # confirmed by discovery, see report
DUNE_PERFORMANCE = "medium"            # 10 credits/execution; large is 20


def summary() -> str:
    return (
        f"window     [{T_START.date()}, {T_END.date()})  = {_span_days} days\n"
        f"holdout    [{HOLDOUT_START.date()}, {T_END.date()}) "
        f"= {(T_END - HOLDOUT_START).days} days ({HOLDOUT_FRACTION:%} of span)\n"
        f"events to  {EVENT_FETCH_END.date()} (+{EVENT_TAIL.days}d tail)\n"
        f"sampling   {'full universe' if SAMPLE_RATE is None else f'{SAMPLE_RATE:%} by mint hash'}"
    )


if __name__ == "__main__":
    print(summary())
