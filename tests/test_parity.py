"""SQL ↔ Python parity on cached real data — spec §8.2 requirement 8.

No Dune access: both sides are files under data/cache/, committed so the check is
reproducible and auditable.

  parity_raw_events_200tokens.json  15,017 raw events, 200 hash-ordered tokens
                                    created 2026-06-01 (the frozen §2.2 sample rule)
  parity_sql_rows_200tokens.json    the 88 burst rows sql/extract_schema_probe.sql
                                    produced for exactly those tokens

The synthetic tests in this suite show the Python side is *correct*; this one
shows the SQL agrees with it on real data.  Neither alone is enough — together
they close the loop, with one residual risk worth naming: a definition both sides
share would survive both.  The window-convention test at the bottom is there
because that risk turned out to be real.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from statistics import pstdev

from src.features_reference import n_buyers, round_frac, size_cv
from src.oh_reference import load_events, replay

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
RAW = CACHE / "parity_raw_events_200tokens.json"
SQL = CACHE / "parity_sql_rows_200tokens.json"

#: Comparisons are RELATIVE since 2026-08-20 -- see src/parity_tolerance.  The
#: old fixed-decimal bounds demanded more than double precision delivers once a
#: value grew past 1, which showed up as a 9-ulp "failure" on oh_a.
from src.parity_tolerance import close  # noqa: E402


def _tokens() -> dict[str, list]:
    by_token: dict[str, list] = {}
    for event in load_events(RAW):
        by_token.setdefault(event.mint, []).append(event)
    for token in by_token.values():
        token.sort(key=lambda e: e.key)
    return by_token


def _locate(by_token: dict[str, list], key) -> tuple[int, list]:
    mint, slot, tx, ix = key
    token = by_token[mint]
    i = next(j for j, e in enumerate(token)
             if (e.slot, e.tx_index, e.ix_index) == (slot, tx, ix))
    return i, token


@pytest.fixture(scope="module")
def sides():
    py = {(r["mint"], r["slot"], r["tx_index"], r["ix_index"]): r
          for r in replay(load_events(RAW))}
    sq = {(r["token_mint"], int(r["slot"]), int(r["tx_index"]), int(r["ix_index"])): r
          for r in json.loads(SQL.read_text())}
    return py, sq


def test_cache_files_are_present_and_non_trivial():
    assert RAW.exists() and SQL.exists()
    assert len(json.loads(SQL.read_text())) == 88


def test_burst_sets_agree(sides):
    """Both sides must find the same burst_start events (§4.1)."""
    py, sq = sides
    assert set(py) == set(sq)
    assert len(py) == 88


@pytest.mark.parametrize("field", ["oh", "oh_ratio", "oh_conc"])
def test_oh_family_matches_to_12_places(sides, field):
    """§1.2 quantities agree to 12 decimals; the residual is float64 in the SQL."""
    py, sq = sides
    for key in sorted(set(py) & set(sq)):
        expected = py[key][field]
        got = Decimal(str(sq[key][field]))
        assert close(expected, got), f"{field} at {key}: {expected} vs {got}"


def test_trajectory_matches_element_by_element(sides):
    """All 75 slots of §4.3's primary (incl_pre) trajectory."""
    py, sq = sides
    compared = 0
    for key in sorted(set(py) & set(sq)):
        left, right = py[key]["nf3_traj_75_incl_pre"], sq[key]["nf3_traj_75_incl_pre"]
        assert len(left) == 75 and len(right) == 75, f"length at {key}"
        for a, (expected, got) in enumerate(zip(left, right), start=1):
            assert close(expected, got), f"incl_pre a={a} at {key}"
            compared += 1
    assert compared == 88 * 75


@pytest.mark.parametrize("a,column", [(1, "nf3_excl_pre_1"), (2, "nf3_excl_pre_2")])
def test_excl_pre_scalars_match(sides, a, column):
    """FIX 8: excl_pre survives as two scalars, a = 1 and a = 2.

    The Python reference still computes the whole 75-element excl_pre list — it is
    the reference, and staying richer than the extract is what lets this test
    check the reduction rather than assume it.  Elements 3..75 are dropped because
    they are identical to incl_pre by the window arithmetic, verified on chunk 1
    over 9,773,021 element comparisons with zero mismatches.
    """
    py, sq = sides
    for key in sorted(set(py) & set(sq)):
        expected = py[key]["nf3_traj_75_excl_pre"][a - 1]
        got = Decimal(str(sq[key][column]))
        assert close(expected, got), f"{column} at {key}"


def test_excl_pre_tail_is_redundant_with_incl_pre(sides):
    """The premise of FIX 8, re-asserted on the parity cohort itself."""
    py, _ = sides
    mismatches = 0
    for key in py:
        incl, excl = py[key]["nf3_traj_75_incl_pre"], py[key]["nf3_traj_75_excl_pre"]
        mismatches += sum(1 for a in range(2, 75) if incl[a] != excl[a])
    assert mismatches == 0


def test_quote_mint_is_carried_as_a_stratum_column(sides):
    """FIX 9: quote_mint is no longer a universe filter, but it is still exported."""
    _, sq = sides
    values = {r["quote_mint"] for r in sq.values()}
    assert values == {"11111111111111111111111111111111"}, values


@pytest.mark.parametrize("variant", ["incl", "excl"])
def test_death_age_matches(sides, variant):
    """§4.3 death age, derived from the trajectory on both sides."""
    py, sq = sides
    for key in sorted(set(py) & set(sq)):
        expected = py[key][f"death_age_{variant}"]
        got = sq[key][f"death_age_{variant}"]
        assert expected == (int(got) if got is not None else None), f"{variant} at {key}"


