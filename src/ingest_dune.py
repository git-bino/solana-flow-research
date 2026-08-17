"""Dune ingestion — spec §2.1, §2.2, §2.3, Phase 0.1/0.2.

Subcommands, in the order Phase 0 runs them:

  discover   dump information_schema for the pump.fun namespaces, so every column
             name used downstream is *observed* rather than remembered
  estimate   §0.1 — measure a short sample, extrapolate the 90-day universe, and
             price it in Dune credits and ClickHouse disk BEFORE pulling anything
  fetch      §0.2 — pull launches / trades / migrations for the frozen window,
             apply the frozen mint-hash sample, split dev vs holdout on write

Credit discipline: nothing here executes a query without printing what it cost.
Every execution records `datapoint_count` and `total_result_set_bytes` from the
API into results/dune_usage.jsonl, which is what the §0.1 estimate is built from
and what makes the estimate auditable after the fact.

Dune has no ad-hoc-SQL endpoint: SQL must live in a saved query.  `ensure_query`
creates one through the CRUD API when the plan allows it and otherwise falls back
to an id recorded in sql/query_ids.json, so the same code path works on a Free
key where the query was pasted into the UI by hand.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

SQL_DIR = config.REPO / "sql"
QUERY_IDS = SQL_DIR / "query_ids.json"
USAGE_LOG = config.RESULTS / "dune_usage.jsonl"

#: Published export rates, credits per MB (docs.dune.com billing).  Retrieval has
#: also historically been billed per 1000 datapoints; the estimate reports both
#: and the run log records what the API actually charged, so the report never
#: rests on a single remembered rate.
CREDITS_PER_MB = {"free": 20, "analyst": 10, "plus": 2}
CREDITS_PER_1K_DATAPOINTS = 1
MONTHLY_CREDITS = {"free": 2_500, "analyst": 4_000, "plus": 25_000}
EXECUTION_CREDITS = {"small": 10, "medium": 10, "large": 20}


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

    # --- plumbing ---------------------------------------------------------
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
        """Return a saved-query id for `sql`, creating or updating as needed."""
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
        QUERY_IDS.write_text(json.dumps(ids, indent=2) + "\n")
        print(f"  created Dune query {qid} for {name}")
        return qid

    def run(self, name: str, sql: str, params: dict[str, Any] | None = None) -> int:
        qid = self.ensure_query(name, sql)
        body: dict[str, Any] = {"performance": self.performance}
        if params:
            body["query_parameters"] = params
        execution = self._request("POST", f"/query/{qid}/execute", json=body)
        eid = execution["execution_id"]
        print(f"  {name}: execution {eid} ...", end="", flush=True)
        while True:
            status = self._request("GET", f"/execution/{eid}/status")
            state = status["state"]
            if state == "QUERY_STATE_COMPLETED":
                print(" done")
                self._log_usage(name, eid, status)
                return eid
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"):
                raise RuntimeError(f"{name}: execution {eid} {state}: {status}")
            print(".", end="", flush=True)
            time.sleep(3)

    def _log_usage(self, name: str, eid: str, status: dict[str, Any]) -> None:
        meta = status.get("result_metadata") or {}
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "query": name,
            "execution_id": eid,
            "performance": self.performance,
            "rows": meta.get("total_row_count"),
            "bytes": meta.get("total_result_set_bytes"),
            "datapoints": meta.get("datapoint_count"),
            "columns": len(meta.get("column_names") or []),
            "execution_ms": meta.get("execution_time_millis"),
        }
        self.usage.append(record)
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"    rows={record['rows']:,} bytes={_mb(record['bytes'])} "
              f"datapoints={record['datapoints']:,}"
              if record["rows"] is not None else "    (no result metadata)")

    def rows(self, eid: str, page: int = 25_000) -> Iterator[dict[str, Any]]:
        """Stream every row of a completed execution, page by page."""
        offset = 0
        while True:
            payload = self._request(
                "GET", f"/execution/{eid}/results",
                params={"limit": page, "offset": offset},
            )
            batch = payload.get("result", {}).get("rows", [])
            yield from batch
            if len(batch) < page:
                return
            offset += len(batch)


def _mb(n: int | None) -> str:
    return "?" if n is None else f"{n / 1e6:,.1f}MB"


# --- SQL ------------------------------------------------------------------
# Kept as files so Codex (§8.4) reviews the same text Dune executes, and so a
# Free-plan key can paste them into the UI unchanged.

DISCOVERY_SQL = """
-- Phase 0: observe the schema instead of assuming it.
select table_schema, table_name, column_name, data_type
from information_schema.columns
where table_schema like '%pump%'
order by table_schema, table_name, ordinal_position
"""


def cmd_discover(args: argparse.Namespace) -> None:
    dune = Dune(performance="small")
    eid = dune.run("schema_discovery", DISCOVERY_SQL)
    rows = list(dune.rows(eid))
    out = config.RESULTS / "dune_schema.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    current = None
    for row in rows:
        table = f"{row['table_schema']}.{row['table_name']}"
        if table != current:
            lines.append(f"\n=== {table}")
            current = table
        lines.append(f"  {row['column_name']:<40} {row['data_type']}")
    out.write_text("\n".join(lines) + "\n")
    tables = sorted({f"{r['table_schema']}.{r['table_name']}" for r in rows})
    print(f"\n{len(tables)} tables, {len(rows)} columns -> {out}")
    for t in tables:
        print(f"  {t}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="dump information_schema for pump.fun tables")
    args = parser.parse_args()
    {"discover": cmd_discover}[args.cmd](args)


if __name__ == "__main__":
    main()
