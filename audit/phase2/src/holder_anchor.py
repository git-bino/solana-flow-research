"""Holder-count anchors and first passage -- Dune side, aggregates only.

  python -m src.holder_anchor mv <name> <sql-file>     # build a matview
  python -m src.holder_anchor q  <name> <sql-file>     # run a query, print rows

NO PARQUET EXPORT (research lead, 2026-08-21).  Everything stays on Dune; only
aggregate result sets come back through the API.
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

OUT = config.RESULTS / "holder_anchor.json"
XF = (config.REPO / "sql" / "xf_union.sql").read_text()


def load() -> dict:
    return json.loads(OUT.read_text()) if OUT.exists() else {}


def save(r: dict) -> None:
    OUT.write_text(json.dumps(r, indent=2, default=float))


def cycle(d: Dune) -> float:
    return float(d._request("POST", "/usage", json={})["billing_periods"][0]["credits_used"])


def sql_of(path: str, kinds: str | None = None) -> str:
    s = (config.REPO / path).read_text().replace("{{XF_UNION}}", XF)
    if kinds:
        s = s.replace("{{KINDS}}", ", ".join(f"'{k}'" for k in kinds.split(",")))
    return s


def wait(d: Dune, eid: str, cap: int = 2100) -> dict:
    t0 = time.time()
    while time.time() - t0 < cap:
        st = d._request("GET", f"/execution/{eid}/status")
        if st["state"] not in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
            return st
        time.sleep(10)
    return d._request("GET", f"/execution/{eid}/status")


def new_query(d: Dune, name: str, sql: str) -> int:
    return d._request("POST", "/query", json={
        "name": f"[flow-research] {name}", "query_sql": sql,
        "is_private": False, "query_engine": "v2 Dune SQL"})["query_id"]


def build_mv(name: str, path: str, kinds: str | None = None) -> None:
    d, rec = Dune(), load()
    full = f"dune.quantbino1695.{name}"
    qid = new_query(d, name, sql_of(path, kinds))
    print(f"query {qid}", flush=True)
    try:
        mv = d._request("POST", "/materialized-views",
                        json={"name": name, "query_id": qid})
    except RuntimeError as exc:
        if "conflicting existing Matview" not in str(exc):
            raise
        prev = d._request("GET", f"/materialized-views/{full}")
        for e in prev.get("last_execution_ids") or []:
            if d._request("GET", f"/execution/{e}/status")["state"] in (
                    "QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
                raise RuntimeError(f"{name}: build {e} still running") from exc
        requests.delete(f"https://api.dune.com/api/v1/materialized-views/{full}",
                        headers={"X-Dune-Api-Key": api_key()}, timeout=90)
        mv = d._request("POST", "/materialized-views",
                        json={"name": name, "query_id": qid})
    t0 = time.time()
    st = wait(d, mv["execution_id"])
    cost = float(st.get("execution_cost_credits") or 0.0)
    print(f"{st['state']}  {cost:.3f} cr  {time.time()-t0:.1f} с")
    if st["state"] != "QUERY_STATE_COMPLETED":
        print(json.dumps(st.get("error"), indent=2)[:700])
    info = (d._request("GET", f"/materialized-views/{full}")
            if st["state"] == "QUERY_STATE_COMPLETED" else {})
    rec[name] = {"query_id": qid, "execution_id": mv["execution_id"],
                 "state": st["state"], "cost": cost,
                 "table_size_bytes": info.get("table_size_bytes"),
                 "error": st.get("error")}
    save(rec)
    if info:
        print(f"table_size_bytes {info.get('table_size_bytes'):,}")


def run_q(name: str, path: str, kinds: str | None = None) -> None:
    d, rec = Dune(), load()
    qid = new_query(d, name, sql_of(path, kinds))
    eid = d._request("POST", f"/query/{qid}/execute",
                     json={"performance": "medium"})["execution_id"]
    st = wait(d, eid)
    cost = float(st.get("execution_cost_credits") or 0.0)
    print(f"{st['state']}  {cost:.3f} cr")
    rows = []
    if st["state"] == "QUERY_STATE_COMPLETED":
        rows = list(d.rows(eid))
        print(f"{len(rows)} мөр")
    else:
        print(json.dumps(st.get("error"), indent=2)[:700])
    rec[name] = {"query_id": qid, "execution_id": eid, "state": st["state"],
                 "cost": cost, "rows": rows, "error": st.get("error")}
    save(rec)


if __name__ == "__main__":
    mode, name, path = sys.argv[1], sys.argv[2], sys.argv[3]
    kinds = sys.argv[4] if len(sys.argv) > 4 else None
    (build_mv if mode == "mv" else run_q)(name, path, kinds)
