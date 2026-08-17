"""Dune ingestion — spec §2.1, §2.2, §2.3, Phase 0.1/0.2.

  python -m src.ingest_dune raw --sql "..."   capped ad-hoc statement (probing)
  python -m src.ingest_dune discover          sample both tables, record schema
  python -m src.ingest_dune estimate          §0.1 size / credit / disk estimate

Credit discipline (Free plan: 2,500 credits/month, exports 20 credits/MB)
------------------------------------------------------------------------
Execution is billed by *compute time*, roughly 6 credits per minute, and export
is billed per MB retrieved.  Two consequences shape every query in this file:

  1. Aggregate server-side and retrieve almost nothing.  The §0.1 estimate reads
     `total_result_set_bytes` out of the execution *status* — measuring what a
     pull would cost without paying to retrieve it.
  2. Cap every execution.  A query left running to Dune's 30-minute timeout costs
     ~180 credits and returns nothing; that is not a hypothetical, it happened
     (execution 01M07JF0M1YYQY96WY68Q7XV0Q, logged in results/dune_usage.jsonl).

Every execution's authoritative `execution_cost_credits` is appended to
results/dune_usage.jsonl, so the credit story is auditable rather than estimated.

Observed schema (probed 2026-08-17, not remembered — see results/dune_schema.txt)
--------------------------------------------------------------------------------
`pumpdotfun_solana.pump_evt_tradeevent` is a union across program versions: the
old program filled camelCase columns (`solAmount`, `virtualSolReserves`), the
current one fills snake_case (`sol_amount`, `virtual_sol_reserves`, `fee`,
`fee_basis_points`, `creator_fee`, `quote_mint`, `mayhem_mode`).  In the study
window 100% of rows are the snake_case form, so this module reads those columns
directly; a version-mix assertion in `estimate` fails loudly if that stops being
true for a window someone runs later.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

SQL_DIR = config.REPO / "sql"
QUERY_IDS = SQL_DIR / "query_ids.json"
USAGE_LOG = config.RESULTS / "dune_usage.jsonl"

TRADES = "pumpdotfun_solana.pump_evt_tradeevent"
CREATES = "pumpdotfun_solana.pump_evt_createevent"
COMPLETES = "pumpdotfun_solana.pump_evt_completeevent"
MIGRATIONS = "pumpdotfun_solana.pump_evt_completepumpammmigrationevent"

#: pump.fun records native-SOL curves with the system program as quote mint.
#: USDC-quoted curves also exist and are *not* SOL-denominated, so the SOL-only
#: filter below is a unit-of-account filter, not an activity filter — it cannot
#: introduce survivorship (spec §2.2).
SOL_QUOTE_MINT = "11111111111111111111111111111111"
USDC_QUOTE_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

CREDITS_PER_MB = {"free": 20, "analyst": 10, "plus": 2}
MONTHLY_CREDITS = {"free": 2_500, "analyst": 4_000, "plus": 25_000}


def api_key() -> str:
    key = os.environ.get("DUNE_API_KEY")
    if not key:
        env = config.REPO / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                line = line.strip()
                if line.startswith("DUNE_API_KEY"):
                    key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        raise SystemExit(
            "DUNE_API_KEY not found. Put it in .env as DUNE_API_KEY=... "
            "(.env is gitignored) or export it."
        )
    return key


class Dune:
    def __init__(self, performance: str = config.DUNE_PERFORMANCE) -> None:
        self.session = requests.Session()
        self.session.headers["X-Dune-API-Key"] = api_key()
        self.performance = performance
        self.usage: list[dict[str, Any]] = []

    def _request(self, method: str, path: str, **kw) -> Any:
        for attempt in range(6):
            resp = self.session.request(method, f"{config.DUNE_API}{path}", timeout=120, **kw)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if not resp.ok:
                raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")
            return resp.json()
        raise RuntimeError(f"{method} {path}: rate limited after retries")

    def ensure_query(self, name: str, sql: str) -> int:
        """Return a saved-query id for `sql`, creating or updating as needed.

        Dune has no ad-hoc-SQL endpoint, so each logical query is one saved query
        that gets PATCHed in place.  Ids live in sql/query_ids.json (committed:
        they are provenance for which query produced which data, not secrets).
        """
        ids = json.loads(QUERY_IDS.read_text()) if QUERY_IDS.exists() else {}
        if name in ids:
            qid = int(ids[name])
            try:
                self._request("PATCH", f"/query/{qid}", json={"query_sql": sql})
            except RuntimeError as exc:
                print(f"  ! could not update query {qid} ({exc.args[0][:80]}); "
                      "executing the version already saved on Dune", file=sys.stderr)
            return qid
        created = self._request(
            "POST", "/query",
            json={"name": f"[flow-research] {name}", "query_sql": sql,
                  "is_private": True, "query_engine": "v2 Dune SQL"},
        )
        qid = int(created["query_id"])
        ids[name] = qid
        SQL_DIR.mkdir(parents=True, exist_ok=True)
        QUERY_IDS.write_text(json.dumps(ids, indent=2) + "\n")
        print(f"  created Dune query {qid} for {name}")
        return qid

    def run(self, name: str, sql: str, max_seconds: int = 240) -> dict[str, Any]:
        """Execute and wait, cancelling past `max_seconds` to bound the cost."""
        qid = self.ensure_query(name, sql)
        execution = self._request(
            "POST", f"/query/{qid}/execute", json={"performance": self.performance}
        )
        eid = execution["execution_id"]
        print(f"  {name}: execution {eid} (cap {max_seconds}s) ...", end="", flush=True)
        started = time.time()
        while True:
            status = self._request("GET", f"/execution/{eid}/status")
            state = status["state"]
            if state == "QUERY_STATE_COMPLETED":
                print(" done")
                return self._log_usage(name, eid, status)
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"):
                self._log_usage(name, eid, status, state=state)
                raise RuntimeError(
                    f"{name}: {state} after "
                    f"{status.get('execution_cost_credits', '?')} credits: "
                    f"{(status.get('error') or {}).get('message', status)}"
                )
            if time.time() - started > max_seconds:
                print(" CANCELLING (over time cap)")
                self._request("POST", f"/execution/{eid}/cancel")
                status = self._request("GET", f"/execution/{eid}/status")
                self._log_usage(name, eid, status, state="CANCELLED_BY_BUDGET")
                raise RuntimeError(
                    f"{name}: cancelled after {max_seconds}s to protect the credit "
                    f"budget (cost so far {status.get('execution_cost_credits', '?')} "
                    "credits). Narrow the query before retrying."
                )
            print(".", end="", flush=True)
            time.sleep(3)

    def _log_usage(self, name: str, eid: str, status: dict[str, Any],
                   state: str = "COMPLETED") -> dict[str, Any]:
        meta = status.get("result_metadata") or {}
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "query": name,
            "execution_id": eid,
            "state": state,
            "execution_cost_credits": status.get("execution_cost_credits"),
            "rows": meta.get("total_row_count"),
            "bytes": meta.get("total_result_set_bytes"),
            "datapoints": meta.get("datapoint_count"),
            "columns": len(meta.get("column_names") or []),
            "column_names": meta.get("column_names"),
            "execution_ms": meta.get("execution_time_millis"),
        }
        self.usage.append(record)
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        cost = record["execution_cost_credits"]
        cost_str = f"{cost:,.2f}" if isinstance(cost, (int, float)) else "?"
        if record["rows"] is not None:
            print(f"    rows={record['rows']:,} bytes={_mb(record['bytes'])} "
                  f"cost={cost_str} credits")
        else:
            print(f"    no result metadata; cost={cost_str} credits")
        return record

    def rows(self, eid: str, page: int = 25_000, max_rows: int | None = None
             ) -> Iterator[dict[str, Any]]:
        """Stream rows of a completed execution.  Every row retrieved costs credits."""
        offset = 0
        while True:
            payload = self._request(
                "GET", f"/execution/{eid}/results",
                params={"limit": page, "offset": offset},
            )
            batch = payload.get("result", {}).get("rows", [])
            yield from batch
            offset += len(batch)
            if len(batch) < page or (max_rows is not None and offset >= max_rows):
                return

    def total_credits(self) -> float:
        return sum(u["execution_cost_credits"] or 0 for u in self.usage)


def _mb(n: int | None) -> str:
    return "?" if n is None else f"{n / 1e6:,.2f}MB"


def _d(dt) -> str:
    """Date literal for the partition column — pruning on `evt_block_date` is what
    keeps these scans at fractions of a credit."""
    return f"DATE '{dt.strftime('%Y-%m-%d')}'"


# --- SQL ------------------------------------------------------------------

def sql_cohort() -> str:
    """§0.1 — one row: cohort size, §4.1 burst counts, and both at each rate.

    A 3-day *launch cohort* followed for 7 days, so per-token histories are
    complete and `events / tokens_created` is a lifetime figure rather than a
    3-day slice.  Burst detection is §4.1's primary cell (net_flow_2s >=
    max(3 SOL, 0.10x)) with the "no burst active in the previous 10s" clause
    approximated by 10-second sessionisation of qualifying events; for a count
    estimate that is close enough, and it is stated as an approximation in the
    report rather than passed off as the real label.
    """
    rates = config.CANDIDATE_RATES
    frac = config.SAMPLE_SQL_FRACTION.format(mint="mint")
    ev_rate = ", ".join(f"count_if(frac < {q}) AS events_{int(q * 100)}" for q in rates)
    b_rate = ", ".join(f"count_if(frac < {q}) AS bursts_{int(q * 100)}" for q in rates)
    t_rate = ", ".join(f"count_if(frac < {q}) AS tokens_{int(q * 100)}" for q in rates)
    return f"""
