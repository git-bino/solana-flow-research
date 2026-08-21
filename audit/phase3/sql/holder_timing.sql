-- 4 -- the time picture: when the holder count first reaches 5 / 10 / 20,
-- what x was there, what happened after, and whether that moment precedes
-- x = 60.  Clean universe only.
--
-- H5 comes from result_flow_hpath_a, H10 and H20 from result_flow_hpath_b
-- (that is how those matviews were partitioned).  One GROUPING SETS pass.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
tb AS (
    SELECT token_mint,
           to_unixtime(t_60) - to_unixtime(launch_time) AS t60_s
    FROM dune.quantbino1695.result_flow_token_base
),
hp AS (
    SELECT token_mint, anchor_kind, x_a, t_a_s, max_x_after, sl_60
    FROM dune.quantbino1695.result_flow_hpath_a WHERE anchor_kind = 'H5'
),
hp2 AS (
    SELECT token_mint, anchor_kind, x_a, t_a_s, max_x_after, sl_60
    FROM dune.quantbino1695.result_flow_hpath_b WHERE anchor_kind IN ('H10','H20')
),
allp AS (SELECT * FROM hp UNION ALL SELECT * FROM hp2),
j AS (
    SELECT p.anchor_kind, p.x_a, p.t_a_s, p.max_x_after / p.x_a AS r,
           p.sl_60 IS NOT NULL AS reached60_after,
           p.x_a >= 60 AS already60,
           tb.t60_s,
           tb.t60_s IS NOT NULL AND p.t_a_s < tb.t60_s AS anchor_before_60
    FROM allp p JOIN coh c ON c.token_mint = p.token_mint
                LEFT JOIN tb ON tb.token_mint = p.token_mint
)
SELECT anchor_kind, CAST(count(*) AS double) AS n,
       approx_percentile(t_a_s, 0.50) AS t50, approx_percentile(t_a_s, 0.90) AS t90,
       approx_percentile(x_a, 0.25) AS x25, approx_percentile(x_a, 0.50) AS x50,
       approx_percentile(x_a, 0.75) AS x75,
       approx_percentile(r, 0.50) AS r50, approx_percentile(r, 0.90) AS r90,
       approx_percentile(r, 0.95) AS r95, max(r) AS rmax,
       CAST(count_if(already60) AS double)/count(*) AS s_already60,
       CAST(count_if(NOT already60 AND reached60_after) AS double)
         / nullif(count_if(NOT already60), 0) AS s_reach60,
       CAST(count_if(t60_s IS NOT NULL) AS double) AS n_with60,
       CAST(count_if(anchor_before_60) AS double)/nullif(count_if(t60_s IS NOT NULL),0) AS s_before60,
       approx_percentile(if(t60_s IS NOT NULL, t60_s - t_a_s), 0.50) AS gap50
FROM j GROUP BY anchor_kind
