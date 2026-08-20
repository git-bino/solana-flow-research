"""Record a matview build that was started by a driver which is no longer running.

  python -m src.adopt_matview <suffix> <slice_from> <slice_to> <execution_id> <query_id>

The cap-removal change killed the driver mid-build.  The Dune execution itself
keeps running -- cancelling is exactly what we stopped doing -- so this waits it
out and writes the same ledger row `build_matview.build` would have written.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.build_matview import LEDGER, cycle_credits  # noqa: E402
from src.ingest_dune import Dune  # noqa: E402


def main() -> None:
    suffix, sfrom, sto, eid, qid = sys.argv[1:6]
    d = Dune()
    name = f"dune.quantbino1695.result_flow_xf_{suffix}"

    t0 = time.time()
    while time.time() - t0 < 2100:
        st = d._request("GET", f"/execution/{eid}/status")
        if st["state"] not in ("QUERY_STATE_EXECUTING", "QUERY_STATE_PENDING"):
            break
        time.sleep(10)
    state = st["state"]

    n_rows = count_cost = None
    info = {}
    if state == "QUERY_STATE_COMPLETED":
        info = d._request("GET", f"/materialized-views/{name}")
        cm = d.run("probe_schemas", f"SELECT count(*) AS n FROM {name}", max_seconds=300)
        n_rows = int(next(iter(d.rows(cm["execution_id"])))["n"])
        cst = d._request("GET", f"/execution/{cm['execution_id']}/status")
        count_cost = float(cst.get("execution_cost_credits") or 0.0)

    rec = {
        "suffix": suffix, "slice_from": sfrom, "slice_to": sto,
        "query_id": int(qid), "execution_id": eid, "sql_id": name,
        "state": state, "seconds": round(time.time() - t0, 1),
        "execution_cost_credits": float(st.get("execution_cost_credits") or 0.0),
        "cycle_delta": None, "cycle_after": cycle_credits(d),
        "table_size_bytes": info.get("table_size_bytes"),
        "n_rows": n_rows, "count_cost_credits": count_cost,
        "error": st.get("error"), "adopted": True,
    }
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
