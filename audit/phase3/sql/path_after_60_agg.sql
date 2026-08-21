-- A.3 -- aggregates read back from dune.quantbino1695.result_flow_path.
--
-- Long format, ~40 rows out, so retrieval is negligible.  The token-level rows
-- stay on Dune: the measured export price is 312.4 B/row x 41,008 = 12.81 MB =
-- 150.51 credits, against a 60-credit task budget.
--
-- CENSORING.  `dur_above_s` is NULL when `x` never fell back below the level
-- inside the event window.  Two readings are reported and neither is a model:
--   * `dur_above_observed` -- percentiles over the rows that DID fall back.
--     Conditional on falling back; biased DOWN as a statement about all tokens.
--   * `dur_above_lowerbound` -- censored rows enter at `dur_to_window_end_s`,
--     which is a known lower bound on their true duration.  Every percentile of
--     this series is therefore a LOWER BOUND on the true percentile.
-- No Kaplan-Meier, no imputation.

WITH p AS (SELECT * FROM dune.quantbino1695.result_flow_path)

SELECT lvl, 't_anchor_s' AS metric, CAST(count(*) AS double) AS n,
       approx_percentile(t_anchor_s, 0.10) AS p10,
       approx_percentile(t_anchor_s, 0.25) AS p25,
       approx_percentile(t_anchor_s, 0.50) AS p50,
       approx_percentile(t_anchor_s, 0.75) AS p75,
       approx_percentile(t_anchor_s, 0.90) AS p90,
       CAST(NULL AS double) AS share
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'dur_above_observed', CAST(count_if(dur_above_s IS NOT NULL) AS double),
       approx_percentile(dur_above_s, 0.10), approx_percentile(dur_above_s, 0.25),
       approx_percentile(dur_above_s, 0.50), approx_percentile(dur_above_s, 0.75),
       approx_percentile(dur_above_s, 0.90),
       CAST(count_if(dur_above_s IS NULL) AS double) / count(*)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'dur_above_lowerbound', CAST(count(*) AS double),
       approx_percentile(coalesce(dur_above_s, dur_to_window_end_s), 0.10),
       approx_percentile(coalesce(dur_above_s, dur_to_window_end_s), 0.25),
       approx_percentile(coalesce(dur_above_s, dur_to_window_end_s), 0.50),
       approx_percentile(coalesce(dur_above_s, dur_to_window_end_s), 0.75),
       approx_percentile(coalesce(dur_above_s, dur_to_window_end_s), 0.90),
       CAST(count_if(dur_above_s IS NULL) AS double) / count(*)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'min_x_after_ratio', CAST(count(*) AS double),
       approx_percentile(min_x_after / lvl, 0.10),
       approx_percentile(min_x_after / lvl, 0.25),
       approx_percentile(min_x_after / lvl, 0.50),
       approx_percentile(min_x_after / lvl, 0.75),
       approx_percentile(min_x_after / lvl, 0.90),
       CAST(count_if(min_x_after >= lvl) AS double) / count(*)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 't_max_x_s', CAST(count(*) AS double),
       approx_percentile(t_max_x_s, 0.10), approx_percentile(t_max_x_s, 0.25),
       approx_percentile(t_max_x_s, 0.50), approx_percentile(t_max_x_s, 0.75),
       approx_percentile(t_max_x_s, 0.90),
       CAST(count_if(t_max_x_s <= 1) AS double) / count(*)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'final_x_ratio', CAST(count(*) AS double),
       approx_percentile(final_x / lvl, 0.10), approx_percentile(final_x / lvl, 0.25),
       approx_percentile(final_x / lvl, 0.50), approx_percentile(final_x / lvl, 0.75),
       approx_percentile(final_x / lvl, 0.90),
       CAST(count_if(final_x >= lvl) AS double) / count(*)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'max_x_ratio', CAST(count(*) AS double),
       approx_percentile(max_x / lvl, 0.10), approx_percentile(max_x / lvl, 0.25),
       approx_percentile(max_x / lvl, 0.50), approx_percentile(max_x / lvl, 0.75),
       approx_percentile(max_x / lvl, 0.90), CAST(NULL AS double)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 't_final_s', CAST(count(*) AS double),
       approx_percentile(t_final_s, 0.10), approx_percentile(t_final_s, 0.25),
       approx_percentile(t_final_s, 0.50), approx_percentile(t_final_s, 0.75),
       approx_percentile(t_final_s, 0.90), CAST(NULL AS double)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'n_trades_after', CAST(count(*) AS double),
       approx_percentile(n_trades_after, 0.10), approx_percentile(n_trades_after, 0.25),
       approx_percentile(n_trades_after, 0.50), approx_percentile(n_trades_after, 0.75),
       approx_percentile(n_trades_after, 0.90), CAST(NULL AS double)
FROM p GROUP BY lvl

-- threshold crossings after the anchor: share reached, and when
UNION ALL
SELECT lvl, 'reach_70', CAST(count_if(t_70_s IS NOT NULL) AS double),
       approx_percentile(t_70_s, 0.10), approx_percentile(t_70_s, 0.25),
       approx_percentile(t_70_s, 0.50), approx_percentile(t_70_s, 0.75),
       approx_percentile(t_70_s, 0.90),
       CAST(count_if(t_70_s IS NOT NULL) AS double) / count(*)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'reach_80', CAST(count_if(t_80_s IS NOT NULL) AS double),
       approx_percentile(t_80_s, 0.10), approx_percentile(t_80_s, 0.25),
       approx_percentile(t_80_s, 0.50), approx_percentile(t_80_s, 0.75),
       approx_percentile(t_80_s, 0.90),
       CAST(count_if(t_80_s IS NOT NULL) AS double) / count(*)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'reach_100', CAST(count_if(t_100_s IS NOT NULL) AS double),
       approx_percentile(t_100_s, 0.10), approx_percentile(t_100_s, 0.25),
       approx_percentile(t_100_s, 0.50), approx_percentile(t_100_s, 0.75),
       approx_percentile(t_100_s, 0.90),
       CAST(count_if(t_100_s IS NOT NULL) AS double) / count(*)
FROM p GROUP BY lvl

UNION ALL
SELECT lvl, 'reach_115', CAST(count_if(t_115_s IS NOT NULL) AS double),
       approx_percentile(t_115_s, 0.10), approx_percentile(t_115_s, 0.25),
       approx_percentile(t_115_s, 0.50), approx_percentile(t_115_s, 0.75),
       approx_percentile(t_115_s, 0.90),
       CAST(count_if(t_115_s IS NOT NULL) AS double) / count(*)
FROM p GROUP BY lvl

ORDER BY lvl, metric
