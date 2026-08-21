"""Run the growth-identification measurement at each observation point.

  python -m src.growth_identification 10 30 60 300

One Dune execution per observation point T (seconds since launch).  The SQL is
`sql/growth_identification.sql` with {{T}} substituted; results land in
results/growth_identification.json.

Tokens that already crossed the threshold before T are NOT dropped from the
cohort -- they are counted and reported per point, and excluded only from the
AUC/decile base, which is the population a decision at T could still act on.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.ingest_dune import Dune  # noqa: E402

SQL = config.REPO / "sql" / "growth_identification.sql"
OUT = config.RESULTS / "growth_identification.json"


def run_point(d: Dune, T: int) -> dict:
    sql = SQL.read_text().replace("{{T}}", str(T))
    q = d._request("POST", "/query", json={
        "name": f"[flow-research] growth identification T={T}s",
        "query_sql": sql, "is_private": False, "query_engine": "v2 Dune SQL"})
    qid = q["query_id"]
    eid = d._request("POST", f"/query/{qid}/execute",
                     json={"performance": "medium"})["execution_id"]
    print(f"  T={T}s: query {qid}, exec {eid}", flush=True)
    t0 = time.time()
    while time.time() - t0 < 2100:
        st = d._request("GET", f"/execution/{eid}/status")
        if st["state"] not in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
            break
        time.sleep(10)
    cost = float(st.get("execution_cost_credits") or 0.0)
    rec = {"T": T, "query_id": qid, "execution_id": eid, "state": st["state"],
           "cost": cost, "seconds": round(time.time() - t0, 1)}
    if st["state"] == "QUERY_STATE_COMPLETED":
        rec["rows"] = list(d.rows(eid))
        auc = [r for r in rec["rows"] if r["kind"] == "auc"]
        print(f"    {st['state']} {cost:.3f} cr  {len(rec['rows'])} мөр")
        for r in sorted(auc, key=lambda x: -abs((x["auc60"] or 0.5) - 0.5))[:5]:
            print(f"      {r['name']:15} n+ {r['n_pos']:>6,}  n− {r['n_neg']:>7,}  "
                  f"AUC60 {r['auc60']:.4f}  AUC115 {r['auc115']:.4f}")
    else:
        rec["error"] = st.get("error")
        print(f"    {st['state']}: {str(st.get('error'))[:200]}")
    return rec


def main() -> None:
    points = [int(x) for x in sys.argv[1:]] or [10, 30, 60, 300]
    d = Dune()
    before = float(d._request("POST", "/usage", json={})
                   ["billing_periods"][0]["credits_used"])
    out = {"points": [], "cohort_window": "[2026-05-10, 2026-05-19)"}
    for T in points:
        out["points"].append(run_point(d, T))
    after = float(d._request("POST", "/usage", json={})
                  ["billing_periods"][0]["credits_used"])
    out["credits"] = {"before": before, "after": after,
                      "sum_execution": sum(p["cost"] for p in out["points"])}
    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nнийт execution {out['credits']['sum_execution']:.3f} cr -> {OUT}")


if __name__ == "__main__":
    main()
