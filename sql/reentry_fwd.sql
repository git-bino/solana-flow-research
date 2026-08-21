-- 3 (pass 2) -- what happens after each re-entry trigger.
WITH r AS (SELECT * FROM dune.quantbino1695.result_flow_reentry),
ev AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT r.*, e.seq, e.x
    FROM r JOIN ev e ON e.mint = r.token_mint
      AND e.seq > least(coalesce(r.s32, r.s38), coalesce(r.s35, r.s38), coalesce(r.s38, r.s32))
)
SELECT token_mint, max(x_a) AS x_a, max(anchor_unix) AS anchor_unix,
       max(x32) AS x32, max(u32) AS u32, max(x35) AS x35, max(u35) AS u35,
       max(x38) AS x38, max(u38) AS u38,
       min(if(seq > s32, x)) AS mn32, max(if(seq > s32, x)) AS mx32,
       min(if(seq > s35, x)) AS mn35, max(if(seq > s35, x)) AS mx35,
       min(if(seq > s38, x)) AS mn38, max(if(seq > s38, x)) AS mx38,
       CAST(count_if(seq > s32 AND x >= 60) AS bigint) AS h32,
       CAST(count_if(seq > s35 AND x >= 60) AS bigint) AS h35,
       CAST(count_if(seq > s38 AND x >= 60) AS bigint) AS h38
FROM j GROUP BY token_mint
