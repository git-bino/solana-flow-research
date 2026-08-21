-- 3 (stage A) -- when the LARGEST seller stopped.  Matview.
--
-- Largest seller = the wallet with the most token units sold in the
-- anchor -> drawdown window (result_flow_ddsell).
--
-- STOP (pre-registered reading): the first sell by that wallet at or after the
-- anchor such that its NEXT sell is more than 60 s later, or there is none.
-- "holding hit zero" is captured as a separate flag rather than folded in, so
-- the two halves of the brief's definition stay distinguishable.
--
-- The `lead` window runs over ONE wallet per token, so it is small; the cost is
-- the tradeevent scan, not the window.
WITH top AS (
    SELECT token_mint, anchor_kind,
           max_by(wallet, sold_units) AS w,
           max_by(cls, sold_units)    AS cls,
           max(sold_units)            AS top_units,
           sum(sold_units)            AS all_units
    FROM dune.quantbino1695.result_flow_ddsell
    WHERE sold_units > 0
    GROUP BY token_mint, anchor_kind
),
a AS (
    SELECT t.token_mint, t.anchor_kind, t.w, t.cls, t.top_units, t.all_units,
           d.seq_a, d.seq_drop, d.x_a, d.anchor_unix
    FROM top t JOIN dune.quantbino1695.result_flow_dd d
      ON d.token_mint = t.token_mint AND d.anchor_kind = t.anchor_kind
    WHERE d.seq_drop IS NOT NULL
),
sl AS (
    SELECT a.token_mint, a.anchor_kind, a.cls, a.x_a, a.anchor_unix,
           a.top_units, a.all_units,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           to_unixtime(t.evt_block_time) AS ut,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM a
    JOIN pumpdotfun_solana.pump_evt_tradeevent t
      ON t.mint = a.token_mint AND t.user = a.w AND NOT t.is_buy
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
),
f AS (SELECT * FROM sl WHERE seq > (SELECT 0)),
g AS (
    SELECT f.*,
           lead(ut) OVER (PARTITION BY token_mint, anchor_kind ORDER BY seq) AS nxt
    FROM f
),
stop AS (
    SELECT token_mint, anchor_kind,
           min_by(seq, seq) AS dummy,
           min(if(nxt IS NULL OR nxt - ut > 60, seq)) AS seq_stop,
           min_by(ut, if(nxt IS NULL OR nxt - ut > 60, seq)) AS ut_stop,
           min_by(x,  if(nxt IS NULL OR nxt - ut > 60, seq)) AS x_stop,
           max(cls) AS cls, max(x_a) AS x_a, max(anchor_unix) AS anchor_unix,
           max(top_units) AS top_units, max(all_units) AS all_units,
           CAST(count(*) AS bigint) AS n_sells_total
    FROM g GROUP BY token_mint, anchor_kind
)
SELECT token_mint, anchor_kind, cls, x_a, anchor_unix,
       seq_stop, ut_stop, x_stop, top_units, all_units, n_sells_total,
       top_units / nullif(all_units, 0) AS top_share_of_sold
FROM stop
WHERE seq_stop IS NOT NULL
