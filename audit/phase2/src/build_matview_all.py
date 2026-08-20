"""Drive the remaining transfer matview slices, with the mechanical stop rule.

  python -m src.build_matview_all <start_date> <end_date> <days_per_slice> \
                                 <budget_left> <first_suffix>

Stops before any slice whose estimated cost fails `remaining < est * 1.3`, and
stops immediately on a failed build so the slice size can be reconsidered rather
than repeated 15 times.  Every slice's real cost lands in
results/matview_slices.jsonl via `build_matview.build`.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.build_matview import build  # noqa: E402

#: Measured on slice 02 (2026-05-10..05-15, the heaviest six days of the
#: window): 7.179 credits over 6 block_date partitions.
CREDITS_PER_DAY = 7.178970589 / 6


def main() -> None:
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    step = int(sys.argv[3])
    remaining = float(sys.argv[4])
    suffix = int(sys.argv[5])

    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=step - 1), end)
        ndays = (stop - cur).days + 1
        est = CREDITS_PER_DAY * ndays
        if remaining < est * 1.3:
            print(f"STOP: remaining {remaining:.2f} < est {est:.2f} x 1.3 "
                  f"= {est * 1.3:.2f}; {cur} onwards not built")
            return
        print(f"[{suffix:02d}] {cur} .. {stop}  ({ndays}d, est {est:.2f} cr, "
              f"remaining {remaining:.2f})", flush=True)
        rec = build(f"{suffix:02d}", cur.isoformat(), stop.isoformat())
        # Cycle usage lags behind by minutes, so the per-execution cost is the
        # authoritative figure to draw the budget down with.
        spent = rec["execution_cost_credits"] + (rec.get("count_cost_credits") or 0.0)
        remaining -= spent
        print(f"     -> {rec['state']} {rec['seconds']}s  {spent:.3f} cr  "
              f"rows={rec['n_rows']}  size={rec['table_size_bytes']}  "
              f"remaining {remaining:.2f}", flush=True)
        if rec["state"] == "QUERY_STATE_FAILED" and ndays > 3:
            # Dune's own failure costs 0, so a failed 6-day slice is re-cut into
            # 3-day halves rather than abandoning the window.  Slice widths are
            # therefore not uniform; the ledger records each one.
            print(f"     retry {cur}..{stop} as 3-day halves", flush=True)
            sub = cur
            while sub <= stop:
                sub_stop = min(sub + timedelta(days=2), stop)
                suffix += 1
                print(f"[{suffix:02d}] {sub} .. {sub_stop}  (3d retry)", flush=True)
                r2 = build(f"{suffix:02d}", sub.isoformat(), sub_stop.isoformat())
                spent2 = r2["execution_cost_credits"] + (r2.get("count_cost_credits") or 0.0)
                remaining -= spent2
                print(f"     -> {r2['state']} {r2['seconds']}s  {spent2:.3f} cr  "
                      f"rows={r2['n_rows']}  remaining {remaining:.2f}", flush=True)
                if r2["state"] != "QUERY_STATE_COMPLETED":
                    print(f"STOP: 3-day slice {sub} also {r2['state']}")
                    return
                sub = sub_stop + timedelta(days=1)
        elif rec["state"] != "QUERY_STATE_COMPLETED":
            print(f"STOP: {rec['state']} — {rec.get('error')}")
            return
        cur = stop + timedelta(days=1)
        suffix += 1
    print(f"DONE through {end}; remaining {remaining:.2f}")


if __name__ == "__main__":
    main()
