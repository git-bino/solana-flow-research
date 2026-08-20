"""Phase 0 validation — spec §7 Phase 0, prompt §0.3/§0.4 and checks 1–6.

  python -m src.validate_phase0 fee      # §0.3 step 1: determine the convention
  python -m src.validate_phase0 checks   # checks 1–6 -> results/phase0_report.md

`fee` runs first and on raw amounts only: the convention it establishes is what
the loader then uses to reconstruct x, so it cannot depend on x.  It writes
results/fee_convention.json, which `load_clickhouse` reads.

Every subcommand appends to test_log.md (spec §6.7): each look at the data is
recorded, so "how many hypotheses were tested" is answered by git rather than by
memory.

KILL: check 1 failing stops Phase 0.  Nothing downstream is meaningful if the
curve cannot be reconstructed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src import stats  # noqa: E402
from src.curve import (  # noqa: E402
    LAMPORTS_PER_SOL,
    TOKEN_UNITS_PER_TOKEN,
    X0_LAMPORTS,
    Y0_UNITS,
    CurveEvent,
    CurveState,
    FloatCurveState,
    Side,
    SolAmountConvention,
    lamports_to_sol,
)
from src.load_clickhouse import client  # noqa: E402

FEE_JSON = config.RESULTS / "fee_convention.json"
REPORT = config.RESULTS / "phase0_report.md"

#: Tolerances.  Only the first is fixed by the spec (§7 Phase 0); the other two
#: operationalise checks the spec states qualitatively ("must match", "stable").
#: They are written down here, before the run, so they cannot drift afterwards.
X_TOLERANCE_SOL = 0.01          # spec §7 Phase 0, check 1
X_TOLERANCE_SHARE = 0.99        # spec §7 Phase 0: ">99% of events"
PRICE_REL_TOLERANCE = 0.005     # check 2, borrowed from Phase 1's 0.5% bound
DAILY_COUNT_BAND = (0.5, 2.0)   # check 4: day vs median-day, factor band


@dataclass
class CheckResult:
    number: int | str
    name: str
    passed: bool
    detail: str

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"


def append_test_log(what: str, result: str, cell: str = "n/a", cohort: str = "dev") -> None:
    line = f"| {date.today().isoformat()} | 0 | {cell} | {cohort} | {what} — {result} |\n"
    path = config.REPO / "test_log.md"
    with path.open("a") as fh:
        fh.write(line)


# --- data access ----------------------------------------------------------

EVENT_COLUMNS = (
    "token_mint, slot, tx_index, ix_index, side, sol_lamports, token_units, "
    "vsol_post, vtoken_post, fee_lamports, block_time, x_pre_lamports, x_post_lamports"
)


def load_events(limit_tokens: int | None = None):
    """Load dev events in canonical order (spec §2.4).

    Ordered by (token_mint, slot, tx_index, ix_index) so that per-token replay is
    causal; `CurveState` re-asserts that ordering rather than trusting it.
    """
    import pandas as pd  # noqa: F401

    ch = client()
    where = "WHERE split = 'dev'"
    if limit_tokens:
        where += (
            f" AND token_mint IN (SELECT token_mint FROM {config.CH_DATABASE}.event "
            f"GROUP BY token_mint ORDER BY count() DESC LIMIT {limit_tokens})"
        )
    return ch.query_df(
        f"SELECT {EVENT_COLUMNS} FROM {config.CH_DATABASE}.event {where} "
        "ORDER BY token_mint, slot, tx_index, ix_index"
    )


def signed_curve_lamports(frame, convention: SolAmountConvention, fee_bps: int = 100) -> np.ndarray:
    """Signed lamports through the curve for each row, under a convention."""
    reported = frame["sol_lamports"].to_numpy(dtype=np.int64)
    is_buy = (frame["side"] == "buy").to_numpy()
    if convention is SolAmountConvention.NET_OF_FEE:
        curve = reported
    else:
        denom = np.where(is_buy, 10_000 + fee_bps, 10_000 - fee_bps)
        curve = (reported.astype(object) * 10_000) // denom
        curve = np.array([int(v) for v in curve], dtype=np.int64)
    return np.where(is_buy, curve, -curve)


# --- §0.3 fee handling ----------------------------------------------------

def determine_convention(frame) -> dict:
    """§0.3 step 1: decide gross vs net from on-chain reserves.

    The virtual SOL reserve reported with each trade is the state *after* it.  So
    for consecutive trades of one token, `vsol_post[i+1] - vsol_post[i]` is
    exactly the SOL the curve took in or paid out.  Comparing that delta against
    the reported `sol_amount` decides the question with no assumptions: an exact
    match means the field is the curve amount (net of fee); a systematic ~1% gap
    with the fee's sign means it includes the fee.
    """
    evidence: dict[str, object] = {}
    token = frame["token_mint"].to_numpy()
    vsol = frame["vsol_post"].to_numpy(dtype=np.int64)
    same_token = token[1:] == token[:-1]
    delta = (vsol[1:] - vsol[:-1])[same_token]

    for convention in SolAmountConvention:
        signed = signed_curve_lamports(frame, convention)[1:][same_token]
        residual = delta - signed
        evidence[convention.value] = {
            "n_pairs": int(residual.size),
            "exact_match_share": float(np.mean(residual == 0)) if residual.size else float("nan"),
            "within_1_lamport_share": float(np.mean(np.abs(residual) <= 1)) if residual.size else float("nan"),
            "median_abs_residual_sol": float(np.median(np.abs(residual)) / LAMPORTS_PER_SOL) if residual.size else float("nan"),
            "median_residual_bps_of_amount": float(
                np.median(residual / np.maximum(np.abs(signed), 1)) * 10_000
            ) if residual.size else float("nan"),
        }

    # first-trade evidence: does the very first observed trade start from x0?
    first = frame.groupby("token_mint", sort=False).head(1)
    implied_x0 = {
        c: first["vsol_post"].to_numpy(dtype=np.int64) - signed_curve_lamports(first, c)
        for c in SolAmountConvention
    }
    evidence["first_trade_implied_x0"] = {
        "n_tokens": int(implied_x0[SolAmountConvention.NET_OF_FEE].size),
        "share_equal_x0_30_SOL": float(np.mean(implied_x0[SolAmountConvention.NET_OF_FEE] == X0_LAMPORTS)),
        "median_implied_x0_sol": float(np.median(implied_x0[SolAmountConvention.NET_OF_FEE]) / LAMPORTS_PER_SOL),
        "median_implied_x0_sol_gross_hypothesis": float(
            np.median(implied_x0[SolAmountConvention.GROSS_INCLUDES_FEE]) / LAMPORTS_PER_SOL
        ),
    }
    first_y = first["vtoken_post"].to_numpy(dtype=np.int64) + np.where(
        (first["side"] == "buy").to_numpy(),
        first["token_units"].to_numpy(dtype=np.int64),
        -first["token_units"].to_numpy(dtype=np.int64),
    )
    evidence["first_trade_implied_y0"] = {
        "share_equal_spec_y0": float(np.mean(first_y == Y0_UNITS)),
        "median_implied_y0_tokens": float(np.median(first_y) / TOKEN_UNITS_PER_TOKEN),
        "spec_y0_tokens": Y0_UNITS / TOKEN_UNITS_PER_TOKEN,
    }

    # reported fee column, when the source has one
    fee = frame["fee_lamports"].to_numpy(dtype=np.int64)
    reported = frame["sol_lamports"].to_numpy(dtype=np.int64)
    nonzero = fee > 0
    evidence["reported_fee_column"] = {
        "share_nonzero": float(np.mean(nonzero)),
        "median_bps_of_sol_amount": float(
            np.median(fee[nonzero] / np.maximum(reported[nonzero], 1)) * 10_000
        ) if nonzero.any() else None,
    }

    net = evidence[SolAmountConvention.NET_OF_FEE.value]
    gross = evidence[SolAmountConvention.GROSS_INCLUDES_FEE.value]
    if net["within_1_lamport_share"] >= 0.99:
        chosen = SolAmountConvention.NET_OF_FEE
    elif gross["within_1_lamport_share"] >= 0.99:
        chosen = SolAmountConvention.GROSS_INCLUDES_FEE
    else:
        chosen = None

    return {
        "convention": chosen.value if chosen else None,
        "decided": chosen is not None,
        "evidence": evidence,
    }


def cmd_fee(args: argparse.Namespace) -> None:
    frame = load_events(limit_tokens=args.tokens)
    result = determine_convention(frame)
    FEE_JSON.parent.mkdir(parents=True, exist_ok=True)
    FEE_JSON.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    append_test_log(
        "§0.3 fee convention from on-chain reserve deltas",
        f"{result['convention'] or 'UNDECIDED'} ({len(frame):,} events)",
    )
    if not result["decided"]:
        raise SystemExit(
            "§0.3 undecided: neither convention reproduces the reserve deltas. "
            "Do not proceed — reconstruction would be unverifiable."
        )


def read_convention() -> SolAmountConvention:
    if not FEE_JSON.exists():
        raise SystemExit("run `validate_phase0 fee` first (§0.3 step 1)")
    value = json.loads(FEE_JSON.read_text())["convention"]
    if value is None:
        raise SystemExit("§0.3 undecided; refusing to reconstruct")
    return SolAmountConvention(value)


# --- checks 1–6 -----------------------------------------------------------

def _text_histogram(values: np.ndarray, edges: list[float], unit: str) -> str:
    lines = [f"| bucket ({unit}) | events | share |", "|---|---|---|"]
    total = values.size
    lo = -np.inf
    for edge in edges + [np.inf]:
        n = int(np.sum((values > lo) & (values <= edge)))
        label = f"<= {edge:g}" if lo == -np.inf else (f"> {lo:g}" if edge == np.inf else f"({lo:g}, {edge:g}]")
        lines.append(f"| {label} | {n:,} | {n / total:.4%} |")
        lo = edge
    return "\n".join(lines)


def check1_reconstruction(frame, convention) -> tuple[CheckResult, np.ndarray]:
    """Cumulative replay from x0 vs on-chain virtual SOL reserve."""
    errors = np.empty(len(frame), dtype=np.float64)
    first_bad_token: dict[str, int] = {}
    idx = 0
    for mint, group in frame.groupby("token_mint", sort=False):
        state = CurveState()
        for row in group.itertuples(index=False):
            event = CurveEvent(
                int(row.slot), int(row.tx_index), int(row.ix_index),
                Side(row.side), int(row.sol_lamports), int(row.token_units),
            )
            try:
                rec = state.apply(event, convention)
                err = abs(rec.x_post - int(row.vsol_post))
            except Exception:                      # curve violation: unusable event
                err = np.inf
                state.x = int(row.vsol_post)       # resync so later events stay readable
                state.y = int(row.vtoken_post)
            errors[idx] = err / LAMPORTS_PER_SOL
            if err > X_TOLERANCE_SOL * LAMPORTS_PER_SOL and mint not in first_bad_token:
                first_bad_token[mint] = idx
            idx += 1

    within = float(np.mean(errors <= X_TOLERANCE_SOL))
    summary = stats.describe(errors[np.isfinite(errors)])
    detail = (
        f"share of events within {X_TOLERANCE_SOL} SOL: **{within:.4%}** "
        f"(threshold >{X_TOLERANCE_SHARE:.0%})\n\n"
        f"|x_post_reconstructed − x_post_onchain| in SOL: {summary.line('SOL')}\n\n"
        + _text_histogram(errors, [0, 1e-9, 1e-6, 1e-3, 0.01, 0.1, 1.0], "SOL abs error")
        + f"\n\ntokens with at least one out-of-tolerance event: "
        f"{len(first_bad_token):,} of {frame['token_mint'].nunique():,}"
    )
    return CheckResult(1, "Reconstructed x_post vs on-chain state", within > X_TOLERANCE_SHARE, detail), errors


def check2_price(frame, convention) -> CheckResult:
    """Curve-implied average price vs realised sol_amount / token_amount.

    Uses the *local* pre-trade state (on-chain post state minus this trade), so
    the check is independent of check 1's cumulative replay: it tests the AMM
    formula itself, not the accumulation.
    """
    signed = signed_curve_lamports(frame, convention)
    token_units = frame["token_units"].to_numpy(dtype=np.int64)
    is_buy = (frame["side"] == "buy").to_numpy()
    x_post = frame["vsol_post"].to_numpy(dtype=np.float64)
    y_post = frame["vtoken_post"].to_numpy(dtype=np.float64)
    x_pre = x_post - signed
    y_pre = y_post + np.where(is_buy, token_units, -token_units)

    q_sol = np.abs(signed) / LAMPORTS_PER_SOL
    tokens = token_units / TOKEN_UNITS_PER_TOKEN
    realised = np.divide(q_sol, tokens, out=np.full_like(q_sol, np.nan), where=tokens > 0)

    x_pre_sol, y_pre_tok = x_pre / LAMPORTS_PER_SOL, y_pre / TOKEN_UNITS_PER_TOKEN
    y_post_tok = y_post / TOKEN_UNITS_PER_TOKEN
    # buy:  avg = (x_pre + q) / y_pre        sell: avg = x_pre / (y_pre + Δ)
    predicted = np.where(is_buy, (x_pre_sol + q_sol) / y_pre_tok, x_pre_sol / y_post_tok)
    rel = np.abs(realised - predicted) / predicted
    rel = rel[np.isfinite(rel)]

    within = float(np.mean(rel <= PRICE_REL_TOLERANCE))
    detail = (
        f"share of events within {PRICE_REL_TOLERANCE:.2%} relative price error: "
        f"**{within:.4%}**\n\n"
        f"relative error: {stats.describe(rel).line()}\n\n"
        + _text_histogram(rel, [1e-9, 1e-6, 1e-4, 0.005, 0.01, 0.02], "relative error")
    )
    return CheckResult(2, "Curve price vs realised sol/token", within > X_TOLERANCE_SHARE, detail)


def check3_universe() -> CheckResult:
    ch = client()
    total, migrated, sampled = ch.query(
        f"SELECT count(), sum(migrated), sum(in_sample) FROM {config.CH_DATABASE}.token"
    ).result_rows[0]
    thin = ch.query(
        f"SELECT countIf(n <= 5), countIf(n = 0) FROM ("
        f"  SELECT t.token_mint, count(e.token_mint) n FROM {config.CH_DATABASE}.token t "
        f"  LEFT JOIN {config.CH_DATABASE}.event e ON e.token_mint = t.token_mint "
        f"  GROUP BY t.token_mint)"
    ).result_rows[0]
    non_migrated = total - (migrated or 0)
    detail = (
        f"tokens in dev universe: **{total:,}**\n\n"
        f"| cohort | tokens | share |\n|---|---|---|\n"
        f"| migrated | {migrated or 0:,} | {(migrated or 0) / max(total, 1):.2%} |\n"
        f"| never migrated | {non_migrated:,} | {non_migrated / max(total, 1):.2%} |\n"
        f"| <= 5 trades (dead on arrival) | {thin[0]:,} | {thin[0] / max(total, 1):.2%} |\n"
        f"| zero trades | {thin[1]:,} | {thin[1] / max(total, 1):.2%} |\n\n"
        "Universe is selected on creation time only; migration is a column, never a filter."
    )
    passed = non_migrated > 0 and thin[0] > 0
    return CheckResult(3, "Universe defined by launch, not migration", passed, detail)


def check4_daily_counts() -> CheckResult:
    ch = client()
    rows = ch.query(
        f"SELECT toDate(block_time) d, count() n, uniqExact(token_mint) t "
        f"FROM {config.CH_DATABASE}.event GROUP BY d ORDER BY d"
    ).result_rows
    launches = dict(ch.query(
        f"SELECT toDate(created_at) d, count() FROM {config.CH_DATABASE}.token GROUP BY d"
    ).result_rows)
    counts = np.array([r[1] for r in rows], dtype=float)
    # Boundary days are partial by construction (window edges), so the stability
    # band is judged on interior days only.
    interior = counts[1:-1] if counts.size > 2 else counts
    med = float(np.median(interior))
    ratios = interior / med
    bad = int(np.sum((ratios < DAILY_COUNT_BAND[0]) | (ratios > DAILY_COUNT_BAND[1])))
    table = ["| day | events | tokens traded | launches | ratio to median |", "|---|---|---|---|---|"]
    for day, n, t in rows:
        table.append(f"| {day} | {n:,} | {t:,} | {launches.get(day, 0):,} | {n / med:.2f} |")
    detail = (
        f"median interior day: {med:,.0f} events; days outside "
        f"[{DAILY_COUNT_BAND[0]}x, {DAILY_COUNT_BAND[1]}x] band: **{bad}**\n\n"
        + "\n".join(table)
    )
    return CheckResult(4, "Daily event counts stable (no missing data)", bad == 0, detail)


def check5_continuity(frame, convention) -> CheckResult:
    """Per-event continuity of on-chain reserves within each token.

    The stored `x_post -> next x_pre` chain is an identity of the additive replay
    and so proves nothing on its own; it is asserted separately below.  The
    informative version is whether *on-chain* reserves move by exactly the
    reported trade amount from one event to the next, which is what a missing
    event breaks.
    """
    token = frame["token_mint"].to_numpy()
    vsol = frame["vsol_post"].to_numpy(dtype=np.int64)
    signed = signed_curve_lamports(frame, convention)
    same = token[1:] == token[:-1]
    residual = (vsol[1:] - vsol[:-1] - signed[1:])[same]
    exact = float(np.mean(residual == 0))
    near = float(np.mean(np.abs(residual) <= 1))

    stored_ok = True
    stored_bad = 0
    x_pre = frame["x_pre_lamports"].to_numpy(dtype=np.int64)
    x_post = frame["x_post_lamports"].to_numpy(dtype=np.int64)
    if x_post.size > 1:
        broken = (x_post[:-1] != x_pre[1:])[same]
        stored_bad = int(np.sum(broken))
        stored_ok = stored_bad == 0

    detail = (
        f"on-chain reserve continuity: exact **{exact:.4%}**, within 1 lamport {near:.4%} "
        f"({residual.size:,} consecutive pairs)\n\n"
        f"stored x_post[i] == x_pre[i+1] within token: "
        f"{'holds for all pairs' if stored_ok else f'{stored_bad:,} breaks'}\n\n"
        f"residual (lamports): {stats.describe(np.abs(residual)).line('lamports')}"
    )
    return CheckResult(5, "x_post chains into next x_pre", near > X_TOLERANCE_SHARE and stored_ok, detail)


def check6_fee_documented(convention) -> CheckResult:
    payload = json.loads(FEE_JSON.read_text())
    ev = payload["evidence"]
    net = ev[SolAmountConvention.NET_OF_FEE.value]
    gross = ev[SolAmountConvention.GROSS_INCLUDES_FEE.value]
    detail = (
        f"**step 1 — determined from data.** On-chain reserve deltas vs reported "
        f"`sol_amount`, {net['n_pairs']:,} consecutive pairs:\n\n"
        f"| hypothesis | exact match | within 1 lamport | median abs residual |\n|---|---|---|---|\n"
        f"| net of fee | {net['exact_match_share']:.4%} | {net['within_1_lamport_share']:.4%} | "
        f"{net['median_abs_residual_sol']:.3g} SOL |\n"
        f"| gross (fee included) | {gross['exact_match_share']:.4%} | "
        f"{gross['within_1_lamport_share']:.4%} | {gross['median_abs_residual_sol']:.3g} SOL |\n\n"
        f"reported fee column non-zero on {ev['reported_fee_column']['share_nonzero']:.2%} of events"
        + (f", median {ev['reported_fee_column']['median_bps_of_sol_amount']:.1f} bps of `sol_amount`"
           if ev['reported_fee_column']['median_bps_of_sol_amount'] is not None else "")
        + f"\n\nfirst trade of each token implies x0 = 30 SOL on "
        f"{ev['first_trade_implied_x0']['share_equal_x0_30_SOL']:.2%} of tokens "
        f"(median implied x0 = {ev['first_trade_implied_x0']['median_implied_x0_sol']:.9g} SOL)\n\n"
        f"implied y0 equals the §1.1 value on "
        f"{ev['first_trade_implied_y0']['share_equal_spec_y0']:.2%} of tokens "
        f"(median implied y0 = {ev['first_trade_implied_y0']['median_implied_y0_tokens']:,.0f} tokens; "
        f"§1.1 states {ev['first_trade_implied_y0']['spec_y0_tokens']:,.0f})\n\n"
        f"**step 2 — written down.** `results/fee_convention.json` and this report: "
        f"`sol_amount` is treated as **{convention.value}**.\n\n"
        f"**step 3 — reconstruction verified against it.** Check 1 replays every event "
        f"under exactly this convention; the ~1% systematic drift the wrong choice "
        f"produces is what checks 1 and 5 above would have caught."
    )
    return CheckResult(6, "Fee handling determined and documented (§0.3)", payload["decided"], detail)


def float_drift(frame, convention) -> str:
    """§0.4: measure the floating-point error the integer path avoids."""
    counts = frame["token_mint"].value_counts()
    mint = counts.index[0]
    group = frame[frame["token_mint"] == mint]
    exact, approx = CurveState(), FloatCurveState()
    worst = 0.0
    for row in group.itertuples(index=False):
        event = CurveEvent(int(row.slot), int(row.tx_index), int(row.ix_index),
                           Side(row.side), int(row.sol_lamports), int(row.token_units))
        try:
            rec = exact.apply(event, convention)
        except Exception:
            break
        approx.apply(event, convention)
        worst = max(worst, abs(approx.x - float(lamports_to_sol(rec.x_post))))
    return (
        f"Longest token in the dev set has **{int(counts.iloc[0]):,}** events "
        f"(`{mint}`).  Replaying it in float64 SOL instead of integer lamports "
        f"accumulates at most **{worst:.3g} SOL** of error against the exact integer "
        f"path — {'below' if worst < X_TOLERANCE_SOL else 'ABOVE'} check 1's "
        f"{X_TOLERANCE_SOL} SOL tolerance by a factor of "
        f"{X_TOLERANCE_SOL / worst:,.0f}x.\n\n"
        f"Conclusion: money is nonetheless carried as integer base units throughout "
        f"`curve.py`, which is *exact at any length* (`x = x0 + Σ signed amounts`, "
        f"verified with zero tolerance in `tests/test_curve.py`), so no accumulated "
        f"error enters any later phase. `Decimal` is used only for human-unit output."
        if worst > 0 else "Drift measurement produced no comparable events."
    )


def cmd_checks(args: argparse.Namespace) -> None:
    convention = read_convention()
    frame = load_events(limit_tokens=args.tokens)
    print(f"loaded {len(frame):,} events, {frame['token_mint'].nunique():,} tokens")

    c1, errors = check1_reconstruction(frame, convention)
    results = [
        c1,
        check2_price(frame, convention),
        check3_universe(),
        check4_daily_counts(),
        check5_continuity(frame, convention),
        check6_fee_documented(convention),
    ]
    drift = float_drift(frame, convention)
    write_report(results, drift, frame, convention)

    print()
    for r in results:
        print(f"  check {r.number}: {r.verdict}  {r.name}")
        append_test_log(f"check {r.number} — {r.name}", r.verdict)
    if not results[0].passed:
        print("\nKILL CRITERION HIT: check 1 FAILED. Stop here; do not start Phase 1.")
        raise SystemExit(1)
    print(f"\nreport -> {REPORT}")


def write_report(results, drift: str, frame, convention) -> None:
    ch = client()
    tokens, events = ch.query(
        f"SELECT uniqExact(token_mint), count() FROM {config.CH_DATABASE}.event"
    ).result_rows[0]
    holdout_files = sorted(config.HOLDOUT.glob("*.parquet"))
    holdout_note = (
        "\n".join(f"- `{p.name}` — {p.stat().st_size / 1e6:,.1f} MB" for p in holdout_files)
        or "- (no holdout files written yet)"
    )
    overall = all(r.passed for r in results)
    body = [
        "# Phase 0 report — data and unit checks",
        "",
        f"Generated {date.today().isoformat()} · spec v1.1 §7 Phase 0 · "
        f"`sol_amount` convention: **{convention.value}**",
        "",
        "## Verdict",
        "",
        "| # | check | verdict |",
        "|---|---|---|",
        *[f"| {r.number} | {r.name} | **{r.verdict}** |" for r in results],
        "",
        f"**Phase 0: {'PASS' if overall else 'FAIL'}**"
        + ("" if overall else "  — see the failing checks below before any Phase 1 work."),
        "",
        f"Kill criterion (check 1): **{results[0].verdict}**.",
        "",
        "## Universe",
        "",
        "```",
        config.summary(),
        "```",
        "",
        f"Events loaded into ClickHouse (dev only): **{events:,}** across **{tokens:,}** tokens.",
        "",
        "## Holdout isolation (§6.1)",
        "",
        f"Holdout tokens are created in [{config.HOLDOUT_START.date()}, {config.T_END.date()}) "
        f"and live only in `data/holdout/`:",
        "",
        holdout_note,
        "",
        f"`load_clickhouse.load` refuses any path under `data/holdout/`, and every row in "
        f"ClickHouse carries `split='dev'`.",
        "",
        "## §0.4 floating-point accumulation",
        "",
        drift,
        "",
        "## Checks",
        "",
    ]
    for r in results:
        body += [f"### Check {r.number} — {r.name}: {r.verdict}", "", r.detail, ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(body) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("fee", "checks"):
        p = sub.add_parser(name)
        p.add_argument("--tokens", type=int, default=None,
                       help="restrict to the N busiest tokens (debugging only)")
    args = parser.parse_args()
    {"fee": cmd_fee, "checks": cmd_checks}[args.cmd](args)


if __name__ == "__main__":
    main()
