"""Aggregate probes over the transfer-enabled extract_v2 -- sections 1, 2, 3.

  python -m src.trial_v2_probe

Nothing is exported: every number below is computed on Dune and comes back as a
single row.  The extract's own SELECT is turned into a CTE named `final` so the
burst-level checks (§1 asserts, §2 oh_a vs oh_b) read it, while the ledger-level
checks (§3) read `wat` and `xf` directly -- both already defined in the same
statement, so neither block re-runs the pipeline.

Two single-row blocks are CROSS JOINed rather than twelve scalar subqueries.
Probe A2 died at Dune's 30-minute limit for 164.755 credits with twelve of them
over one heavy CTE (docs/redesign_probe.md); two is the smallest arrangement that
still answers both halves in one execution.
ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (the shape of the probe, not what it measures).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.trial_v2_transfers import build, execute  # noqa: E402

MARKER = "SELECT\n    -- identity and ordering (fix 2: the raw pair, no packing)"

#: §1 asserts and §2, over one row per burst.
BURST_BLOCK = """
burst_agg AS (
  SELECT count(*)                                                    AS n_rows,
         count(DISTINCT token_mint)                                  AS n_tokens,
         count_if(traj_len <> 75)                                    AS bad_traj,
         count_if(oh_a < 0)                                          AS bad_oh_a,
         count_if(oh_b < 0)                                          AS bad_oh_b,
         count_if(oh_conc_a < 0 OR oh_conc_a > 1)                     AS bad_conc_a,
         count_if(oh_conc_b < 0 OR oh_conc_b > 1)                     AS bad_conc_b,
         -- §2: oh_a vs oh_b
         count_if(oh_a = oh_b)                                       AS n_equal,
         count_if(oh_b > oh_a)                                       AS n_b_gt_a,
         count_if(oh_b < oh_a)                                       AS n_b_lt_a,
         approx_percentile(if(oh_a <> oh_b,
             (oh_b - oh_a) / greatest(oh_a, oh_b, 1), NULL), 0.5)     AS d_oh_p50,
         approx_percentile(if(oh_a <> oh_b,
             (oh_b - oh_a) / greatest(oh_a, oh_b, 1), NULL), 0.9)     AS d_oh_p90,
         approx_percentile(if(oh_a <> oh_b,
             (oh_b - oh_a) / greatest(oh_a, oh_b, 1), NULL), 0.99)    AS d_oh_p99,
         max(if(oh_a <> oh_b,
             (oh_b - oh_a) / greatest(oh_a, oh_b, 1), NULL))          AS d_oh_max,
         count_if(oh_ratio_a = oh_ratio_b)                           AS n_ratio_equal,
         approx_percentile(if(oh_ratio_a <> oh_ratio_b,
             (oh_ratio_b - oh_ratio_a)
             / greatest(oh_ratio_a, oh_ratio_b, 1), NULL), 0.5)       AS d_ratio_p50,
         max(if(oh_ratio_a <> oh_ratio_b,
             (oh_ratio_b - oh_ratio_a)
             / greatest(oh_ratio_a, oh_ratio_b, 1), NULL))            AS d_ratio_max,
         count_if(oh_conc_a = oh_conc_b)                             AS n_conc_equal,
         approx_percentile(if(oh_conc_a <> oh_conc_b,
             (oh_conc_b - oh_conc_a)
             / greatest(oh_conc_a, oh_conc_b, 1), NULL), 0.5)         AS d_conc_p50,
         max(if(oh_conc_a <> oh_conc_b,
             (oh_conc_b - oh_conc_a)
             / greatest(oh_conc_a, oh_conc_b, 1), NULL))              AS d_conc_max,
         count_if(oh_n_wallets_b > oh_n_wallets_a)                    AS n_wal_more,
         count_if(oh_n_wallets_b < oh_n_wallets_a)                    AS n_wal_fewer,
         sum(oh_n_wallets_b - oh_n_wallets_a)                         AS wal_delta_sum,
         max(oh_n_wallets_b - oh_n_wallets_a)                         AS wal_delta_max,
         sum(held_from_transfers)                                     AS held_xfer_sum,
         sum(held_from_buys)                                          AS held_buys_sum
  FROM final
)"""

#: §3, corrected.  `cum_xf_units` counts INBOUND units only -- `pos` puts 0 in
#: `d_units_xf` on the transfer-out leg and `units` on the transfer-in leg -- so a
#: sender is invisible to it even though its `held` is reduced by `d_units`.
#: Counting "pairs whose held moved because of a transfer" therefore has to go to
#: `run`, which carries `kind` (0 trade, 1 transfer-out, 2 transfer-in), and count
#: distinct (mint, wallet) pairs per leg.
LEDGER2_BLOCK = """
pair_agg AS (
  SELECT count(DISTINCT (mint, wallet))                                AS n_pairs,
         count(DISTINCT if(kind = 1, (mint, wallet), NULL))            AS n_sent,
         count(DISTINCT if(kind = 2, (mint, wallet), NULL))            AS n_recv,
         count(DISTINCT if(kind <> 0, (mint, wallet), NULL))           AS n_either,
         count(DISTINCT if(held < 0, (mint, wallet), NULL))            AS n_neg_pairs
  FROM run
),
neg_agg AS (
  SELECT count(DISTINCT (mint, wallet)) AS n_neg_with_xfer
  FROM run r
  WHERE r.held < 0
    AND (r.mint, r.wallet) IN (SELECT mint, wallet FROM run WHERE kind <> 0)
),
tol_agg AS (
  SELECT count_if(abs(oh_b - oh_a) / greatest(abs(oh_a), abs(oh_b), 1) > 1e-12)
             AS n_oh_real_diff,
         count_if(abs(oh_ratio_b - oh_ratio_a)
                  / greatest(abs(oh_ratio_a), abs(oh_ratio_b), 1) > 1e-12)
             AS n_ratio_real_diff,
         count_if(abs(oh_conc_b - oh_conc_a)
                  / greatest(abs(oh_conc_a), abs(oh_conc_b), 1) > 1e-12)
             AS n_conc_real_diff
  FROM final
)"""

#: §3, over the per-burst wallet state and the transfer rows themselves.
LEDGER_BLOCK = """
ledger_agg AS (
  SELECT count(*)                                            AS n_wallet_rows,
         count_if(cum_xf_units <> 0)                         AS n_touched,
         count_if(held < 0)                                  AS n_negative_held,
         count_if(held < 0 AND cum_xf_units = 0)             AS n_neg_untouched,
         count_if(cum_xf_units > 0)                          AS n_net_receiver,
         count_if(cum_xf_units < 0)                          AS n_net_sender,
         count_if(inherited_units > 0)                       AS n_inherited,
         count_if(held_from_buys_approx <= 0 AND held > 0)    AS n_holds_only_xfer
  FROM wat
),
xf_agg AS (
  SELECT count(*)                                            AS n_transfers,
         count(DISTINCT to_owner)                            AS n_recipients,
         count(DISTINCT from_owner)                          AS n_senders,
         count(DISTINCT mint)                                AS n_xfer_mints,
         -- re-transmission: an owner that both received and sent for the same
         -- mint.  This is exactly the one hop the SQL basis chain models; a
         -- second hop inherits a basis of zero.
         count(DISTINCT if(to_owner IN (SELECT from_owner FROM xf),
                           to_owner, NULL))                  AS n_forwarders
  FROM xf
)"""


def probe_sql(second: bool = False) -> str:
    sql = build(include_transfers="true")
    head, tail = sql.split(MARKER, 1)
    final_select = MARKER + tail
    # `head` ends at the close of the last CTE (`cb_variants`), which in the
    # original statement is followed directly by the final SELECT -- so there is
    # no comma there.  Turning that SELECT into another CTE needs one.
    return (
        head.rstrip() + ",\n"
        + "final AS (\n" + final_select.rstrip().rstrip(";") + "\n),"
        + (LEDGER2_BLOCK + "\n"
           + "SELECT * FROM pair_agg CROSS JOIN neg_agg CROSS JOIN tol_agg\n"
           if second else
           BURST_BLOCK + "," + LEDGER_BLOCK + "\n"
           + "SELECT * FROM burst_agg CROSS JOIN ledger_agg CROSS JOIN xf_agg\n")
    )


def main() -> None:
    second = "2" in sys.argv
    sql = probe_sql(second=second)
    if "sql" in sys.argv:
        print(sql)
        return
    from src.ingest_dune import Dune
    rec = execute("extract_v2_xfer_probe2" if second else "extract_v2_xfer_probe", sql)
    print(json.dumps(rec, indent=2))
    if rec["state"] == "QUERY_STATE_COMPLETED":
        d = Dune()
        for row in d.rows(rec["execution_id"]):
            print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()
