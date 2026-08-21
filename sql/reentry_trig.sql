-- 3 (pass 1) -- re-entry trigger AFTER the drawdown.
-- The entry is when x comes DOWN to the level: the first event at or after the
-- drawdown with x <= L, for L in {32, 35, 38}.  Stated explicitly because
-- "reach 32" upward from the anchor would be a different (and impossible) event
-- -- x_a median is 43.83, above all three levels.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
a AS (
    SELECT d.token_mint, d.seq_drop, d.x_a, d.anchor_unix
    FROM dune.quantbino1695.result_flow_dd d JOIN coh c ON c.token_mint = d.token_mint
    WHERE d.anchor_kind = 'H20' AND d.seq_drop IS NOT NULL
),
ev AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           to_unixtime(t.evt_block_time) AS ut,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT a.token_mint, a.x_a, a.anchor_unix, e.seq, e.ut, e.x
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq >= a.seq_drop
)
SELECT token_mint, max(x_a) AS x_a, max(anchor_unix) AS anchor_unix,
       min(if(x <= 32, seq)) AS s32, min_by(x, if(x <= 32, seq)) AS x32,
       min(if(x <= 32, ut))  AS u32,
       min(if(x <= 35, seq)) AS s35, min_by(x, if(x <= 35, seq)) AS x35,
       min(if(x <= 35, ut))  AS u35,
       min(if(x <= 38, seq)) AS s38, min_by(x, if(x <= 38, seq)) AS x38,
       min(if(x <= 38, ut))  AS u38
FROM j GROUP BY token_mint
