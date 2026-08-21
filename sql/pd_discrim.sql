-- 3 + 4 -- discrimination of the eight variables, and the stop-space table.
--
-- ONE source scan.  The eight variables are unpivoted with CROSS JOIN UNNEST,
-- never with UNION ALL, so no CTE is re-executed.
--
-- QUINTILES from MID-RANKS (rank + (tie_count-1)/2), never `ntile`, which splits
-- ties arbitrarily.  Rows with a NULL variable are dropped from that variable's
-- ranking entirely (not ranked as a group), and `n` states how many remained.
--   n_hold_drop / n_exit / n_new / n_of20_left are NULL for a token with no
--   drawdown; wr_med / wr_p90 are NULL when no anchor wallet had a prior token.
--
-- AUC is exact: (sum of positive mid-ranks - n_pos(n_pos+1)/2) / (n_pos*n_neg),
-- computed on the same non-null rows.  Reported AS THE VARIABLE IS SIGNED, so
-- AUC < 0.5 means a LOWER value goes with a higher `x >= 60` rate.
WITH p AS (SELECT * FROM dune.quantbino1695.result_flow_pd),
s AS (SELECT * FROM dune.quantbino1695.result_flow_pdstab),
h AS (SELECT * FROM dune.quantbino1695.result_flow_pdhist),
b AS (
    SELECT p.token_mint, p.ld, p.win, p.min_x_win / p.x_a AS r,
           p.t_a_s,
           CAST(s.n_hold_drop AS double) AS n_hold_drop,
           CAST(s.n_of20_left AS double) AS n_of20_left,
           CAST(s.n_new AS double)       AS n_new,
           h.wr_med, h.wr_p90, h.n_wr20, h.share_exp
    FROM p LEFT JOIN s ON s.token_mint = p.token_mint
           LEFT JOIN h ON h.token_mint = p.token_mint
),
long AS (
    SELECT token_mint, ld, win, r, u.feat, u.val
    FROM b CROSS JOIN UNNEST(ARRAY[
        ROW('A1_t_anchor',   t_a_s),        ROW('A2_n_hold_drop', n_hold_drop),
        ROW('A3_n_of20_left', n_of20_left), ROW('A4_n_new',       n_new),
        ROW('B1_wr_med',     wr_med),       ROW('B2_wr_p90',      wr_p90),
        ROW('B3_n_wr20',     n_wr20),       ROW('B4_share_exp',   share_exp)
    ]) AS u(feat, val)
    WHERE u.val IS NOT NULL
),
rk AS (
    SELECT feat, win, r, val,
           CAST(rank() OVER (PARTITION BY feat ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY feat, val) AS double) - 1)/2.0 AS m,
           CAST(count(*) OVER (PARTITION BY feat) AS double) AS nf
    FROM long
),
g AS (
    SELECT rk.*, least(5, greatest(1, CAST(ceil(5.0 * m / nf) AS integer))) AS grp
    FROM rk
)
SELECT feat, grp, CAST(count(*) AS double) AS n,
       CAST(count_if(win) AS double)/count(*) AS s60,
       approx_percentile(val, 0.50) AS v50,
       approx_percentile(if(win, r), 0.10) AS w10,
       approx_percentile(if(win, r), 0.25) AS w25,
       approx_percentile(if(win, r), 0.50) AS w50,
       approx_percentile(if(NOT win, r), 0.25) AS l25,
       approx_percentile(if(NOT win, r), 0.50) AS l50,
       approx_percentile(if(NOT win, r), 0.75) AS l75,
       (sum(if(win, m, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double) * CAST(count_if(NOT win) AS double), 0) AS auc
FROM g GROUP BY GROUPING SETS ((feat), (feat, grp)) ORDER BY feat, grp
