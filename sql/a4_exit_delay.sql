-- AUDIT 4 FIX 3 -- exit fill delay Lx in {0, 1, 3, 8} events.
--
-- CAUSAL universe.  Same anchor, entry and triggers as sql/a4_states.sql; only
-- the number of events between the trigger and the fill changes.  FOUR leads are
-- computed in ONE window operator (same PARTITION BY / ORDER BY), so this is one
-- pass over the same rows, not four.
--
-- lead(x, 0) is the trigger event's OWN reserve, i.e. no delay at all.
-- A NULL lead means the fill does not exist -> the position is OPEN at that Lx,
-- and is NOT priced.  NO FALLBACK.
--
-- Token set: only tokens that HAVE an H20 anchor (25,353), not the whole 179,288
-- universe, because the rule never looks at the others.  That makes the join
-- selective; sql/b1_grid_path.sql joined 179,725 mints and cost 6.445 cr.
WITH coh AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_clean WHERE mayhem_flag = false
),
a AS (
    SELECT d.token_mint, d.seq_a, d.x_a, d.anchor_unix
    FROM dune.quantbino1695.result_flow_dd d
    JOIN coh c ON c.token_mint = d.token_mint
    WHERE d.anchor_kind = 'H20'
),
ev0 AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           to_unixtime(t.evt_block_time) AS ut,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN a ON a.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
ev AS (
    SELECT mint, seq, ut, x,
           lead(x, 1) OVER w AS l1,
           lead(x, 3) OVER w AS l3,
           lead(x, 8) OVER w AS l8
    FROM ev0
    WINDOW w AS (PARTITION BY mint ORDER BY seq)
),
en AS (
    SELECT a.token_mint, a.x_a, a.anchor_unix,
           min_by(e.seq, e.seq) AS seq_en, min_by(e.l3, e.seq) AS x_en
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq >= a.seq_a
    GROUP BY a.token_mint, a.x_a, a.anchor_unix
),
j AS (
    SELECT en.token_mint, en.x_en, en.anchor_unix, e.seq, e.ut, e.x, e.l1, e.l3, e.l8
    FROM en JOIN ev e ON e.mint = en.token_mint AND e.seq > en.seq_en
    WHERE en.x_en IS NOT NULL AND en.x_en > 0
)
SELECT token_mint, max(x_en) AS x1,
       min(if(x >= 60.0, seq)) AS g_seq,
       min_by(x,  if(x >= 60.0, seq)) AS g0,
       min_by(l1, if(x >= 60.0, seq)) AS g1,
       min_by(l3, if(x >= 60.0, seq)) AS g3,
       min_by(l8, if(x >= 60.0, seq)) AS g8,
       min(if(ut - anchor_unix >= 60, seq)) AS t_seq,
       min_by(x,  if(ut - anchor_unix >= 60, seq)) AS q0,
       min_by(l1, if(ut - anchor_unix >= 60, seq)) AS q1,
       min_by(l3, if(ut - anchor_unix >= 60, seq)) AS q3,
       min_by(l8, if(ut - anchor_unix >= 60, seq)) AS q8
FROM j GROUP BY token_mint
