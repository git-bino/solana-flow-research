"""A -- token-level path summary, built on Dune as a MATERIALIZED VIEW.

  python -m src.path_after_60_dune build       # §1 matview (one row per token,level)
  python -m src.path_after_60_dune price       # price the parquet export, no download
  python -m src.path_after_60_dune agg         # §3 aggregates, read back from the matview
  python -m src.path_after_60_dune export      # download the token rows -> parquet

`src/path_after_60.py` is the earlier LOCAL feasibility check that stopped this
task; this module is the Dune side the research lead then authorised.

WHY A MATVIEW AND NOT A DIRECT PULL.  Retrieval is billed per byte of result.
The only measured anchor is chunk 1: 165,829,366 bytes -> 1,948.0 retrieval
credits = 11.748 cr per 1e6 bytes.  The task's budget is 60 credits total, so the
export has to be PRICED BEFORE IT IS PAID.  Building the rows into a matview
costs execution only; `price` then reads the stored size and a measured row width
and reports what the download would cost, so the decision is made on a number.
ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (cost engineering; the rows and their
definitions are exactly what the task specified).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from src import config  # noqa: E402
from src.ingest_dune import Dune, api_key  # noqa: E402

SQL = config.REPO / "sql" / "path_after_60.sql"
OUT = config.RESULTS / "path_after_60_dune.json"
MV = "result_flow_path"
FULL = f"dune.quantbino1695.{MV}"

#: measured on chunk 1 (results/extract_v2_chunks.jsonl):
#: 165,829,366 result bytes -> 1,948.0 retrieval credits
CR_PER_BYTE = 1948.0 / 165_829_366


def cycle(d: Dune) -> float:
    return float(d._request("POST", "/usage", json={})["billing_periods"][0]["credits_used"])


def _load() -> dict:
    return json.loads(OUT.read_text()) if OUT.exists() else {}


def _save(rec: dict) -> None:
    OUT.write_text(json.dumps(rec, indent=2, default=float))


def run_public(d: Dune, name: str, sql: str, cap: int = 900) -> dict:
    """Create a PUBLIC query and execute it.  The 30 private-query cap is full;
    public queries do not count against it (measured 2026-08-19)."""
    qid = d._request("POST", "/query", json={
        "name": f"[flow-research] {name}", "query_sql": sql,
        "is_private": False, "query_engine": "v2 Dune SQL"})["query_id"]
    eid = d._request("POST", f"/query/{qid}/execute",
                     json={"performance": "medium"})["execution_id"]
    st = wait(d, eid, cap)
    return {"query_id": qid, "execution_id": eid, "state": st["state"],
            "cost": float(st.get("execution_cost_credits") or 0.0),
            "error": st.get("error")}


def wait(d: Dune, eid: str, cap: int = 2100) -> dict:
    t0 = time.time()
    while time.time() - t0 < cap:
        st = d._request("GET", f"/execution/{eid}/status")
        if st["state"] not in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
            return st
        time.sleep(10)
    return d._request("GET", f"/execution/{eid}/status")


def build() -> None:
    d = Dune()
    rec = _load()
    before = cycle(d)
    sql = SQL.read_text()

    qid = d._request("POST", "/query", json={
        "name": "[flow-research] token path after level (60 / 115)",
        "query_sql": sql, "is_private": False,
        "query_engine": "v2 Dune SQL"})["query_id"]
    print(f"query {qid}")

    try:
        mv = d._request("POST", "/materialized-views",
                        json={"name": MV, "query_id": qid})
    except RuntimeError as exc:
        if "conflicting existing Matview" not in str(exc):
            raise
        prev = d._request("GET", f"/materialized-views/{FULL}")
        for e in prev.get("last_execution_ids") or []:
            st = d._request("GET", f"/execution/{e}/status")
            if st["state"] in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
                raise RuntimeError(f"{MV}: build {e} still running; adopt it") from exc
        requests.delete(f"https://api.dune.com/api/v1/materialized-views/{FULL}",
                        headers={"X-Dune-Api-Key": api_key()}, timeout=90)
        mv = d._request("POST", "/materialized-views",
                        json={"name": MV, "query_id": qid})

    eid = mv["execution_id"]
    print(f"execution {eid}", flush=True)
    t0 = time.time()
    st = wait(d, eid)
    cost = float(st.get("execution_cost_credits") or 0.0)
    print(f"{st['state']}  {cost:.3f} cr  {time.time()-t0:.1f} с")
    if st["state"] != "QUERY_STATE_COMPLETED":
        print(json.dumps(st.get("error"), indent=2)[:600])
        rec["build"] = {"query_id": qid, "execution_id": eid,
                        "state": st["state"], "cost": cost,
                        "error": st.get("error")}
        _save(rec)
        return

    info = d._request("GET", f"/materialized-views/{mv['name']}")
    rec["build"] = {"query_id": qid, "execution_id": eid, "state": st["state"],
                    "cost": cost, "table_size_bytes": info.get("table_size_bytes"),
                    "cycle_before": before, "cycle_after": cycle(d)}
    print(f"table_size_bytes {info.get('table_size_bytes'):,}")
    _save(rec)


def price() -> None:
    """Count the rows and MEASURE the API row width on a 200-row probe."""
    d = Dune()
    rec = _load()
    before = cycle(d)

    cm = run_public(d, "path_count",
                    f"SELECT lvl, count(*) AS n FROM {FULL} GROUP BY lvl ORDER BY lvl")
    counts = {int(r["lvl"]): int(r["n"]) for r in d.rows(cm["execution_id"])}
    c1 = cm["cost"]
    total_rows = sum(counts.values())
    print(f"мөр: " + ", ".join(f"lvl={k} -> {v:,}" for k, v in counts.items())
          + f"  нийт {total_rows:,}   ({c1:.3f} cr)")

    # measure the API payload width on 200 rows rather than guessing it
    pm = run_public(d, "path_probe", f"SELECT * FROM {FULL} LIMIT 200")
    body = requests.get(f"https://api.dune.com/api/v1/execution/"
                        f"{pm['execution_id']}/results?limit=200",
                        headers={"X-Dune-Api-Key": api_key()}, timeout=120)
    probe_bytes = len(body.content)
    c2 = pm["cost"]
    width = probe_bytes / 200.0
    est_bytes = width * total_rows
    est_cr = est_bytes * CR_PER_BYTE
    print(f"хэмжсэн мөрийн өргөн {width:.1f} байт (200 мөрийн probe "
          f"{probe_bytes:,} байт, {c2:.3f} cr)")
    print(f"экспортын тооцоо: {est_bytes/1e6:.2f} MB -> "
          f"**{est_cr:.2f} cr**   (× 3 = {3*est_cr:.2f})")

    rec["price"] = {"counts": counts, "total_rows": total_rows,
                    "probe_bytes": probe_bytes, "row_width_bytes": width,
                    "est_export_bytes": est_bytes, "est_export_credits": est_cr,
                    "count_cost": c1, "probe_cost": c2,
                    "cycle_before": before, "cycle_after": cycle(d)}
    _save(rec)


def export() -> None:
    """Download the token-level rows to parquet.  Only run after `price`."""
    import pandas as pd

    d = Dune()
    rec = _load()
    est = rec.get("price", {}).get("est_export_credits")
    if est is None:
        raise SystemExit("эхлээд `price`-ыг ажиллуул")
    before = cycle(d)
    m = run_public(d, "path_export", f"SELECT * FROM {FULL}", cap=1800)
    rows = list(d.rows(m["execution_id"]))
    df = pd.DataFrame(rows)
    p = config.REPO / "data" / "path" / "path_after_60.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    after = cycle(d)
    print(f"{len(df):,} мөр -> {p}  ({p.stat().st_size:,} байт)")
    print(f"бодит зардал {after-before:.3f} cr (тооцоо {est:.2f})")
    rec["export"] = {"rows": len(df), "parquet_bytes": p.stat().st_size,
                     "actual_credits": after - before, "estimate": est}
    _save(rec)


if __name__ == "__main__":
    {"build": build, "price": price, "export": export}[sys.argv[1]]()