WITH created AS (
    SELECT mint,
           min(evt_block_time) AS created_at,
           {frac} AS frac,
           bool_or(is_mayhem_mode) AS mayhem_at_launch,
           max(CAST(virtual_sol_reserves AS double)) / 1e9 AS x0_sol,
           max(CAST(virtual_token_reserves AS double)) / 1e6 AS y0_tokens
    FROM {CREATES}
    WHERE evt_block_date >= {_d(config.PROBE_START)}
      AND evt_block_date <  {_d(config.PROBE_END)}
      AND quote_mint = '{SOL_QUOTE_MINT}'
    GROUP BY mint, 3
),
ev AS (
    SELECT c.mint, c.frac, t.evt_block_time AS block_time,
           t.is_buy,
           CAST(t.sol_amount AS double) / 1e9 AS sol,
           (CAST(t.virtual_sol_reserves AS double)
              - (CASE WHEN t.is_buy THEN CAST(t.sol_amount AS double)
                      ELSE -CAST(t.sol_amount AS double) END)) / 1e9 AS x_pre,
           t.mayhem_mode
    FROM {TRADES} t
    JOIN created c ON t.mint = c.mint
    WHERE t.evt_block_date >= {_d(config.PROBE_START)}
      AND t.evt_block_date <  {_d(config.PROBE_TAIL_END)}
      AND t.quote_mint = '{SOL_QUOTE_MINT}'
),
flow AS (
    SELECT mint, frac, block_time, x_pre,
           sum(CASE WHEN is_buy THEN sol ELSE -sol END) OVER (
               PARTITION BY mint ORDER BY block_time
               RANGE BETWEEN INTERVAL '2' SECOND PRECEDING AND CURRENT ROW) AS net_2s
    FROM ev
),
qual AS (
    SELECT mint, frac, block_time,
           lag(block_time) OVER (PARTITION BY mint ORDER BY block_time) AS prev_q
    FROM flow
    WHERE net_2s >= greatest(3.0, 0.10 * x_pre)
),
bursts AS (
    SELECT mint, frac FROM qual
    WHERE prev_q IS NULL OR date_diff('second', prev_q, block_time) > 10
),
per_token AS (SELECT mint, count(*) AS n FROM ev GROUP BY 1),
e AS (SELECT count(*) AS events, count(DISTINCT mint) AS tokens_traded,
             count_if(mayhem_mode = true) AS mayhem_events, {ev_rate} FROM ev),
