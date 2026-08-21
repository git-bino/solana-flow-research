-- 1 + 2 -- decomposing the 37.44% / 62.56% split at the H20 anchor.
--
-- CLEAN universe only: max|x*y/k0 - 1| < 1e-6.
--
-- WINDOW.  The whole point is the path BEFORE the outcome is known, so the
-- window is anchor-exclusive to 60-crossing-inclusive:
--     seq > seq_a  AND  (seq_60 IS NULL OR seq <= seq_60)
-- For a winner that ends at the first x >= 60 (the 60-event itself cannot lower
-- the minimum).  For a loser seq_60 is NULL and the window is the whole forward
-- path.  This is why `min_x_win` is NOT `result_flow_hpath_b.min_x_after`, which
-- runs past the crossing and would mix post-outcome depth into a winner's path.
--
-- TARGET.  win = `seq_60 IS NOT NULL` in result_flow_dd, i.e. x >= 60 reached
-- AFTER the anchor.  This is the same definition §1-§4 of the previous step used
-- and is NOT `token_base.max_x >= 60`, which also counts a token that was above
-- 60 before the anchor.
--
-- CLUSTER.  `ld` = launch date, carried for the launch-day cluster bootstrap.
WITH cu AS (
    SELECT token_mint, lifetime_s,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint, lifetime_s FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
a AS (
    SELECT d.token_mint, d.seq_a, d.x_a, d.t_a_s, d.anchor_unix, d.seq_60,
           d.seq_drop, d.max_x_after, d.final_x, c.lifetime_s,
           date(b.launch_time) AS ld
    FROM dune.quantbino1695.result_flow_dd d
    JOIN coh c ON c.token_mint = d.token_mint
    JOIN dune.quantbino1695.result_flow_token_base b ON b.token_mint = d.token_mint
    WHERE d.anchor_kind = 'H20'
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
    SELECT a.token_mint, a.ld, a.x_a, a.t_a_s, a.anchor_unix, a.seq_60,
           a.max_x_after, a.final_x, a.lifetime_s,
           e.seq, e.ut, e.x,
           (a.seq_60 IS NULL OR e.seq <= a.seq_60) AS inw
    FROM a JOIN ev e ON e.mint = a.token_mint AND e.seq > a.seq_a
)
SELECT token_mint, max(ld) AS ld, max(x_a) AS x_a, max(t_a_s) AS t_a_s,
       max(seq_60) IS NOT NULL AS win,
       max(lifetime_s) AS lifetime_s,
       max(max_x_after) AS max_x_after, max(final_x) AS final_x,
       CAST(count_if(inw) AS bigint) AS n_win_ev,
       min(if(inw, x)) AS min_x_win,
       max(if(inw, x)) AS max_x_win,
       min(if(inw AND x >= 60, ut)) - max(anchor_unix) AS t_60_s,
       min(if(inw AND x <= x_a * 0.95, ut)) - max(anchor_unix) AS t_d5,
       min(if(inw AND x <= x_a * 0.90, ut)) - max(anchor_unix) AS t_d10,
       min(if(inw AND x <= x_a * 0.85, ut)) - max(anchor_unix) AS t_d15,
       min(if(inw AND x <= x_a * 0.80, ut)) - max(anchor_unix) AS t_d20
FROM j GROUP BY token_mint
