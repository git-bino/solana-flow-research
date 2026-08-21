-- 2 -- path after the anchor, aggregated off the hpath matviews.  ~60 rows out.
WITH hp AS (
    SELECT * FROM dune.quantbino1695.result_flow_hpath_a
    UNION ALL SELECT * FROM dune.quantbino1695.result_flow_hpath_b
)
SELECT anchor_kind, 'max_x_after_ratio' AS metric, CAST(count(*) AS double) AS n,
       approx_percentile(max_x_after / x_a, 0.10) AS p10,
       approx_percentile(max_x_after / x_a, 0.25) AS p25,
       approx_percentile(max_x_after / x_a, 0.50) AS p50,
       approx_percentile(max_x_after / x_a, 0.75) AS p75,
       approx_percentile(max_x_after / x_a, 0.90) AS p90,
       CAST(NULL AS double) AS share
FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'min_x_after_ratio', CAST(count(*) AS double),
       approx_percentile(min_x_after / x_a, 0.10), approx_percentile(min_x_after / x_a, 0.25),
       approx_percentile(min_x_after / x_a, 0.50), approx_percentile(min_x_after / x_a, 0.75),
       approx_percentile(min_x_after / x_a, 0.90), NULL FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'final_x_ratio', CAST(count(*) AS double),
       approx_percentile(final_x / x_a, 0.10), approx_percentile(final_x / x_a, 0.25),
       approx_percentile(final_x / x_a, 0.50), approx_percentile(final_x / x_a, 0.75),
       approx_percentile(final_x / x_a, 0.90), NULL FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 't_max_after_s', CAST(count(*) AS double),
       approx_percentile(t_max_after_s, 0.10), approx_percentile(t_max_after_s, 0.25),
       approx_percentile(t_max_after_s, 0.50), approx_percentile(t_max_after_s, 0.75),
       approx_percentile(t_max_after_s, 0.90), NULL FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 't_final_s', CAST(count(*) AS double),
       approx_percentile(t_final_s, 0.10), approx_percentile(t_final_s, 0.25),
       approx_percentile(t_final_s, 0.50), approx_percentile(t_final_s, 0.75),
       approx_percentile(t_final_s, 0.90), NULL FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'n_after', CAST(count(*) AS double),
       approx_percentile(CAST(n_after AS double), 0.10), approx_percentile(CAST(n_after AS double), 0.25),
       approx_percentile(CAST(n_after AS double), 0.50), approx_percentile(CAST(n_after AS double), 0.75),
       approx_percentile(CAST(n_after AS double), 0.90), NULL FROM hp GROUP BY anchor_kind
-- reach / fall shares with their times
UNION ALL SELECT anchor_kind, 'up_20', CAST(count_if(sl_g20 IS NOT NULL) AS double),
       approx_percentile(t_g20_s,0.10), approx_percentile(t_g20_s,0.25), approx_percentile(t_g20_s,0.50),
       approx_percentile(t_g20_s,0.75), approx_percentile(t_g20_s,0.90),
       CAST(count_if(sl_g20 IS NOT NULL) AS double)/count(*) FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'up_36', CAST(count_if(sl_g36 IS NOT NULL) AS double),
       approx_percentile(t_g36_s,0.10), approx_percentile(t_g36_s,0.25), approx_percentile(t_g36_s,0.50),
       approx_percentile(t_g36_s,0.75), approx_percentile(t_g36_s,0.90),
       CAST(count_if(sl_g36 IS NOT NULL) AS double)/count(*) FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'up_100', CAST(count_if(sl_g100 IS NOT NULL) AS double),
       approx_percentile(t_g100_s,0.10), approx_percentile(t_g100_s,0.25), approx_percentile(t_g100_s,0.50),
       approx_percentile(t_g100_s,0.75), approx_percentile(t_g100_s,0.90),
       CAST(count_if(sl_g100 IS NOT NULL) AS double)/count(*) FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'down_20', CAST(count_if(sl_l20 IS NOT NULL) AS double),
       approx_percentile(t_l20_s,0.10), approx_percentile(t_l20_s,0.25), approx_percentile(t_l20_s,0.50),
       approx_percentile(t_l20_s,0.75), approx_percentile(t_l20_s,0.90),
       CAST(count_if(sl_l20 IS NOT NULL) AS double)/count(*) FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'down_30', CAST(count_if(sl_l30 IS NOT NULL) AS double),
       approx_percentile(t_l30_s,0.10), approx_percentile(t_l30_s,0.25), approx_percentile(t_l30_s,0.50),
       approx_percentile(t_l30_s,0.75), approx_percentile(t_l30_s,0.90),
       CAST(count_if(sl_l30 IS NOT NULL) AS double)/count(*) FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'down_50', CAST(count_if(sl_l50 IS NOT NULL) AS double),
       approx_percentile(t_l50_s,0.10), approx_percentile(t_l50_s,0.25), approx_percentile(t_l50_s,0.50),
       approx_percentile(t_l50_s,0.75), approx_percentile(t_l50_s,0.90),
       CAST(count_if(sl_l50 IS NOT NULL) AS double)/count(*) FROM hp GROUP BY anchor_kind
-- 60 / 115, split by whether the anchor was ALREADY across
UNION ALL SELECT anchor_kind, 'reach_60_notyet', CAST(count_if(x_a < 60) AS double),
       approx_percentile(t_60_s,0.10), approx_percentile(t_60_s,0.25), approx_percentile(t_60_s,0.50),
       approx_percentile(t_60_s,0.75), approx_percentile(t_60_s,0.90),
       CAST(count_if(x_a < 60 AND sl_60 IS NOT NULL) AS double)/nullif(count_if(x_a < 60),0)
FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'already_60', CAST(count_if(x_a >= 60) AS double),
       NULL, NULL, NULL, NULL, NULL,
       CAST(count_if(x_a >= 60) AS double)/count(*) FROM hp GROUP BY anchor_kind
UNION ALL SELECT anchor_kind, 'reach_115_notyet', CAST(count_if(x_a < 115) AS double),
       approx_percentile(t_115_s,0.10), approx_percentile(t_115_s,0.25), approx_percentile(t_115_s,0.50),
       approx_percentile(t_115_s,0.75), approx_percentile(t_115_s,0.90),
       CAST(count_if(x_a < 115 AND sl_115 IS NOT NULL) AS double)/nullif(count_if(x_a < 115),0)
FROM hp GROUP BY anchor_kind
ORDER BY anchor_kind, metric
