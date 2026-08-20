"""Run the v2 dev extract, one 9-day launch chunk at a time.

  python -m src.run_extract_v2 <chunk_number>

Schema is frozen: `sql/extract_v2.sql`, 80 columns, INCLUDE_TRANSFERS = true,
transfers read from the union of the 17 materialized views.  Nothing here adds
or removes a column.

No execution cap.  Cancelling bills in full while Dune's own failure bills 0
(measured: a 1200s cap cost 62.62 credits for no output, a 300s cap cost 5.21
and killed a build that finished at 335s), so the poll loop waits out Dune's own
30-minute limit instead of cancelling.

Pages land on disk as they arrive.  A mid-export failure has already cost this
study one paid page (ChunkedEncodingError, chunk 6 of the v1 run), so the export
resumes from the row count already written rather than re-fetching.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from src import config  # noqa: E402
from src.extract_schema import CANON_V2, V2_COLUMNS  # noqa: E402
from src.ingest_dune import Dune  # noqa: E402
from src.trial_v2_transfers import xf_source, _DROP  # noqa: E402

import re  # noqa: E402

OUT = config.REPO / "data" / "extract_v2"
LEDGER = config.RESULTS / "extract_v2_chunks.jsonl"
PAGE = 25_000
EVENT_TO = "2026-08-15"

#: launch windows, half-open.  Identical to the v1 dev chunks, so the burst key
#: sets must match exactly.
CHUNKS = {
    1: ("2026-05-10", "2026-05-19"),
    2: ("2026-05-19", "2026-05-28"),
    3: ("2026-05-28", "2026-06-06"),
    4: ("2026-06-06", "2026-06-15"),
    5: ("2026-06-15", "2026-06-24"),
    6: ("2026-06-24", "2026-07-03"),
}


def build_sql(launch_from: str, launch_to: str) -> str:
    sql = (config.REPO / "sql" / "extract_v2.sql").read_text()
    sql = sql.replace("FROM tokens_solana.spl_token_transfers x", "FROM " + xf_source())
    for pat in _DROP:
        sql = re.sub(pat, "", sql, flags=re.MULTILINE)
    for k, v in (("{{LAUNCH_FROM}}", launch_from), ("{{LAUNCH_TO}}", launch_to),
                 ("{{EVENT_TO}}", EVENT_TO), ("{{INCLUDE_TRANSFERS}}", "true")):
        sql = sql.replace(k, v)
    if "{{" in sql:
        raise RuntimeError("unsubstituted parameter remains")
    if "tokens_solana.spl_token_transfers" in sql:
        raise RuntimeError("raw transfer table still referenced")
    return sql


def cycle(d: Dune) -> float:
    return float(d._request("POST", "/usage", json={})["billing_periods"][0]["credits_used"])


def dune_seconds(st: dict) -> float | None:
    a, b = st.get("execution_started_at"), st.get("execution_ended_at")
    if not (a and b):
        return None
    from datetime import datetime
    f = lambda s: datetime.strptime(re.sub(r"(\.\d{6})\d*Z", r"\1Z", s),
                                    "%Y-%m-%dT%H:%M:%S.%fZ")
    return round((f(b) - f(a)).total_seconds(), 1)


def execute(d: Dune, n: int, sql: str) -> dict:
    """Create a public query and run it to completion, never cancelling."""
    q = d._request("POST", "/query", json={
        "name": f"[flow-research] extract_v2 dev chunk {n:02d}",
        "query_sql": sql, "is_private": False, "query_engine": "v2 Dune SQL"})
    qid = q["query_id"]
    ex = d._request("POST", f"/query/{qid}/execute", json={"performance": "medium"})
    eid = ex["execution_id"]
    print(f"  chunk {n}: public query {qid}, execution {eid}", flush=True)
    t0 = time.time()
    while time.time() - t0 < 2100:
        st = d._request("GET", f"/execution/{eid}/status")
        if st["state"] not in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
            break
        time.sleep(15)
    st = d._request("GET", f"/execution/{eid}/status")
    return {"query_id": qid, "execution_id": eid, "status": st}


def export(d: Dune, eid: str, n: int) -> tuple[Path, int, int]:
    """Page the result to JSONL on disk, resuming from what is already there."""
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / f"dev_chunk{n:02d}.rows.jsonl"
    have = sum(1 for _ in raw.open()) if raw.exists() else 0
    if have:
        print(f"  resuming at row {have:,}", flush=True)
    requests = 0
    with raw.open("a") as fh:
        while True:
            payload = d._request("GET", f"/execution/{eid}/results",
                                 params={"limit": PAGE, "offset": have})
            requests += 1
            batch = payload.get("result", {}).get("rows", [])
            for r in batch:
                fh.write(json.dumps(r) + "\n")
            fh.flush()
            have += len(batch)
            print(f"    page {requests}: +{len(batch):,} -> {have:,}", flush=True)
            if len(batch) < PAGE:
                return raw, have, requests


def to_parquet(raw: Path, n: int) -> Path:
    rows = [json.loads(l) for l in raw.open()]
    cols = {c: [r.get(c) for r in rows] for c in V2_COLUMNS}
    table = pa.table({c: cols[c] for c in CANON_V2.names}).cast(CANON_V2)
    out = OUT / f"dev_chunk{n:02d}.parquet"
    pq.write_table(table, out, compression="zstd")
    return out


def main() -> None:
    n = int(sys.argv[1])
    lf, lt = CHUNKS[n]
    d = Dune()
    before = cycle(d)
    print(f"[chunk {n}] launch [{lf}, {lt}), event -> {EVENT_TO}; cycle {before:.3f}",
          flush=True)

    t0 = time.time()
    run = execute(d, n, build_sql(lf, lt))
    st = run["status"]
    exec_cr = float(st.get("execution_cost_credits") or 0.0)
    md = st.get("result_metadata") or {}
    if st["state"] != "QUERY_STATE_COMPLETED":
        print(json.dumps({"state": st["state"], "error": st.get("error"),
                          "execution_cost_credits": exec_cr}, indent=2))
        return
    after_exec = cycle(d)

    t1 = time.time()
    raw, n_rows, reqs = export(d, run["execution_id"], n)
    t2 = time.time()
    after_export = cycle(d)
    parquet = to_parquet(raw, n)

    rec = {
        "chunk": n, "launch_from": lf, "launch_to": lt, "event_to": EVENT_TO,
        "query_id": run["query_id"], "execution_id": run["execution_id"],
        "rows": md.get("total_row_count"), "rows_exported": n_rows,
        "result_bytes": md.get("total_result_set_bytes"),
        "row_width_bytes": (md.get("total_result_set_bytes") or 0)
                           / max(md.get("total_row_count") or 1, 1),
        "execution_credits": exec_cr,
        "retrieval_credits": round(after_export - after_exec, 3),
        "cycle_before": before, "cycle_after": after_export,
        "dune_seconds": dune_seconds(st),
        "wall_execute_seconds": round(t1 - t0, 1),
        "export_seconds": round(t2 - t1, 1),
        "api_requests": reqs,
        "parquet": str(parquet), "parquet_bytes": parquet.stat().st_size,
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
