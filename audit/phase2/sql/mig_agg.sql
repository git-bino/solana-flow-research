-- 1 -- migration ceiling.  Reads result_flow_mig only.
WITH m AS (SELECT * FROM dune.quantbino1695.result_flow_mig)
SELECT
  CAST(count(*) AS double)                                   AS n_tokens,
  CAST(sum(n_ev) AS double)                                  AS n_events,
  CAST(sum(n_gt115) AS double)                               AS n_ev_gt115,
  CAST(count_if(ever_gt115) AS double)                       AS tok_gt115,
  CAST(count_if(has_complete) AS double)                     AS tok_complete,
  -- (b) trades AFTER completeevent
  CAST(count_if(has_complete AND n_after_c > 0) AS double)   AS tok_trade_after_c,
  CAST(sum(n_after_c) AS double)                             AS n_ev_after_c,
  approx_percentile(if(has_complete, CAST(n_after_c AS double)), 0.50) AS after_c_p50,
  approx_percentile(if(has_complete, CAST(n_after_c AS double)), 0.90) AS after_c_p90,
  -- (c) of the x>115 tokens, how many completed
  CAST(count_if(ever_gt115 AND has_complete) AS double)      AS gt115_and_complete,
  -- KEY: did the reserve exceed 115 BEFORE the curve closed?
  CAST(count_if(max_x_pre > 115) AS double)                  AS tok_pre_gt115,
  CAST(count_if(has_complete AND max_x_pre > 115) AS double) AS compl_pre_gt115,
  -- (d) reserve at completeevent
  approx_percentile(if(has_complete, x_at_complete), 0.10)   AS xc_p10,
  approx_percentile(if(has_complete, x_at_complete), 0.25)   AS xc_p25,
  approx_percentile(if(has_complete, x_at_complete), 0.50)   AS xc_p50,
  approx_percentile(if(has_complete, x_at_complete), 0.75)   AS xc_p75,
  approx_percentile(if(has_complete, x_at_complete), 0.90)   AS xc_p90,
  min(if(has_complete, x_at_complete))                       AS xc_min,
  max(if(has_complete, x_at_complete))                       AS xc_max,
  -- (e) max_x BEFORE completeevent vs overall
  approx_percentile(max_x_pre, 0.50) AS pre_p50, approx_percentile(max_x_pre, 0.90) AS pre_p90,
  approx_percentile(max_x_pre, 0.95) AS pre_p95, approx_percentile(max_x_pre, 0.99) AS pre_p99,
  max(max_x_pre) AS pre_max,
  approx_percentile(max_x_all, 0.50) AS all_p50, approx_percentile(max_x_all, 0.90) AS all_p90,
  approx_percentile(max_x_all, 0.95) AS all_p95, approx_percentile(max_x_all, 0.99) AS all_p99,
  max(max_x_all) AS all_max,
  -- (2a) the FLOOR
  approx_percentile(min_x_all, 0.01) AS min_p01, approx_percentile(min_x_all, 0.05) AS min_p05,
  approx_percentile(min_x_all, 0.10) AS min_p10, approx_percentile(min_x_all, 0.50) AS min_p50,
  min(min_x_all) AS min_min,
  CAST(count_if(min_x_all < 30) AS double) AS tok_below30,
  CAST(count_if(min_x_all < 29) AS double) AS tok_below29,
  CAST(count_if(min_x_all < 25) AS double) AS tok_below25
FROM m
