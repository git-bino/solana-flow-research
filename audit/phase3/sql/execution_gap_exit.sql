-- 1 (exit side) -- the reserve a DELAYED exit would actually get.
--
-- Starts from the crossing `seq` captured by result_flow_gapin, so the barrier
-- is not recomputed.  Same no-window shape: `min_by(x, if(after, seq), 3)`
-- returns the first three post-crossing reserves as an array.
--
-- The join is bounded by `e.seq > (the earlier of the two crossings)`, so only
-- the tail of each token's stream is carried.
--
-- A token with fewer than k events after its crossing yields NULL at that k:
-- the delayed exit never filled.  Kept and counted, never back-filled.
WITH base AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_token_base
),
a AS (
    SELECT token_mint, x_a, seq_u76, seq_u35,
           least(coalesce(seq_u76, seq_u35), coalesce(seq_u35, seq_u76)) AS seq_lo
    FROM dune.quantbino1695.result_flow_gapin
    WHERE seq_u76 IS NOT NULL OR seq_u35 IS NOT NULL
),
ev AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT a.token_mint, e.seq, e.x,
           a.seq_u76 IS NOT NULL AND e.seq > a.seq_u76 AS af76,
           a.seq_u35 IS NOT NULL AND e.seq > a.seq_u35 AS af35
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_lo
),
g AS (
    SELECT token_mint,
           min_by(x, if(af76, seq), 3) AS a76,
           min_by(x, if(af35, seq), 3) AS a35,
           CAST(count_if(af76) AS bigint) AS n76,
           CAST(count_if(af35) AS bigint) AS n35
    FROM j GROUP BY token_mint
)
SELECT token_mint, n76, n35,
       element_at(a76, 1) AS x76_e1, element_at(a76, 3) AS x76_e3,
       element_at(a35, 1) AS x35_e1, element_at(a35, 3) AS x35_e3
FROM g
