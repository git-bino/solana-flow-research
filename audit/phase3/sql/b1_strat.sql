-- 2 + 4 -- x_a held fixed against B1, and the price-independent combination.
--
-- Quintiles are GLOBAL mid-rank quintiles built once.  A feature's NULL rows get
-- a NULL quintile and are NEVER ranked (the repeated `rank()` defect), and every
-- output row carries `grouping(qx, qb, q2, q4)` so a "NULL because the column is
-- not in this grouping set" row can never be confused with a "NULL because the
-- feature is missing" row (the repeated GROUPING SETS defect).
--
-- Directions, read off sql/b1_tautology.sql and not chosen here: B1_wr_med and
-- B2_wr_p90 rise with the win rate (good end = q5); D4_n_trades falls (good end
-- = q1).
WITH p AS (SELECT token_mint, x_a, win, min_x_win FROM dune.quantbino1695.result_flow_pd),
b AS (
    SELECT p.*, h.wr_med, h.wr_p90, CAST(a.f_n_trades AS double) AS n_tr
    FROM p LEFT JOIN dune.quantbino1695.result_flow_pdhist h ON h.token_mint = p.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_wanch  a ON a.token_mint = p.token_mint
),
rx AS (
    SELECT b.*,
           CAST(rank() OVER (ORDER BY x_a) AS double)
             + (CAST(count(*) OVER (PARTITION BY x_a) AS double)-1)/2.0 AS mx,
           CAST(count(*) OVER () AS double) AS nx
    FROM b
),
rb AS (
    SELECT rx.*,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double)-1)/2.0 AS mb,
           CAST(count(*) OVER () AS double) AS nb
    FROM rx WHERE wr_med IS NOT NULL
),
r2 AS (
    SELECT rb.*,
           CAST(rank() OVER (ORDER BY wr_p90) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_p90) AS double)-1)/2.0 AS m2,
           CAST(count(*) OVER () AS double) AS n2
    FROM rb WHERE wr_p90 IS NOT NULL
),
r4 AS (
    SELECT r2.*,
           CAST(rank() OVER (ORDER BY n_tr) AS double)
             + (CAST(count(*) OVER (PARTITION BY n_tr) AS double)-1)/2.0 AS m4,
           CAST(count(*) OVER () AS double) AS n4
    FROM r2 WHERE n_tr IS NOT NULL
),
-- x_a quintile must be the GLOBAL one, so it is carried from rx through the
-- filters rather than recomputed on the surviving subset.
q AS (
    SELECT win, x_a, min_x_win,
           least(5,greatest(1,CAST(ceil(5.0*mx/nx) AS integer))) AS qx,
           least(5,greatest(1,CAST(ceil(5.0*mb/nb) AS integer))) AS qb,
           least(5,greatest(1,CAST(ceil(5.0*m2/n2) AS integer))) AS q2,
           least(5,greatest(1,CAST(ceil(5.0*m4/n4) AS integer))) AS q4
    FROM r4
)
SELECT qx, qb, q2, q4,
       CAST(grouping(qx, qb, q2, q4) AS integer)                AS gset,
       CAST(count(*) AS double)                                 AS n,
       CAST(count_if(win) AS double)/count(*)                    AS s60,
       approx_percentile(x_a, 0.50)                              AS xa50,
       approx_percentile(power(60.0 / x_a, 2) - 1.0, 0.50)        AS gain50,
       approx_percentile(if(NOT win, min_x_win / x_a), 0.50)      AS l50
FROM q
GROUP BY GROUPING SETS ((), (qx), (qb), (qx, qb), (qb, q2), (qb, q4), (qb, q2, q4))
ORDER BY qx, qb, q2, q4
