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
        """One API call, retrying rate limits and transient network faults.

        A read timeout on a `/execution/{id}/status` poll used to abort the whole
        run (chunk 3, 2026-08-18) even though the execution was still running on
        Dune's side — and re-running from scratch would have paid for it twice.
        Timeouts are therefore retried like 429s; only the request is repeated,
        never the execution.

        `ChunkedEncodingError` is in the list for the same reason and at a higher
        price: a truncated response body killed chunk 6's export after Dune had
        already billed the first 25k-row page, and every page has to be paid for
        again on a fresh fetch.  Callers that page results should also persist
        each page as it arrives — see the note in `rows`.
        """
        last: Exception | None = None
        for attempt in range(6):
            try:
                resp = self.session.request(
                    method, f"{config.DUNE_API}{path}", timeout=120, **kw)
            except (requests.Timeout, requests.ConnectionError,
                    requests.exceptions.ChunkedEncodingError) as exc:
                last = exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if not resp.ok:
                raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")
            return resp.json()
        raise RuntimeError(f"{method} {path}: giving up after retries ({last})")

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
        """Stream rows of a completed execution.  Every row retrieved costs credits.

        Because each page is billed on arrival and re-fetching pays again, a
        caller exporting a large result should write pages to disk as they come
        in and resume from the row count already on disk, rather than holding
        them in memory where a mid-export failure discards paid-for data.
        """
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


def _cohort_cte() -> str:
    """The §0.1 probe cohort, reused by every measurement so they are comparable."""
    frac = config.SAMPLE_SQL_FRACTION.format(mint="mint")
    return f"""
created AS (
    SELECT mint,
           min(evt_block_time) AS created_at,
           {frac} AS frac,
           bool_or(is_mayhem_mode) AS mayhem_at_launch
    FROM {CREATES}
    WHERE evt_block_date >= {_d(config.PROBE_START)}
      AND evt_block_date <  {_d(config.PROBE_END)}
      AND quote_mint = '{SOL_QUOTE_MINT}'
    GROUP BY mint, 3
)"""


def sql_burst_tokens() -> str:
    """Measurement 2 — what share of tokens and events the burst-producing tokens are.

    A token has at least one burst exactly when it has at least one qualifying
    event, so sessionisation is irrelevant here and the count is exact for §4.1's
    flow condition.  The looser `max(net_flow_2s) >= 1 SOL` proxies are reported
    alongside because a server-side pre-filter has to be expressible without
    knowing x at every event.
    """
    return f"""
WITH {_cohort_cte()},
ev AS (
    SELECT c.mint, t.evt_block_time AS block_time, t.is_buy,
           CAST(t.sol_amount AS double) / 1e9 AS sol,
           (CAST(t.virtual_sol_reserves AS double)
              - (CASE WHEN t.is_buy THEN CAST(t.sol_amount AS double)
                      ELSE -CAST(t.sol_amount AS double) END)) / 1e9 AS x_pre
    FROM {TRADES} t
    JOIN created c ON t.mint = c.mint
    WHERE t.evt_block_date >= {_d(config.PROBE_START)}
      AND t.evt_block_date <  {_d(config.PROBE_TAIL_END)}
      AND t.quote_mint = '{SOL_QUOTE_MINT}'
),
flow AS (
    SELECT mint, x_pre,
           sum(CASE WHEN is_buy THEN sol ELSE -sol END) OVER (
               PARTITION BY mint ORDER BY block_time
               RANGE BETWEEN INTERVAL '2' SECOND PRECEDING AND CURRENT ROW) AS net_2s
    FROM ev
),
tok AS (
    SELECT mint, count(*) AS n, max(net_2s) AS max_net2s,
           count_if(net_2s >= greatest(3.0, 0.10 * x_pre)) AS qual_events
    FROM flow GROUP BY 1
)
SELECT count(*) AS tokens,
       sum(n) AS events,
       count_if(qual_events > 0) AS tokens_burst,
       sum(CASE WHEN qual_events > 0 THEN n ELSE 0 END) AS events_burst_tokens,
       count_if(max_net2s >= 0.5) AS tokens_net2s_05,
       sum(CASE WHEN max_net2s >= 0.5 THEN n ELSE 0 END) AS events_net2s_05,
       count_if(max_net2s >= 1.0) AS tokens_net2s_1,
       sum(CASE WHEN max_net2s >= 1.0 THEN n ELSE 0 END) AS events_net2s_1,
       count_if(max_net2s >= 3.0) AS tokens_net2s_3,
       sum(CASE WHEN max_net2s >= 3.0 THEN n ELSE 0 END) AS events_net2s_3
FROM tok
"""


