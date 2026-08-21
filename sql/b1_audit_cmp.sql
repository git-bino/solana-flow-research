-- 0(c) -- the WRONG and the CORRECT win-rate features side by side.
-- Every feature is ranked only after `WHERE val IS NOT NULL`; x_a is re-ranked
-- inside the same non-null subset; every row carries grouping().
WITH p AS (SELECT token_mint, x_a, win FROM dune.quantbino1695.result_flow_pd),
b AS (
    SELECT p.x_a, p.win,
           o.wr_med AS o_wr, o.wr_p90 AS o_p90, o.n_wr20 AS o_n20, o.share_exp AS o_se,
           c.wr_med AS c_wr, c.wr_p90 AS c_p90, c.n_wr20 AS c_n20, c.share_exp AS c_se
    FROM p LEFT JOIN dune.quantbino1695.result_flow_pdhist  o ON o.token_mint = p.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_pdhist2 c ON c.token_mint = p.token_mint
),
long AS (
    SELECT x_a, win, u.feat, u.val
    FROM b CROSS JOIN UNNEST(ARRAY[
        ROW('B1_wr_med  WRONG', o_wr),  ROW('B1_wr_med  FIXED', c_wr),
        ROW('B2_wr_p90  WRONG', o_p90), ROW('B2_wr_p90  FIXED', c_p90),
        ROW('B3_n_wr20  WRONG', o_n20), ROW('B3_n_wr20  FIXED', c_n20),
        ROW('B4_share   WRONG', o_se),  ROW('B4_share   FIXED', c_se)
    ]) AS u(feat, val)
    WHERE u.val IS NOT NULL
),
rk AS (
    SELECT feat, win, x_a, val,
           CAST(rank() OVER (PARTITION BY feat ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY feat, val) AS double)-1)/2.0 AS m,
           CAST(rank() OVER (PARTITION BY feat ORDER BY x_a) AS double)
             + (CAST(count(*) OVER (PARTITION BY feat, x_a) AS double)-1)/2.0 AS mx,
           CAST(count(*) OVER (PARTITION BY feat) AS double) AS nf
    FROM long
),
g AS (SELECT rk.*, least(5,greatest(1,CAST(ceil(5.0*m/nf) AS integer))) AS grp FROM rk)
SELECT feat, grp, CAST(grouping(feat, grp) AS integer) AS gset,
       CAST(count(*) AS double) AS n,
       CAST(count_if(win) AS double)/count(*) AS s60,
       corr(m, mx) AS spearman,
       approx_percentile(val, 0.50) AS v50,
       approx_percentile(x_a, 0.50) AS xa50,
       (sum(if(win, m, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double),0) AS auc
FROM g GROUP BY GROUPING SETS ((feat), (feat, grp)) ORDER BY feat, grp
