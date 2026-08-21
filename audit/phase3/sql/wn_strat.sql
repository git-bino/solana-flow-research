-- 4 -- does anything survive holding B1_wr_med fixed?
--
-- The three strongest §2-§3 variables by |AUC - 0.5| are D1_sol_in (0.2303),
-- D3_t10_20 (0.0785) and D4_n_trades (0.0705); they are the ones stratified.
-- All quintiles are GLOBAL mid-rank quintiles computed once, then read inside
-- each B1 stratum, so a stratum with few tokens does not get its own cutpoints.
WITH p AS (SELECT token_mint, win FROM dune.quantbino1695.result_flow_pd),
b AS (
    SELECT p.token_mint, p.win, h.wr_med, a.sol_in, a.t10_20,
           CAST(a.f_n_trades AS double) AS n_tr
    FROM p LEFT JOIN dune.quantbino1695.result_flow_pdhist h ON h.token_mint = p.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_wanch a ON a.token_mint = p.token_mint
),
r AS (
    SELECT b.*,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double)-1)/2.0 AS mb,
           CAST(count(*) OVER (PARTITION BY (wr_med IS NULL)) AS double) AS nb,
           CAST(rank() OVER (ORDER BY sol_in) AS double)
             + (CAST(count(*) OVER (PARTITION BY sol_in) AS double)-1)/2.0 AS m1,
           CAST(count(*) OVER (PARTITION BY (sol_in IS NULL)) AS double) AS n1,
           CAST(rank() OVER (ORDER BY t10_20) AS double)
             + (CAST(count(*) OVER (PARTITION BY t10_20) AS double)-1)/2.0 AS m3,
           CAST(count(*) OVER (PARTITION BY (t10_20 IS NULL)) AS double) AS n3,
           CAST(rank() OVER (ORDER BY n_tr) AS double)
             + (CAST(count(*) OVER (PARTITION BY n_tr) AS double)-1)/2.0 AS m4,
           CAST(count(*) OVER (PARTITION BY (n_tr IS NULL)) AS double) AS n4
    FROM b
),
q AS (
    SELECT win,
           if(wr_med  IS NULL, NULL, least(5,greatest(1,CAST(ceil(5.0*mb/nb) AS integer)))) AS bq,
           if(sol_in  IS NULL, NULL, least(5,greatest(1,CAST(ceil(5.0*m1/n1) AS integer)))) AS q1,
           if(t10_20  IS NULL, NULL, least(5,greatest(1,CAST(ceil(5.0*m3/n3) AS integer)))) AS q3,
           if(n_tr    IS NULL, NULL, least(5,greatest(1,CAST(ceil(5.0*m4/n4) AS integer)))) AS q4
    FROM r
)
SELECT bq, q1, q3, q4, CAST(count(*) AS double) AS n,
       CAST(count_if(win) AS double)/count(*) AS s60
FROM q
GROUP BY GROUPING SETS ((), (bq), (bq,q1), (bq,q3), (bq,q4), (bq,q1,q3))
ORDER BY bq, q1, q3, q4
