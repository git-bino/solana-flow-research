-- 1 -- the tail of `max_x / x_a`.  Reads the EXISTING hpath/hfeat matviews.
--
-- `max_x_after` is already the max reserve over events strictly after the
-- anchor, so no new scan is needed for this section.
--
-- PRICE percentiles are NOT computed separately: r -> r^2 is strictly
-- increasing on r > 0, so the q-th percentile of (max_x/x_a)^2 - 1 is exactly
-- (q-th percentile of max_x/x_a)^2 - 1.  Squaring the reported quantiles is an
-- identity here, not an approximation, and it saves six aggregate columns.
--
-- Tertiles from MID-RANKS, cut inside each anchor; no `ntile`.  One read of each
-- source, one GROUPING SETS pass.
WITH hp AS (
    SELECT token_mint, anchor_kind, x_a, t_a_s, max_x_after
    FROM dune.quantbino1695.result_flow_hpath_a WHERE anchor_kind = 'H3'
    UNION ALL
    SELECT token_mint, anchor_kind, x_a, t_a_s, max_x_after
    FROM dune.quantbino1695.result_flow_hpath_b WHERE anchor_kind IN ('H10','H20','X60')
),
hf AS (
    SELECT token_mint, anchor_kind, f_gini
    FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'
    UNION ALL
    SELECT token_mint, anchor_kind, f_gini
    FROM dune.quantbino1695.result_flow_hfeat_b WHERE anchor_kind IN ('H10','H20','X60')
),
j AS (
    SELECT p.anchor_kind, p.x_a, p.t_a_s, p.max_x_after / p.x_a AS r, f.f_gini
    FROM hp p JOIN hf f ON f.token_mint = p.token_mint
                       AND f.anchor_kind = p.anchor_kind
),
r AS (
    SELECT j.*,
           CAST(rank() OVER (PARTITION BY anchor_kind ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY anchor_kind, f_gini) AS double) - 1)/2.0 AS mg,
           CAST(count(*) OVER (PARTITION BY anchor_kind) AS double) AS n_tot
    FROM j
),
c AS (
    SELECT anchor_kind, x_a, r,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           CASE WHEN t_a_s < 1 THEN '1_lt1s' WHEN t_a_s < 3 THEN '2_1to3s'
                WHEN t_a_s < 10 THEN '3_3to10s' ELSE '4_gt10s' END AS tb
    FROM r
)
SELECT anchor_kind, g3, tb, CAST(count(*) AS double) AS n,
       approx_percentile(r, 0.50) AS p50, approx_percentile(r, 0.75) AS p75,
       approx_percentile(r, 0.90) AS p90, approx_percentile(r, 0.95) AS p95,
       approx_percentile(r, 0.99) AS p99, max(r) AS rmax,
       approx_percentile(x_a, 0.50) AS x_a_p50,
       CAST(count_if(r >= 1.50) AS double)/count(*) AS s150,
       CAST(count_if(r >= 1.76) AS double)/count(*) AS s176,
       CAST(count_if(r >= 2.05) AS double)/count(*) AS s205,
       CAST(count_if(r >= 2.35) AS double)/count(*) AS s235
FROM c
GROUP BY GROUPING SETS ((anchor_kind), (anchor_kind, g3), (anchor_kind, tb))
ORDER BY anchor_kind, g3, tb
