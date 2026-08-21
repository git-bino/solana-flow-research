"""Build one transfer materialized view per slice, and report what it cost.

  python -m src.build_matview <name_suffix> <slice_from> <slice_to> [cap_seconds]

A Dune materialized view is a real table, not a saved query: `query_<id>`
re-executes the query text, while `dune.<user>.result_<name>` is read back
without re-running anything (both measured, docs/transfer_materialization.md).

The build itself is an ordinary execution and is billed like one.  Two costs are
recorded for each slice: the execution's own `execution_cost_credits` and the
delta in the account's cycle usage, which also catches anything the create call
bills outside the execution.

A failed execution costs 0 credits (measured on the 9-day plain-query attempt),
but a CANCELLED one does not: the 8-day probe was cancelled at a 1200-second cap
and still billed 62.62 credits.  Probing large slices is therefore not free, and
the cap is what bounds a runaway.  A healthy 6-day build finishes in ~92s, so the
default cap is 300s -- 3x headroom, and ~15 credits of exposure rather than 62.
ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (the cap, not the slice size).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
import requests  # noqa: E402

from src.ingest_dune import Dune, api_key  # noqa: E402

SQL = config.REPO / "sql" / "materialize_transfers.sql"
LEDGER = config.RESULTS / "matview_slices.jsonl"


def cycle_credits(d: Dune) -> float:
    return float(d._request("POST", "/usage", json={})["billing_periods"][0]["credits_used"])


def slice_sql(slice_from: str, slice_to: str) -> str:
    return (SQL.read_text()
            .replace("{{SLICE_FROM}}", slice_from)
            .replace("{{SLICE_TO}}", slice_to))


def build(suffix: str, slice_from: str, slice_to: str, cap: int = 2100) -> dict:
    d = Dune()
    name = f"result_flow_xf_{suffix}"
    sql = slice_sql(slice_from, slice_to)
    before = cycle_credits(d)

    q = d._request("POST", "/query", json={
        "name": f"[flow-research] pumpfun curve SPL transfers {suffix} "
                f"({slice_from}..{slice_to})",
        "query_sql": sql,
        "is_private": False,
    })
    qid = q["query_id"]
    try:
        mv = d._request("POST", "/materialized-views",
                        json={"name": name, "query_id": qid})
    except RuntimeError as exc:
        # A driver killed mid-run leaves a matview bound to its own query id, and
        # the name is then refused.  Drop the stale table and take the name back.
        # Check it is not still building first -- an in-flight build is worth
        # adopting (src/adopt_matview.py), not deleting.
        if "conflicting existing Matview" not in str(exc):
            raise
        full = f"dune.quantbino1695.{name}"
        prev = d._request("GET", f"/materialized-views/{full}")
        for e in prev.get("last_execution_ids") or []:
            st = d._request("GET", f"/execution/{e}/status")
            if st["state"] in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
                raise RuntimeError(f"{name}: build {e} still running; adopt it") from exc
        requests.delete(f"https://api.dune.com/api/v1/materialized-views/{full}",
                        headers={"X-Dune-Api-Key": api_key()}, timeout=90)
        mv = d._request("POST", "/materialized-views",
                        json={"name": name, "query_id": qid})
    eid = mv["execution_id"]
    print(f"  {name}: query {qid}, execution {eid}", flush=True)

    t0 = time.time()
    state = "QUERY_STATE_PENDING"
    while time.time() - t0 < cap:
        st = d._request("GET", f"/execution/{eid}/status")
        state = st["state"]
        if state not in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
            break
        time.sleep(10)
    else:
        # NO CANCEL.  Measured: Dune's own cluster-capacity failure bills 0, while
        # cancelling bills in full (1209.5s -> 62.62 cr, 304.9s -> 5.21 cr, the
        # latter killing a build that would have completed at 335s).  A cap saves
        # nothing and only burns credits for no output, so the loop waits out
        # Dune's own 30-minute limit instead.  NOTE: a 30-minute *timeout* is not
        # free either -- one was measured at 164.755 cr -- so this trades a
        # certain small loss for a rare large one.
        state = "STILL_EXECUTING_AT_CAP"

    elapsed = time.time() - t0
    st = d._request("GET", f"/execution/{eid}/status")
    cost = float(st.get("execution_cost_credits") or 0.0)
    after = cycle_credits(d)

    info, n_rows, count_cost = {}, None, None
    if state == "QUERY_STATE_COMPLETED":
        info = d._request("GET", f"/materialized-views/{mv['name']}")
        # Row count, not bytes: the extract's join cost scales with rows, and the
        # stored table is compressed (~19 B/row against 160 B/row uncompressed),
        # so `table_size_bytes` is not a row proxy.
        cm = d.run("probe_schemas", f"SELECT count(*) AS n FROM {mv['name']}",
                   max_seconds=300)
        n_rows = int(next(iter(d.rows(cm["execution_id"])))["n"])
        cst = d._request("GET", f"/execution/{cm['execution_id']}/status")
        count_cost = float(cst.get("execution_cost_credits") or 0.0)

    rec = {
        "suffix": suffix, "slice_from": slice_from, "slice_to": slice_to,
        "query_id": qid, "execution_id": eid, "sql_id": mv["name"],
        "state": state, "seconds": round(elapsed, 1),
        "execution_cost_credits": cost,
        "cycle_delta": round(after - before, 3),
        "cycle_after": after,
        "table_size_bytes": info.get("table_size_bytes"),
        "n_rows": n_rows,
        "count_cost_credits": count_cost,
        "error": st.get("error"),
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def main() -> None:
    suffix, sfrom, sto = sys.argv[1], sys.argv[2], sys.argv[3]
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else 2100
    rec = build(suffix, sfrom, sto, cap)
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