b AS (SELECT count(*) AS bursts, count(DISTINCT mint) AS burst_tokens, {b_rate} FROM bursts),
k AS (SELECT count(*) AS tokens_created,
             count_if(mayhem_at_launch) AS mayhem_tokens,
             count_if(x0_sol = 30.0) AS x0_is_30,
             count_if(y0_tokens = 1073000000.0) AS y0_is_1073000000,
             count_if(y0_tokens = 1073000191.0) AS y0_is_spec_value,
             {t_rate} FROM created),
d AS (SELECT approx_percentile(n, 0.5) AS ev_p50, approx_percentile(n, 0.9) AS ev_p90,
             approx_percentile(n, 0.99) AS ev_p99, max(n) AS ev_max,
             count_if(n <= 5) AS tokens_le5 FROM per_token)
SELECT * FROM e CROSS JOIN b CROSS JOIN k CROSS JOIN d
"""


def sql_projection(limit: int = 200_000) -> str:
    """The exact per-event projection pull (a) would retrieve, LIMITed.

    Executed only to measure bytes per row; rows are never fetched.  `x_pre` and
    `x_post` from §2.3 are absent by design — they are reconstructed locally, and
    downloading them would be paying for arithmetic.  The on-chain reserves take
    their place as the ground truth validation check 1 compares against.
    """
    return f"""
