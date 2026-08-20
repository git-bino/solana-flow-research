-- 1a -- anchor coverage and the anchor-moment `x` distribution.
-- Reads the matview only; result is ~12 rows.
SELECT anchor_kind, n_target,
       CAST(count(*) AS double) AS n_tokens,
       CAST(count(*) AS double) / 262129.0 AS share_cohort,
       approx_percentile(x_a, 0.10) AS x_p10,
       approx_percentile(x_a, 0.25) AS x_p25,
       approx_percentile(x_a, 0.50) AS x_p50,
       approx_percentile(x_a, 0.75) AS x_p75,
       approx_percentile(x_a, 0.90) AS x_p90,
       approx_percentile(t_a_s, 0.50) AS t_p50,
       approx_percentile(t_a_s, 0.90) AS t_p90,
       approx_percentile(CAST(nh_a AS double), 0.50) AS nh_p50,
       CAST(count_if(x_a >= 60) AS double) / count(*) AS share_x_ge_60
FROM dune.quantbino1695.result_flow_holder_anchor
GROUP BY anchor_kind, n_target
ORDER BY n_target, anchor_kind