def sql_mayhem_timing() -> str:
    """Measurement 3a — where in a token's life mayhem mode switches on."""
    return f"""
WITH {_cohort_cte()},
tr AS (
    SELECT mint, evt_block_time AS bt, mayhem_mode
    FROM {TRADES}
    WHERE evt_block_date >= {_d(config.PROBE_START)}
      AND evt_block_date <  {_d(config.PROBE_TAIL_END)}
      AND quote_mint = '{SOL_QUOTE_MINT}'
),
onset AS (SELECT mint, min(bt) AS t_mayhem FROM tr WHERE mayhem_mode = true GROUP BY 1),
tok AS (
    SELECT c.mint, c.created_at, c.mayhem_at_launch, o.t_mayhem,
           date_diff('second', c.created_at, o.t_mayhem) AS secs
    FROM created c LEFT JOIN onset o ON c.mint = o.mint
)
SELECT count(*) AS tokens,
       count_if(t_mayhem IS NOT NULL) AS tokens_mayhem,
       count_if(mayhem_at_launch) AS mayhem_at_launch,
       count_if(mayhem_at_launch AND t_mayhem IS NULL) AS flagged_but_never_traded_mayhem,
       count_if(t_mayhem IS NOT NULL AND NOT mayhem_at_launch) AS mayhem_after_launch,
       count_if(secs <= 0) AS onset_at_launch,
       count_if(secs <= 60) AS onset_within_60s,
       count_if(secs <= 300) AS onset_within_300s,
       approx_percentile(CAST(secs AS double), 0.10) AS secs_p10,
       approx_percentile(CAST(secs AS double), 0.25) AS secs_p25,
       approx_percentile(CAST(secs AS double), 0.50) AS secs_p50,
       approx_percentile(CAST(secs AS double), 0.75) AS secs_p75,
       approx_percentile(CAST(secs AS double), 0.90) AS secs_p90,
       approx_percentile(CAST(secs AS double), 0.99) AS secs_p99,
       max(secs) AS secs_max
FROM tok
"""


