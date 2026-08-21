-- 2 + 3 -- discrimination.  Same construction as sql/pd_discrim.sql: ONE source
-- scan, unpivot with CROSS JOIN UNNEST (never UNION ALL), quintiles from
-- MID-RANKS (never `ntile`), NULL rows dropped from that variable's ranking.
-- AUC exact: (sum of positive mid-ranks - n_pos(n_pos+1)/2)/(n_pos*n_neg),
-- reported AS THE VARIABLE IS SIGNED.
WITH p AS (SELECT token_mint, ld, win FROM dune.quantbino1695.result_flow_pd),
b AS (
    SELECT p.token_mint, p.ld, p.win,
           w.m_hold_s, w.m_still, w.m_esol, w.m_rk, w.m_ratio,
           a.sol_in, a.top1_nc, a.t10_20, CAST(a.f_n_trades AS double) AS n_tr
    FROM p LEFT JOIN dune.quantbino1695.result_flow_wbeh  w ON w.token_mint = p.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_wanch a ON a.token_mint = p.token_mint
),
long AS (
    SELECT ld, win, u.feat, u.val
    FROM b CROSS JOIN UNNEST(ARRAY[
        ROW('C1_hold_s',  m_hold_s), ROW('C2_still',   m_still),
        ROW('C3_esol',    m_esol),   ROW('C4_rk_buy',  m_rk),
        ROW('C5_ratio',   m_ratio),  ROW('D1_sol_in',  sol_in),
        ROW('D2_top1_nc', top1_nc),  ROW('D3_t10_20',  t10_20),
        ROW('D4_n_trades', n_tr)
    ]) AS u(feat, val)
    WHERE u.val IS NOT NULL
),
rk AS (
    SELECT feat, ld, win, val,
           CAST(rank() OVER (PARTITION BY feat ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY feat, val) AS double) - 1)/2.0 AS m,
           CAST(count(*) OVER (PARTITION BY feat) AS double) AS nf
    FROM long
),
g AS (SELECT rk.*, least(5, greatest(1, CAST(ceil(5.0*m/nf) AS integer))) AS grp FROM rk)
SELECT feat, grp, CAST(count(*) AS double) AS n,
       CAST(count_if(win) AS double)/count(*) AS s60,
       approx_percentile(val, 0.50) AS v50,
       approx_percentile(val, 0.10) AS v10,
       approx_percentile(val, 0.90) AS v90,
       (sum(if(win, m, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double), 0) AS auc
FROM g GROUP BY GROUPING SETS ((feat), (feat, grp)) ORDER BY feat, grp
