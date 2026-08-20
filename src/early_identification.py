"""Early observation points, distribution vs growth.

  python -m src.early_identification 5 10 15

One Dune execution per point T (seconds since launch), reading the token-level
matview `dune.quantbino1695.result_flow_token_base` instead of rescanning the
98-day event window.  Results append to results/early_identification.json.

Cheapening measured: 36.962 cr per point before, 6.497 after -- prior_count
dropped, labels from the matview, and AUC switched to mid-ranks.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.ingest_dune import Dune  # noqa: E402

SQL = config.REPO / "sql" / "early_identification.sql"
OUT = config.RESULTS / "early_identification.json"
COHORT = 262_129


def run_point(d: Dune, T: int) -> dict:
    sql = SQL.read_text().replace("{{T}}", str(T))
    qid = d._request("POST", "/query", json={
        "name": f"[flow-research] early ident T={T}s", "query_sql": sql,
        "is_private": False, "query_engine": "v2 Dune SQL"})["query_id"]
    eid = d._request("POST", f"/query/{qid}/execute",
                     json={"performance": "medium"})["execution_id"]
    t0 = time.time()
    while time.time() - t0 < 2100:
        st = d._request("GET", f"/execution/{eid}/status")
        if st["state"] not in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
            break
        time.sleep(10)
    cost = float(st.get("execution_cost_credits") or 0.0)
    rec = {"T": T, "query_id": qid, "execution_id": eid,
           "state": st["state"], "cost": cost}
    if st["state"] == "QUERY_STATE_COMPLETED":
        rec["rows"] = list(d.rows(eid))
        auc = [r for r in rec["rows"] if r["kind"] == "auc"]
        n1, n0 = auc[0]["n_pos"], auc[0]["n_neg"]
        rec |= {"n_pos": n1, "n_neg": n0, "base": n1 / (n1 + n0),
                "already_late": COHORT - (n1 + n0)}
        print(f"  T={T}s  {cost:.3f} cr  хожимдсон {rec['already_late']:,} "
              f"({100*rec['already_late']/COHORT:.2f}%)  суурь {100*rec['base']:.4f}%")
        for r in sorted(auc, key=lambda x: -abs(x["auc60"] - 0.5))[:5]:
            print(f"    {r['name']:16} {r['auc60']:.4f} / {r['auc115']:.4f}")
    else:
        rec["error"] = st.get("error")
        print(f"  T={T}s  {st['state']}: {str(st.get('error'))[:160]}")
    return rec


def main() -> None:
    points = [int(x) for x in sys.argv[1:]] or [5, 10, 15]
    d = Dune()
    out = json.loads(OUT.read_text()) if OUT.exists() else {"points": []}
    have = {p["T"] for p in out["points"]}
    for T in points:
        if T in have:
            print(f"  T={T}s аль хэдийн бий, алгаслаа")
            continue
        out["points"].append(run_point(d, T))
        OUT.write_text(json.dumps(out, indent=2))
    print(f"\nнийт {sum(p['cost'] for p in out['points']):.3f} cr -> {OUT}")


if __name__ == "__main__":
    main()