def sql_mayhem_activity() -> str:
    """Measurement 3b — pre-onset activity, mayhem tokens vs the rest.

    Measurement 3a established that mayhem is set *at launch* and never acquired
    later, so a strictly pre-onset window has zero width for mayhem tokens — the
    `*_pre` columns below are all zero by construction and are kept only to make
    that explicit.  The `*_all` columns are the answerable question: are the two
    populations differently active at all?  That comparison is descriptive, and it
    cannot run the other way (activity causing mayhem) because the flag exists
    before the token's first trade.
    """
    return f"""
WITH {_cohort_cte()},
tr AS (
    SELECT mint, evt_block_time AS bt, mayhem_mode,
           CAST(sol_amount AS double) / 1e9 AS sol
    FROM {TRADES}
    WHERE evt_block_date >= {_d(config.PROBE_START)}
      AND evt_block_date <  {_d(config.PROBE_TAIL_END)}
      AND quote_mint = '{SOL_QUOTE_MINT}'
),
onset AS (SELECT mint, min(bt) AS t_mayhem FROM tr WHERE mayhem_mode = true GROUP BY 1),
tok AS (
    SELECT c.mint, c.created_at, o.t_mayhem
    FROM created c LEFT JOIN onset o ON c.mint = o.mint
),
pre AS (
    SELECT k.mint,
           k.t_mayhem IS NOT NULL AS is_mayhem,
           count_if(date_diff('second', k.created_at, t.bt) < 60) AS n60_all,
           count_if(date_diff('second', k.created_at, t.bt) < 300) AS n300_all,
           sum(CASE WHEN date_diff('second', k.created_at, t.bt) < 60
                    THEN t.sol ELSE 0 END) AS sol60_all,
           count(*) AS n_lifetime,
           sum(t.sol) AS sol_lifetime,
           count_if(date_diff('second', k.created_at, t.bt) < 60
                    AND (k.t_mayhem IS NULL OR t.bt < k.t_mayhem)) AS n60_pre
    FROM tok k JOIN tr t ON t.mint = k.mint
    GROUP BY 1, 2
)
SELECT is_mayhem,
       count(*) AS tokens,
       approx_percentile(CAST(n60_all AS double), 0.5) AS n60_p50,
       approx_percentile(CAST(n60_all AS double), 0.9) AS n60_p90,
       avg(CAST(n60_all AS double)) AS n60_mean,
       approx_percentile(CAST(n300_all AS double), 0.5) AS n300_p50,
       avg(CAST(n300_all AS double)) AS n300_mean,
       approx_percentile(sol60_all, 0.5) AS sol60_p50,
       avg(sol60_all) AS sol60_mean,
       approx_percentile(CAST(n_lifetime AS double), 0.5) AS n_lifetime_p50,
       avg(CAST(n_lifetime AS double)) AS n_lifetime_mean,
       approx_percentile(sol_lifetime, 0.5) AS sol_lifetime_p50,
       avg(CAST(n60_pre AS double)) AS n60_pre_mean
FROM pre GROUP BY 1
"""


