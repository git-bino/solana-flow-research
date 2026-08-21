-- 1 -- holder turnover between the H20 anchor and the drawdown, and the outcome
-- that follows.  CLEAN universe only.
--
-- Per wallet: `u_anchor` = balance at the anchor, `u_drop` = balance at the
-- drawdown, both TRANSFER-AWARE (all legs, trades and transfers).
--   fully exited : u_anchor > 0 and u_drop <= 0
--   partially sold: u_anchor > 0, u_drop > 0, u_drop < u_anchor
--   new entrant  : u_anchor <= 0 and u_drop > 0
-- Token-level counts are aggregated in the SAME query (nested GROUP BY), so the
-- event stream is scanned once.
--
-- Bins on the CHANGE in holder count at the drawdown (the anchor is 20 by
-- construction): 20+ (grew) / 18-20 / 14-17 / 10-13 / <10.
WITH cu AS (
    SELECT token_mint, lifetime_s,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint, lifetime_s FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
a AS (
    SELECT d.token_mint, d.seq_a, d.seq_drop, d.x_a, d.x_drop, d.max_x_after,
           d.final_x, d.seq_60, c.lifetime_s
    FROM dune.quantbino1695.result_flow_dd d
    JOIN coh c ON c.token_mint = d.token_mint
    WHERE d.anchor_kind = 'H20' AND d.seq_drop IS NOT NULL
),
tr AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000
             + CAST(coalesce(t.evt_outer_instruction_index, 0) * 64
                    + coalesce(t.evt_inner_instruction_index, 0) AS bigint) AS seq,
           t.user AS w,
           if(t.is_buy, CAST(t.token_amount AS double),
                       -CAST(t.token_amount AS double)) AS du
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
xf_raw AS (
    SELECT token_mint_address AS mint,
           CAST(block_slot AS bigint) * 1000000000
             + CAST(tx_index AS bigint) * 10000
             + CAST(coalesce(outer_ix_index, 0) * 64
                    + coalesce(inner_ix_index, 0) AS bigint) AS seq,
           from_owner, to_owner, CAST(amount AS double) AS amount
    FROM ({{XF_UNION}}) u
    WHERE block_date >= DATE '2026-05-10' AND block_date <= DATE '2026-08-15'
),
legs AS (
    SELECT mint, seq, w, du FROM tr
    UNION ALL SELECT mint, seq, to_owner,    amount FROM xf_raw
    UNION ALL SELECT mint, seq, from_owner, -amount FROM xf_raw
),
wl AS (
    SELECT a.token_mint, l.w,
           sum(if(l.seq <= a.seq_a, l.du, 0.0))    AS u_anchor,
           sum(l.du)                               AS u_drop
    FROM a JOIN legs l ON l.mint = a.token_mint AND l.seq <= a.seq_drop
    GROUP BY a.token_mint, l.w
),
tk AS (
    SELECT token_mint,
           CAST(count_if(u_drop > 0) AS bigint)                            AS n_hold_drop,
           CAST(count_if(u_anchor > 0 AND u_drop <= 0) AS bigint)          AS n_exit,
           CAST(count_if(u_anchor > 0 AND u_drop > 0 AND u_drop < u_anchor) AS bigint) AS n_part,
           CAST(count_if(u_anchor <= 0 AND u_drop > 0) AS bigint)          AS n_new,
           CAST(count_if(u_anchor > 0 AND u_drop > 0) AS bigint)           AS n_of20_left
    FROM wl GROUP BY token_mint
),
j AS (
    SELECT a.*, tk.n_hold_drop, tk.n_exit, tk.n_part, tk.n_new, tk.n_of20_left,
           r.min_x_after_drop, r.t_back_to_xa, r.t_to_60,
           CASE WHEN tk.n_hold_drop >= 21 THEN '1_grew'
                WHEN tk.n_hold_drop >= 18 THEN '2_18to20'
                WHEN tk.n_hold_drop >= 14 THEN '3_14to17'
                WHEN tk.n_hold_drop >= 10 THEN '4_10to13'
                ELSE '5_lt10' END AS bin
    FROM a JOIN tk ON tk.token_mint = a.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_ddrec r
             ON r.token_mint = a.token_mint AND r.anchor_kind = 'H20'
)
SELECT bin, CAST(count(*) AS double) AS n,
       approx_percentile(CAST(n_hold_drop AS double), 0.50) AS hd50,
       approx_percentile(CAST(n_exit AS double), 0.50)      AS ex50,
       approx_percentile(CAST(n_part AS double), 0.50)      AS pt50,
       approx_percentile(CAST(n_new AS double), 0.50)       AS nw50,
       approx_percentile(CAST(n_of20_left AS double), 0.50) AS lf50,
       approx_percentile(min_x_after_drop / x_drop, 0.50)   AS md50,
       approx_percentile(min_x_after_drop / x_drop, 0.90)   AS md90,
       CAST(count_if(seq_60 IS NOT NULL) AS double)/count(*) AS s60,
       CAST(count_if(t_back_to_xa IS NOT NULL) AS double)/count(*) AS s_back,
       approx_percentile(t_back_to_xa, 0.50) AS tb50,
       approx_percentile(max_x_after / x_a, 0.50) AS mr50,
       approx_percentile(max_x_after / x_a, 0.95) AS mr95,
       approx_percentile(lifetime_s, 0.50) AS life50
FROM j
GROUP BY GROUPING SETS ((), (bin))
ORDER BY bin
