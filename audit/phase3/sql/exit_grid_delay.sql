-- Grid, pass C -- the DELAYED exit price for each stop/target trigger.
-- Exit fills 3 trade events after the condition is met; the reserve used is the
-- one that event LEFT (overshoot), never the threshold value.
-- Fewer than 3 events after the trigger -> NULL, and the aggregation falls back
-- to the observed `final_x` (the position is still open at the window edge).
WITH t AS (SELECT * FROM dune.quantbino1695.result_flow_eg_trig),
ev AS (
    SELECT t2.mint,
           CAST(t2.evt_block_slot AS bigint) * 1000000000
             + CAST(t2.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t2.evt_outer_instruction_index, 0) * 64
                    + coalesce(t2.evt_inner_instruction_index, 0) AS bigint) AS seq,
           CAST(t2.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t2
    WHERE t2.evt_block_date >= DATE '2026-05-10' AND t2.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT t.token_mint, t.anchor_kind, t.s95, t.s90, t.s85, t.g60, t.g70, t.g15,
           e.seq, e.x
    FROM t JOIN ev e ON e.mint = t.token_mint
      AND e.seq > least(coalesce(t.s95, t.g60), coalesce(t.g60, t.s95),
                        coalesce(t.s90, t.g60), coalesce(t.s85, t.g60),
                        coalesce(t.g70, t.g60), coalesce(t.g15, t.g60))
)
SELECT token_mint, anchor_kind,
       element_at(min_by(x, if(seq > s95, seq), 3), 3) AS x95,
       element_at(min_by(x, if(seq > s90, seq), 3), 3) AS x90,
       element_at(min_by(x, if(seq > s85, seq), 3), 3) AS x85,
       element_at(min_by(x, if(seq > g60, seq), 3), 3) AS xg60,
       element_at(min_by(x, if(seq > g70, seq), 3), 3) AS xg70,
       element_at(min_by(x, if(seq > g15, seq), 3), 3) AS xg15
FROM j GROUP BY token_mint, anchor_kind