@pytest.mark.parametrize("feature,fn,column", [
    ("f3", n_buyers, "n_buyers_12slot"),
    ("f8", size_cv, "size_cv_25slot"),
    ("f9", round_frac, "round_frac_25slot"),
])
def test_trailing_window_features_match_sql(sides, feature, fn, column):
    """f3/f8/f9 against the SQL, asserting causal trailing windows (§3, §6.1).

    THIS TEST FAILS, and the failure is the finding.  Measured cause, not
    hypothesis — see `test_sql_trailing_window_defect_is_characterised` below,
    which reproduces the SQL exactly:

      1. `RANGE BETWEEN w PRECEDING AND CURRENT ROW` with `ORDER BY slot` treats
         every row sharing the current slot as a peer inside the frame, so the
         window swallows trades that execute LATER in (tx_index, ix_index) order.
         That is intra-slot lookahead — the exact thing the flow features avoid by
         being built as differences of prefix sums, and what §6.1 forbids.
      2. f3 additionally counts NULL as a buyer: `array_agg(if(is_buy, wallet))`
         emits NULL for every sell, `array_distinct` keeps one, and `cardinality`
         counts it — inflating n_buyers by exactly 1 whenever the window holds a sell.

    Not fixed here: the instruction for this task was to report failures, not
    repair them.
    """
    py, sq = sides
    events_by_token = _tokens()
    window = 12 if feature == "f3" else 25
    checked = 0
    for key in sorted(set(py) & set(sq)):
        i, token = _locate(events_by_token, key)
        expected = fn(token, i, window)
        got = sq[key][column]
        if expected is None or got is None:
            continue
        assert abs(Decimal(str(got)) - Decimal(expected)) < Decimal("1e-9"), \
            f"{feature} ({column}) at {key}: python {expected} vs sql {got}"
        checked += 1
    assert checked > 0


def test_intra_slot_lookahead_defect_is_gone(sides):
    """Regression for the two defects fixed on 2026-08-18 (FIX 4 / FIX 5b).

    Before the fix the SQL's f3/f8/f9 were reproduced *exactly* (88/88) by a rule
    that (a) let every row sharing the current slot into the window, including
    trades executing later in (tx_index, ix_index) order, and (b) counted the NULL
    that `if(is_buy, wallet)` emits for sells as a distinct buyer.  This test
    asserts the SQL no longer behaves that way: the peer rule must now MISS, and
    the causal rule must match, which the parity tests above assert directly.
    """
    py, sq = sides
    events_by_token = _tokens()
    peer_null_matches = cv_peer_matches = total = 0
    for key in sorted(set(py) & set(sq)):
        i, token = _locate(events_by_token, key)
        slot = token[i].slot
        peers12 = [e for e in token if slot - 12 <= e.slot <= slot]
        peers25 = [e for e in token if slot - 25 <= e.slot <= slot]
        buyers = len({e.wallet for e in peers12 if e.is_buy})
        with_null = buyers + (1 if any(not e.is_buy for e in peers12) else 0)
        got = sq[key]["n_buyers_12slot"]
        if got is not None:
            total += 1
            peer_null_matches += with_null == got
        cv = sq[key]["size_cv_25slot"]
        if cv is not None:
            sizes = [e.lam / 1e9 for e in peers25]
            mean = sum(sizes) / len(sizes)
            if mean:
                cv_peer_matches += abs(pstdev(sizes) / mean - float(cv)) < 1e-9
    assert total == 88
    assert peer_null_matches < 88, "f3 still reproduced by peer window + NULL buyer"
    assert cv_peer_matches < 88, "f8 still reproduced by the peer window"


@pytest.mark.parametrize("window,column", [(5, "fwd_net_flow_5slot"),
                                           (12, "fwd_net_flow_12slot"),
                                           (37, "fwd_net_flow_37slot")])
def test_forward_flow_labels_match(sides, window, column):
    """§4.2 forward flows use `RANGE 1 FOLLOWING ...`, excluding the current slot."""
    from src.features_reference import fwd_net_flow
    py, sq = sides
    by_token = _tokens()
    for key in sorted(set(py) & set(sq)):
        i, token = _locate(by_token, key)
        assert abs(fwd_net_flow(token, i, window) - Decimal(str(sq[key][column]))) < Decimal("1e-9"), \
            f"{column} at {key}"


@pytest.mark.parametrize("window,column", [(5, "x_at_plus5"), (12, "x_at_plus12"),
                                           (37, "x_at_plus37")])
def test_forward_price_labels_match(sides, window, column):
    """THIS FAILS for τ = 5 and 12, and the failure is the fourth audit finding.

    `x_at_plus*` is built as `last_value(vsol) OVER (ORDER BY slot RANGE BETWEEN
    CURRENT ROW AND w FOLLOWING)`.  `CURRENT ROW` in a RANGE frame pulls in every
    row sharing the current slot — including trades that execute later — so when
    the forward window is empty the SQL returns a same-slot successor's reserve
    where the reference returns this row's own.  Measured: 6/88 rows differ at
    τ = 5, 4/88 at τ = 12, 0/88 at τ = 37, and 36/88 bursts have a forward window
    ending on a multi-event slot, where `last_value` over ties is order-dependent
    as well.

    Two label families therefore disagree about what "future" means:
    `fwd_net_flow_*` uses `1 FOLLOWING` and never sees the current slot, while
    `x_at_plus*` sees all of it.  Which one §4.2 intends is a research decision,
    so this is reported, not silently changed.
    """
    from src.features_reference import x_at_plus
    py, sq = sides
    by_token = _tokens()
    for key in sorted(set(py) & set(sq)):
        i, token = _locate(by_token, key)
        assert abs(x_at_plus(token, i, window) - Decimal(str(sq[key][column]))) < Decimal("1e-9"), \
            f"{column} at {key}"