SELECT t.mint                        AS token_mint,
       t.evt_block_slot              AS slot,
       t.evt_block_time              AS block_time,
       t.evt_tx_index                AS tx_index,
       t.evt_outer_instruction_index AS outer_ix,
       t.evt_inner_instruction_index AS inner_ix,
       t.user                        AS wallet,
       t.is_buy                      AS is_buy,
       CAST(t.sol_amount AS varchar)             AS sol_amount,
       CAST(t.token_amount AS varchar)           AS token_amount,
       CAST(t.virtual_sol_reserves AS varchar)   AS vsol_post,
       CAST(t.virtual_token_reserves AS varchar) AS vtoken_post,
       CAST(t.fee AS varchar)                    AS fee,
       CAST(t.creator_fee AS varchar)            AS creator_fee
FROM {TRADES} t
WHERE t.evt_block_date >= {_d(config.PROBE_START)}
  AND t.evt_block_date <  {_d(config.PROBE_END)}
  AND t.quote_mint = '{SOL_QUOTE_MINT}'
LIMIT {limit}
"""


def sql_minute() -> str:
    """Pull (b) — market-wide per-minute aggregate for f10/f11.

    Sampling must never touch this: f10 (`mkt_active_bursts`) and f11
    (`mkt_total_flow`) are market-wide by definition, so they are computed over
    every token and only the per-minute aggregate is returned.  That is ~1,440
    rows per day instead of ~2.4M, which is why this pull is affordable at full
    coverage even when pull (a) is not.
    """
    sol = "CAST(sol_amount AS double)"
    return f"""
SELECT date_trunc('minute', evt_block_time) AS minute,
       count(*) AS trades,
       count(DISTINCT mint) AS active_tokens,
       sum({sol}) / 1e9 AS gross_flow_sol,
       sum(CASE WHEN is_buy THEN {sol} ELSE -{sol} END) / 1e9 AS net_flow_sol,
       count_if(mayhem_mode = true) AS mayhem_trades
