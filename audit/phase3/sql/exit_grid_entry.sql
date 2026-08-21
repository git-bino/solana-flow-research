-- Grid, pass A -- the ENTRY, per (clean token, anchor in {H15, H20}).
--
-- Entry = the 3rd TRADE event after the anchor, priced on the reserve THAT event
-- left.  `min_by(x, seq, 3)` returns the first three post-anchor reserves as a
-- bounded array -- no window function.
--
-- The exit conditions in pass B are evaluated on events STRICTLY AFTER the entry:
-- the position does not exist before it fills.  ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР
-- (causal reading; the brief states the three conditions run "at the same time"
-- but a position cannot exit before it is opened).
WITH d AS (
    SELECT token_mint, anchor_kind, seq_a, x_a, anchor_unix, t_a_s
    FROM dune.quantbino1695.result_flow_dd
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
    SELECT d.token_mint, d.anchor_kind, d.seq_a, d.x_a, d.anchor_unix, d.t_a_s,
           e.seq, e.ut, e.x
    FROM d JOIN ev e ON e.mint = d.token_mint AND e.seq > d.seq_a
),
g AS (
    SELECT token_mint, anchor_kind, max(x_a) AS x_a, max(anchor_unix) AS anchor_unix,
           max(t_a_s) AS t_a_s, CAST(count(*) AS bigint) AS n_after,
           min_by(x,   seq, 3) AS xs,
           min_by(seq, seq, 3) AS ss,
           min_by(ut,  seq, 3) AS us,
           max_by(x, seq) AS final_x, max(ut) AS ut_last
    FROM j GROUP BY token_mint, anchor_kind
)
SELECT token_mint, anchor_kind, x_a, anchor_unix, t_a_s, n_after, final_x, ut_last,
       element_at(xs, 3)  AS x_entry,
       element_at(ss, 3)  AS seq_entry,
       element_at(us, 3)  AS ut_entry
FROM g