def sql_reserve_continuity() -> str:
    """Measurement 4 — do the reported reserves form a consistent series?

    Everything here is exact `decimal(38,0)` integer arithmetic, no floats: the
    reserve deltas are compared to the reported amounts lamport for lamport, and
    x*y is compared between consecutive trades exactly.  Three questions at once:

      * does `vsol` move by exactly the reported `sol_amount` (net), or by
        `sol_amount - fee - creator_fee` (gross)?  That is §0.3, answered by
        arithmetic rather than by documentation.
      * does x*y stay put between trades, and where it jumps, is the jump
        concentrated in mayhem-mode rows?
      * does each token's first trade start from x0 = 30 SOL?
    """
    dec = "CAST({} AS decimal(38,0))"
    vsol, vtok = dec.format("t.virtual_sol_reserves"), dec.format("t.virtual_token_reserves")
    sol, fee, cfee = (dec.format("t.sol_amount"), dec.format("coalesce(t.fee, 0)"),
                      dec.format("coalesce(t.creator_fee, 0)"))
    return f"""
WITH {_cohort_cte()},
ev AS (
    SELECT c.mint, {vsol} AS vsol, {vtok} AS vtok,
           {sol} AS sol, {fee} AS fee, {cfee} AS cfee,
           t.is_buy, t.mayhem_mode,
           t.evt_block_slot AS slot, t.evt_tx_index AS txi,
           t.evt_outer_instruction_index AS oix,
           coalesce(t.evt_inner_instruction_index, 0) AS iix
    FROM {TRADES} t
    JOIN created c ON t.mint = c.mint
    WHERE t.evt_block_date >= {_d(config.PROBE_START)}
      AND t.evt_block_date <  {_d(config.PROBE_TAIL_END)}
      AND t.quote_mint = '{SOL_QUOTE_MINT}'
),
seq AS (
    SELECT mint, vsol, vtok, sol, fee, cfee, is_buy, mayhem_mode,
           vsol * vtok AS k,
           lag(vsol) OVER w AS prev_vsol,
           lag(vsol * vtok) OVER w AS prev_k,
           row_number() OVER w AS rn
    FROM ev
    WINDOW w AS (PARTITION BY mint ORDER BY slot, txi, oix, iix)
),
d AS (
    SELECT mint, mayhem_mode, rn,
           vsol - prev_vsol AS delta,
           CASE WHEN is_buy THEN sol ELSE -sol END AS signed_net,
           CASE WHEN is_buy THEN sol - fee - cfee ELSE -(sol - fee - cfee) END AS signed_gross,
           k, prev_k, vsol
    FROM seq WHERE prev_vsol IS NOT NULL
),
first_ev AS (
    SELECT count(*) AS n_first,
           count_if(vsol - (CASE WHEN is_buy THEN sol ELSE -sol END) = CAST(30000000000 AS decimal(38,0)))
               AS first_implies_x0_30_net,
           count_if(vsol - (CASE WHEN is_buy THEN sol - fee - cfee ELSE -(sol - fee - cfee) END)
                    = CAST(30000000000 AS decimal(38,0))) AS first_implies_x0_30_gross
    FROM seq WHERE rn = 1
),
pairs AS (
    SELECT count(*) AS n_pairs,
           count_if(delta = signed_net) AS net_exact,
           count_if(abs(delta - signed_net) <= 1) AS net_within_1,
           count_if(delta = signed_gross) AS gross_exact,
           count_if(abs(delta - signed_gross) <= 1) AS gross_within_1,
           count_if(k = prev_k) AS k_unchanged,
           count_if(k <> prev_k) AS k_changed,
           count_if(k <> prev_k AND mayhem_mode = true) AS k_changed_mayhem,
           count_if(mayhem_mode = true) AS mayhem_pairs,
           count_if(mayhem_mode = true AND delta = signed_net) AS mayhem_net_exact,
           count_if(mayhem_mode <> true AND delta = signed_net) AS plain_net_exact,
           count_if(mayhem_mode <> true) AS plain_pairs,
           approx_percentile(abs(CAST(delta - signed_net AS double)), 0.5) AS resid_net_p50,
           approx_percentile(abs(CAST(delta - signed_net AS double)), 0.99) AS resid_net_p99,
           approx_percentile(abs(CAST(k - prev_k AS double) / CAST(prev_k AS double)), 0.99)
               AS k_rel_change_p99,
           max(abs(CAST(k - prev_k AS double) / CAST(prev_k AS double))) AS k_rel_change_max
    FROM d
)
SELECT * FROM pairs CROSS JOIN first_ev
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


def sql_reserve_detail() -> str:
    """Measurement 4b — the curve identity itself, split by mayhem mode.

    Measurement 4 showed the SOL side chains exactly for non-mayhem trades, but
    left two things unmeasured: whether the *token* side moves by exactly
    `token_amount`, and where the bulk of the x*y drift sits (its p99 could be
    entirely the mayhem fifth).  Both are exact integer comparisons; x*y is
    compared as a ratio in double, which resolves ~1e-16 and so cannot manufacture
    the drift it measures.
    """
    dec = "CAST({} AS decimal(38,0))"
    return f"""