FROM {TRADES}
WHERE evt_block_date >= {_d(config.PROBE_START)}
  AND evt_block_date <  {_d(config.PROBE_END)}
  AND quote_mint = '{SOL_QUOTE_MINT}'
GROUP BY 1
"""


def sql_parity() -> str:
    """Real mints with the SQL-side hash fraction, to prove the server-side sample
    filter is the same rule as the frozen Python one (requirement A)."""
    frac = config.SAMPLE_SQL_FRACTION.format(mint="mint")
    return f"""
SELECT mint, {frac} AS frac
FROM {CREATES}
WHERE evt_block_date = {_d(config.PROBE_START)}
  AND quote_mint = '{SOL_QUOTE_MINT}'
LIMIT 40
"""


def sql_quote_mix() -> str:
    """Unit-of-account split, for the report: how much of the venue is not SOL."""
    return f"""
SELECT quote_mint,
       count(*) AS trades,
       count(DISTINCT mint) AS mints,
       count_if(mayhem_mode = true) AS mayhem_trades,
       approx_percentile(CAST(fee_basis_points AS double), 0.5) AS fee_bps_p50,
       approx_percentile(CAST(creator_fee_basis_points AS double), 0.5) AS creator_bps_p50
FROM {TRADES}
WHERE evt_block_date >= {_d(config.PROBE_START)}
  AND evt_block_date <  {_d(config.PROBE_END)}
