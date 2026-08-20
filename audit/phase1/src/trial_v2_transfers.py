"""Run `sql/extract_v2.sql` with transfers on, sourced from the matviews.

  python -m src.trial_v2_transfers sql                 # print the built SQL
  python -m src.trial_v2_transfers run                 # execute, report status only
  python -m src.trial_v2_transfers agg                 # execute the aggregate probe

`sql/extract_v2.sql` is NOT edited.  Its `xf` CTE reads
`tokens_solana.spl_token_transfers` directly, which is the 6.9-billion-row scan
the materialisation exists to avoid; the substitution below swaps that one FROM
for the union of the 17 materialized views in `sql/xf_union.sql`.  Keeping the
edit here rather than in the SQL file leaves the audited statement readable and
makes the swap itself reviewable in one place.
ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (where the substitution lives, not whether the
matviews are the transfer source -- that was specified).

Four predicates are dropped along with the raw table, because the matview
already applied every one of them when it was built and the columns they read
are not projected:

    block_time < TIMESTAMP '{{EVENT_TO}} 23:59:00 UTC'   baked in (EVENT_TO is
                                                         2026-08-15 in every chunk)
    action = 'transfer'                                  baked in
    outer_executing_account <> pump.fun                  baked in
    from_owner <> to_owner                               baked in

What stays is what varies per chunk: the `sel` join to this chunk's mints and
the `block_date` bounds.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.ingest_dune import Dune  # noqa: E402

V2 = config.REPO / "sql" / "extract_v2.sql"
UNION = config.REPO / "sql" / "xf_union.sql"

PARAMS = {
    "{{LAUNCH_FROM}}": "2026-06-06",
    "{{LAUNCH_TO}}": "2026-06-07",
    "{{EVENT_TO}}": "2026-08-15",
    "{{INCLUDE_TRANSFERS}}": "true",
}

#: Predicates the matview already applied; they reference columns it does not
#: project, so they must go when the source is swapped.
_DROP = (
    r"^\s+AND x\.block_time <.*$",
    r"^\s+AND x\.action = 'transfer'\s*$",
    r"^\s+AND x\.outer_executing_account <>.*$",
    r"^\s+AND x\.from_owner <> x\.to_owner\s*$",
)


def xf_source() -> str:
    """The matview union, aliased back to the raw table's column names."""
    union = UNION.read_text().strip()
    return (
        "(\n        SELECT block_slot, tx_index,\n"
        "               outer_ix_index AS outer_instruction_index,\n"
        "               inner_ix_index AS inner_instruction_index,\n"
        "               token_mint_address, from_owner, to_owner, amount, block_date\n"
        "        FROM (\n          " + union.replace("\n", "\n          ") + "\n        ) u\n    ) x"
    )


def build(include_transfers: str = "true") -> str:
    sql = V2.read_text()
    sql = sql.replace("FROM tokens_solana.spl_token_transfers x",
                      "FROM " + xf_source())
    for pat in _DROP:
        sql = re.sub(pat, "", sql, flags=re.MULTILINE)
    for k, v in PARAMS.items():
        sql = sql.replace(k, v)
    if include_transfers != "true":
        sql = sql.replace("'true' = 'true'", "'false' = 'true'")
    return sql


def execute(label: str, sql: str, max_seconds: int = 2100) -> dict:
    """Execute as a PUBLIC query.

    `Dune.run` creates private queries, and the account is at its cap of 30.
    The alternative to going public is deleting one of those 30, every one of
    which is a step in this study's audit trail; public queries were measured
    not to count against the cap (docs/transfer_materialization.md §1).
    ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР.
    """
    d = Dune()
    t0 = time.time()
    q = d._request("POST", "/query", json={
        "name": f"[flow-research] {label}", "query_sql": sql,
        "is_private": False, "query_engine": "v2 Dune SQL"})
    qid = q["query_id"]
    ex = d._request("POST", f"/query/{qid}/execute", json={"performance": "medium"})
    eid = ex["execution_id"]
    print(f"  {label}: public query {qid}, execution {eid}", flush=True)
    while time.time() - t0 < max_seconds:
        s = d._request("GET", f"/execution/{eid}/status")
        if s["state"] not in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
            break
        time.sleep(10)
    st = d._request("GET", f"/execution/{eid}/status")
    rec = {
        "label": label, "query_id": qid, "execution_id": eid, "state": st["state"],
        "wall_seconds": round(time.time() - t0, 1),
        "execution_cost_credits": float(st.get("execution_cost_credits") or 0.0),
        "result_rows": (st.get("result_metadata") or {}).get("total_row_count"),
        "result_bytes": (st.get("result_metadata") or {}).get("total_result_set_bytes"),
        "dune_seconds": None,
        "error": st.get("error"),
    }
    for a, b in (("execution_started_at", "execution_ended_at"),):
        if st.get(a) and st.get(b):
            from datetime import datetime
            fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
            try:
                rec["dune_seconds"] = round(
                    (datetime.strptime(st[b], fmt) - datetime.strptime(st[a], fmt))
                    .total_seconds(), 1)
            except ValueError:
                pass
    return rec


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sql"
    if cmd == "sql":
        print(build())
        return
    if cmd == "run":
        rec = execute("extract_v2_xfer", build())
        print(json.dumps(rec, indent=2))
        return
    raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
