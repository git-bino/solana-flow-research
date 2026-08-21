-- 3 (aggregate) -- recovery by seller class.  One GROUPING SETS pass.
WITH r AS (SELECT * FROM dune.quantbino1695.result_flow_ddrec)
SELECT anchor_kind, cls, CAST(count(*) AS double) AS n,
       approx_percentile(min_x_after_drop / x_a, 0.10) AS mn10,
       approx_percentile(min_x_after_drop / x_a, 0.50) AS mn50,
       approx_percentile(min_x_after_drop / x_a, 0.90) AS mn90,
       approx_percentile(x_p10s / x_stop, 0.25) AS r10_25,
       approx_percentile(x_p10s / x_stop, 0.50) AS r10_50,
       approx_percentile(x_p10s / x_stop, 0.75) AS r10_75,
       approx_percentile(x_p30s / x_stop, 0.25) AS r30_25,
       approx_percentile(x_p30s / x_stop, 0.50) AS r30_50,
       approx_percentile(x_p30s / x_stop, 0.75) AS r30_75,
       approx_percentile(x_p60s / x_stop, 0.25) AS r60_25,
       approx_percentile(x_p60s / x_stop, 0.50) AS r60_50,
       approx_percentile(x_p60s / x_stop, 0.75) AS r60_75,
       CAST(count_if(t_back_to_xa IS NOT NULL) AS double)/count(*) AS s_back,
       approx_percentile(t_back_to_xa, 0.50) AS t_back50,
       CAST(count_if(t_to_60 IS NOT NULL) AS double)/count(*) AS s_60,
       approx_percentile(max_x_after_stop / x_stop, 0.50) AS mx50,
       approx_percentile(max_x_after_stop / x_stop, 0.95) AS mx95,
       approx_percentile(x_stop / x_a, 0.50) AS xs50
FROM r
GROUP BY GROUPING SETS ((anchor_kind), (anchor_kind, cls))
ORDER BY anchor_kind, cls