GROUP BY 1 ORDER BY 2 DESC
"""


# --- commands -------------------------------------------------------------

def cmd_raw(args: argparse.Namespace) -> None:
    sql = Path(args.file).read_text() if args.file else args.sql
    dune = Dune()
    meta = dune.run("adhoc_probe", sql, max_seconds=args.cap)
    for i, row in enumerate(dune.rows(meta["execution_id"], max_rows=args.limit)):
        if i >= args.limit:
            print(f"  ... ({meta['rows']:,} rows total)")
            break
        print("  " + json.dumps(row, default=str))


def cmd_discover(args: argparse.Namespace) -> None:
    """Record one sample row per table: column names, types and real values.

    `SHOW COLUMNS` returns nothing through the API and `information_schema` does
    not contain these decoded tables at all, so a one-row sample is the schema
    source of record.  Both dead ends are noted here so nobody pays for them again.
    """
    dune = Dune()
    out = config.RESULTS / "dune_schema.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for table in (TRADES, CREATES, COMPLETES, MIGRATIONS):
        try:
            meta = dune.run(
                "schema_discovery",
                f"SELECT * FROM {table} WHERE evt_block_date = {_d(config.PROBE_START)} LIMIT 1",
                max_seconds=120,
            )
            rows = list(dune.rows(meta["execution_id"], max_rows=1))
        except RuntimeError as exc:
            lines.append(f"\n=== {table}\n  ! {exc}")
            continue
        lines.append(f"\n=== {table}   ({len(rows[0]) if rows else 0} columns)")
        for key, value in sorted(rows[0].items()) if rows else []:
            shown = "NULL" if value is None else str(value)[:60]
            lines.append(f"  {key:<36} {shown}")
    out.write_text("\n".join(lines) + "\n")
    print(f"-> {out}   ({dune.total_credits():.2f} credits)")


def cmd_estimate(args: argparse.Namespace) -> None:
    """§0.1 — the four numbers, before anything is pulled."""
    from src.load_clickhouse import measure_row_bytes

    dune = Dune()
    cohort_meta = dune.run("phase0_cohort_probe", sql_cohort(), max_seconds=args.cap)
    cohort = next(iter(dune.rows(cohort_meta["execution_id"], max_rows=1)))
    proj_meta = dune.run("phase0_projection_probe", sql_projection(), max_seconds=args.cap)
    minute_meta = dune.run("phase0_minute_probe", sql_minute(), max_seconds=args.cap)
    parity_meta = dune.run("phase0_hash_parity", sql_parity(), max_seconds=120)
    parity_rows = list(dune.rows(parity_meta["execution_id"], max_rows=40))
    quote_meta = dune.run("phase0_quote_mix", sql_quote_mix(), max_seconds=args.cap)
    quote_rows = list(dune.rows(quote_meta["execution_id"], max_rows=10))

    mismatches = [
        (row["mint"], float(row["frac"]), float(config.mint_hash_fraction(row["mint"])))
        for row in parity_rows
        if abs(float(row["frac"]) - float(config.mint_hash_fraction(row["mint"]))) > 1e-9
    ]
    parity_ok = bool(parity_rows) and not mismatches
    print(f"\nmint-hash parity (SQL vs Python) on {len(parity_rows)} mints: "
          f"{'MATCH' if parity_ok else f'MISMATCH e.g. {mismatches[:2]}'}")

    scale = 90 / config.PROBE_DAYS
    disk = measure_row_bytes()
    events_probe = int(cohort["events"])
    bytes_per_event = proj_meta["bytes"] / max(proj_meta["rows"], 1)
    minute_rows_90d = int(minute_meta["rows"] * scale)
    bytes_per_minute_row = minute_meta["bytes"] / max(minute_meta["rows"], 1)
    minute_mb_90d = minute_rows_90d * bytes_per_minute_row / 1e6

    est = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "probe_window": [str(config.PROBE_START.date()), str(config.PROBE_END.date())],
        "probe_tail_end": str(config.PROBE_TAIL_END.date()),
        "probe_days": config.PROBE_DAYS,
        "scale_to_90d": scale,
        "probe": {k: (int(v) if isinstance(v, (int, float)) and float(v).is_integer() else v)
                  for k, v in cohort.items()},
        "quote_mix": quote_rows,
        "tokens_created_90d": int(cohort["tokens_created"] * scale),
        "events_90d": int(events_probe * scale),
        "bursts_90d": int(cohort["bursts"] * scale),
        "bytes_per_event_dune": bytes_per_event,
        "projection_rows_probe": proj_meta["rows"],
        "projection_bytes_probe": proj_meta["bytes"],
        "minute_rows_90d": minute_rows_90d,
        "bytes_per_minute_row": bytes_per_minute_row,
        "minute_mb_90d": minute_mb_90d,
        "minute_credits_90d": minute_mb_90d * CREDITS_PER_MB["free"],
        "clickhouse_bytes_per_row": disk["compressed_bytes_per_row"],
        "disk_measurement": disk,
        "parity_ok": parity_ok,
        "credits_spent_on_estimate": dune.total_credits(),
        "executions": dune.usage,
        "per_rate": {},
    }

    for rate in (Decimal(1), *config.CANDIDATE_RATES):
        pct = int(rate * 100)
        events = est["events_90d"] if pct == 100 else int(cohort[f"events_{pct}"] * scale)
        bursts = est["bursts_90d"] if pct == 100 else int(cohort[f"bursts_{pct}"] * scale)
        tokens = est["tokens_created_90d"] if pct == 100 else int(cohort[f"tokens_{pct}"] * scale)
        mb_a = events * bytes_per_event / 1e6
        credits = (mb_a + minute_mb_90d) * CREDITS_PER_MB["free"]
        est["per_rate"][f"{float(rate):.2f}"] = {
            "tokens": tokens,
            "events": events,
            "bursts": bursts,
            "pull_a_mb": mb_a,
            "pull_a_credits": mb_a * CREDITS_PER_MB["free"],
            "pull_b_mb": minute_mb_90d,
            "total_credits": credits,
            "share_of_monthly": credits / MONTHLY_CREDITS["free"],
            "months_of_budget": credits / MONTHLY_CREDITS["free"],
            "clickhouse_gb": events * disk["compressed_bytes_per_row"] / 1e9,
        }

    reserve = 400        # credits kept for executions, re-runs and validation
    budget_mb = (MONTHLY_CREDITS["free"] - reserve) / CREDITS_PER_MB["free"]
    mb_full = est["events_90d"] * bytes_per_event / 1e6
    est["budget_mb_after_reserve"] = budget_mb
    est["affordable_rate"] = max(0.0, (budget_mb - minute_mb_90d) / mb_full)

    out = config.RESULTS / "phase0_size_estimate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(est, indent=2, default=str) + "\n")
    _print_estimate(est)
    print(f"\nfull numbers -> {out}")
    print(f"credits spent producing this estimate: {dune.total_credits():.2f}")


def _print_estimate(est: dict) -> None:
    p, rates = est["probe"], est["per_rate"]
    full = rates["1.00"]
    print(f"\n=== §0.1 estimate — {est['probe_days']}-day launch cohort "
          f"({est['probe_window'][0]} to {est['probe_window'][1]}, followed to "
          f"{est['probe_tail_end']}), scaled x{est['scale_to_90d']:.0f} ===\n")
    print(f"probe cohort: {p['tokens_created']:,} tokens created "
          f"({p['mayhem_tokens']:,} mayhem-mode), {p['events']:,} events, "
          f"{p['bursts']:,} bursts")
    print(f"              events/token p50={p['ev_p50']:,.0f} p90={p['ev_p90']:,.0f} "
          f"p99={p['ev_p99']:,.0f} max={p['ev_max']:,.0f}; "
          f"{p['tokens_le5']:,} tokens with <=5 trades")
    print(f"              initial reserves: x0=30 SOL on {p['x0_is_30']:,} tokens, "
          f"y0=1,073,000,000 on {p['y0_is_1073000000']:,}, "
          f"y0=spec's 1,073,000,191 on {p['y0_is_spec_value']:,}")
    print(f"\n1. 90-day universe:  {est['tokens_created_90d']:,} tokens, "
          f"{est['events_90d']:,} events")
    print(f"   pull (a) sampled events : {full['pull_a_mb']:,.0f} MB at 100%")
    print(f"   pull (b) market minutes : {est['minute_mb_90d']:,.1f} MB "
          f"({est['minute_rows_90d']:,} rows, always full coverage)")
    print(f"2. credits at 20/MB: {full['total_credits']:,.0f} = "
          f"{full['share_of_monthly']:,.0%} of one month's 2,500 "
          f"({full['months_of_budget']:,.0f} months of budget)")
    print(f"3. ClickHouse disk: {full['clickhouse_gb']:,.1f} GB at 100% "
          f"({est['clickhouse_bytes_per_row']:.0f} compressed bytes/row, measured)")
    print("4. bursts in the primary cell (0.10x, tau=5s):\n")
    print("   | rate | tokens | events | bursts | pull(a) MB | credits | % of monthly | disk |")
    print("   |---|---|---|---|---|---|---|---|")
    for key, row in rates.items():
        print(f"   | {float(key):.0%} | {row['tokens']:,} | {row['events']:,} | "
              f"**{row['bursts']:,}** | {row['pull_a_mb']:,.0f} | "
              f"{row['total_credits']:,.0f} | {row['share_of_monthly']:,.0%} | "
              f"{row['clickhouse_gb']:,.1f} GB |")
    print(f"\n   largest rate fitting {est['budget_mb_after_reserve']:,.0f} MB "
          f"(2,500 credits minus a 400 reserve): {est['affordable_rate']:.3%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    est = sub.add_parser("estimate")
    est.add_argument("--cap", type=int, default=420, help="seconds before cancelling")
    raw = sub.add_parser("raw")
    raw.add_argument("--sql")
    raw.add_argument("--file")
    raw.add_argument("--cap", type=int, default=120)
    raw.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    {"discover": cmd_discover, "estimate": cmd_estimate, "raw": cmd_raw}[args.cmd](args)


if __name__ == "__main__":
    main()
