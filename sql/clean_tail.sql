-- 3 -- the tail of max_x_after / x_a on the H3 anchor, clean against contaminated.
--
-- ONE GROUPING SETS pass, no UNION ALL: the previous query in this step
-- (sql/clean_baselines.sql) cost 3.805 cr against a 0.2 estimate because its
-- UNION ALL branch re-executed the CTE.  Same lesson as `cond` (60.697 cr).
--
-- PRICE percentiles are the square of the ratio percentiles: r -> r^2 is strictly
-- increasing on r > 0, so quantile(r^2) = quantile(r)^2 exactly.  Not an
-- approximation, and it saves six aggregate columns.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
hb AS (SELECT token_mint, x_a, t_a_s, max_x_after FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_gini FROM dune.quantbino1695.result_flow_hfeat_a
       WHERE anchor_kind = 'H3'),
j AS (
    SELECT hb.x_a, hb.t_a_s, hb.max_x_after / hb.x_a AS r, hf.f_gini,
           CASE WHEN cu.dev IS NULL THEN 'no_ev'
                WHEN cu.dev < 1e-6 THEN 'clean' ELSE 'dirty' END AS uni
    FROM hb JOIN hf ON hf.token_mint = hb.token_mint
            JOIN cu ON cu.token_mint = hb.token_mint
),
rk AS (
    SELECT j.*,
           CAST(rank() OVER (PARTITION BY uni ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY uni, f_gini) AS double) - 1)/2.0 AS mg,
           CAST(count(*) OVER (PARTITION BY uni) AS double) AS n_tot
    FROM j
),
c AS (
    SELECT uni, r, x_a,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           CASE WHEN t_a_s < 1 THEN '1_lt1s' WHEN t_a_s < 3 THEN '2_1to3s'
                WHEN t_a_s < 10 THEN '3_3to10s' ELSE '4_gt10s' END AS tb
    FROM rk
)
SELECT uni, g3, tb, CAST(count(*) AS double) AS n,
       approx_percentile(r, 0.50) AS p50, approx_percentile(r, 0.75) AS p75,
       approx_percentile(r, 0.90) AS p90, approx_percentile(r, 0.95) AS p95,
       approx_percentile(r, 0.99) AS p99, max(r) AS rmax,
       approx_percentile(x_a, 0.50) AS x_a_p50,
       CAST(count_if(r >= 1.76) AS double)/count(*) AS s176,
       CAST(count_if(r >= 2.35) AS double)/count(*) AS s235
FROM c
GROUP BY GROUPING SETS ((uni), (uni, g3), (uni, tb))
ORDER BY uni, g3, tb