WITH {_cohort_cte()},
ev AS (
    SELECT c.mint,
           {dec.format('t.virtual_sol_reserves')} AS vsol,
           {dec.format('t.virtual_token_reserves')} AS vtok,
           {dec.format('t.sol_amount')} AS sol,
           {dec.format('t.token_amount')} AS tok,
           t.is_buy, t.mayhem_mode,
           t.evt_block_slot AS slot, t.evt_tx_index AS txi,
           t.evt_outer_instruction_index AS oix,
           coalesce(t.evt_inner_instruction_index, 0) AS iix
    FROM {TRADES} t
    JOIN created c ON t.mint = c.mint
    WHERE t.evt_block_date >= {_d(config.PROBE_START)}
      AND t.evt_block_date <  {_d(config.PROBE_TAIL_END)}
      AND t.quote_mint = '{SOL_QUOTE_MINT}'
),
seq AS (
    SELECT mint, vsol, vtok, sol, tok, is_buy,
           coalesce(mayhem_mode, false) AS mayhem,
           lag(vsol) OVER w AS prev_vsol,
           lag(vtok) OVER w AS prev_vtok
    FROM ev
    WINDOW w AS (PARTITION BY mint ORDER BY slot, txi, oix, iix)
),
d AS (
    SELECT mayhem,
           vsol - prev_vsol AS dsol,
           vtok - prev_vtok AS dtok,
           CASE WHEN is_buy THEN sol ELSE -sol END AS want_dsol,
           CASE WHEN is_buy THEN -tok ELSE tok END AS want_dtok,
           abs(CAST(vsol * vtok AS double) / CAST(prev_vsol * prev_vtok AS double) - 1.0) AS k_rel
    FROM seq WHERE prev_vsol IS NOT NULL
)
SELECT mayhem,
       count(*) AS pairs,
       count_if(dsol = want_dsol) AS sol_side_exact,
       count_if(dtok = want_dtok) AS token_side_exact,
       count_if(dsol = want_dsol AND dtok = want_dtok) AS both_sides_exact,
       approx_percentile(k_rel, 0.50) AS k_rel_p50,
       approx_percentile(k_rel, 0.90) AS k_rel_p90,
       approx_percentile(k_rel, 0.99) AS k_rel_p99,
       max(k_rel) AS k_rel_max,
       count_if(k_rel < 1e-12) AS k_stable_1e12,
       count_if(k_rel < 1e-9) AS k_stable_1e9,
       count_if(k_rel < 1e-6) AS k_stable_1e6,
       count_if(k_rel < 1e-3) AS k_stable_1e3
FROM d GROUP BY 1
"""


MEASUREMENTS = {
    "burst_tokens": sql_burst_tokens,
    "mayhem_timing": sql_mayhem_timing,
    "mayhem_activity": sql_mayhem_activity,
    "reserve_continuity": sql_reserve_continuity,
    "reserve_detail": sql_reserve_detail,
}


def cmd_measure(args: argparse.Namespace) -> None:
    """Run the named aggregate measurements and append them to a JSON record.

    Each returns a handful of rows, so retrieval is free in practice and the only
    cost is compute.  Results accumulate in results/phase0_measurements.json.
    """
    out = config.RESULTS / "phase0_measurements.json"
    store = json.loads(out.read_text()) if out.exists() else {}
    dune = Dune()
    for name in (args.only or MEASUREMENTS):
        if name not in MEASUREMENTS:
            raise SystemExit(f"unknown measurement {name}; have {list(MEASUREMENTS)}")
        meta = dune.run(f"phase0_{name}", MEASUREMENTS[name](), max_seconds=args.cap)
        rows = list(dune.rows(meta["execution_id"], max_rows=100))
        store[name] = {"rows": rows, "credits": meta["execution_cost_credits"],
                       "execution_id": meta["execution_id"]}
        print(f"    -> {json.dumps(rows, default=str)[:600]}")
    store["credits_total_this_run"] = dune.total_credits()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(store, indent=2, default=str) + "\n")
    print(f"\n-> {out}   ({dune.total_credits():.2f} credits this run)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    mea = sub.add_parser("measure", help="run aggregate measurements (cheap)")
    mea.add_argument("--only", nargs="*", help=f"subset of {list(MEASUREMENTS)}")
    mea.add_argument("--cap", type=int, default=420)
    est = sub.add_parser("estimate")
    est.add_argument("--cap", type=int, default=420, help="seconds before cancelling")
    raw = sub.add_parser("raw")
    raw.add_argument("--sql")
    raw.add_argument("--file")
    raw.add_argument("--cap", type=int, default=120)
    raw.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    {"discover": cmd_discover, "estimate": cmd_estimate, "raw": cmd_raw,
     "measure": cmd_measure}[args.cmd](args)


if __name__ == "__main__":
    main()
