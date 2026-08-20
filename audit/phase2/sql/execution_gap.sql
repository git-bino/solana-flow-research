-- 1 -- ENTRY-side execution gap: the reserve a delayed fill would actually get.
--
-- The model prices entry at `x_a`, the reserve the anchor event left.  A real
-- order is sent after that and lands some events later.  This pass captures the
-- reserve at those later events.
--
-- NO WINDOW FUNCTION.  `min_by(x, seq, 8)` returns an ARRAY of the x values
-- belonging to the 8 smallest `seq` -- the first eight events after the anchor,
-- in order -- as a bounded-memory aggregate.  A `row_number()` window over the
-- forward stream would need a partitioned sort of ~9M rows; the anchor for that
-- is `result_flow_holder_anchor` (two such sorts, 24.466 cr).  This form keeps
-- the query in the same shape and cost class as `result_flow_hbar` (3.268 cr).
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (cost engineering; the delays and their
-- definitions are exactly what the task specified).
--
-- DEATH INSIDE THE DELAY.  If the token has fewer than k events after the
-- anchor, `element_at` returns NULL: the fill never happened.  Those rows are
-- KEPT and counted as "not traded", never dropped and never back-filled.
--
-- The crossing `seq` for the +76% and +135% barriers is captured here too, so
-- the exit-side pass can start from it without recomputing the barrier.
WITH base AS (
    SELECT token_mint, launch_time FROM dune.quantbino1695.result_flow_token_base
),
a AS (
    SELECT h.token_mint, h.seq_a, h.t_a_s, h.x_a,
           to_unixtime(b.launch_time) + h.t_a_s AS anchor_unix
    FROM dune.quantbino1695.result_flow_holder_anchor h
    JOIN base b ON b.token_mint = h.token_mint
    WHERE h.anchor_kind = 'H3'
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
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT a.token_mint, a.x_a, a.t_a_s, a.anchor_unix, e.seq, e.ut, e.x,
           e.ut >= a.anchor_unix + 0.4  AS d04,
           e.ut >= a.anchor_unix + 1.2  AS d12,
           e.ut >= a.anchor_unix + 3.2  AS d32,
           e.x  >= a.x_a * 1.76         AS c76,
           e.x  >= a.x_a * 2.35         AS c35
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_a
),
g AS (
    SELECT token_mint, x_a, t_a_s, anchor_unix,
           CAST(count(*) AS bigint) AS n_after,
           min_by(x,  seq, 8) AS xs,          -- first eight events, in order
           min_by(ut, seq, 8) AS uts,
           -- time-delayed fills: first event at or after anchor + d seconds
           min_by(x, if(d04, seq)) AS x_t04,
           min_by(x, if(d12, seq)) AS x_t12,
           min_by(x, if(d32, seq)) AS x_t32,
           min_by(ut, if(d04, seq)) AS u_t04,
           min_by(ut, if(d12, seq)) AS u_t12,
           min_by(ut, if(d32, seq)) AS u_t32,
           -- crossing seq for the two targets the executable cells use
           min(if(c76, seq)) AS seq_u76,
           min(if(c35, seq)) AS seq_u35,
           max_by(x, seq) AS final_x,
           max(ut) AS ut_last
    FROM j GROUP BY token_mint, x_a, t_a_s, anchor_unix
)
SELECT token_mint, x_a, t_a_s, n_after, final_x,
       ut_last - anchor_unix AS t_final_s,
       seq_u76, seq_u35,
       element_at(xs, 1) AS x_e1, element_at(xs, 3) AS x_e3, element_at(xs, 8) AS x_e8,
       element_at(uts, 1) - anchor_unix AS t_e1,
       element_at(uts, 3) - anchor_unix AS t_e3,
       element_at(uts, 8) - anchor_unix AS t_e8,
       x_t04, x_t12, x_t32,
       u_t04 - anchor_unix AS t_t04,
       u_t12 - anchor_unix AS t_t12,
       u_t32 - anchor_unix AS t_t32
FROM g
