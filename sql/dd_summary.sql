-- 1 (aggregate) -- drawdown frequency and timing.  Reads result_flow_dd only.
WITH d AS (
    SELECT *, seq_drop IS NOT NULL AS dropped,
           seq_60 IS NOT NULL AS hit60,
           (seq_60 IS NOT NULL AND (seq_drop IS NULL OR seq_60 < seq_drop)) AS hit60_before_drop
    FROM dune.quantbino1695.result_flow_dd
)
SELECT anchor_kind, CAST(count(*) AS double) AS n,
       CAST(count_if(dropped) AS double)/count(*) AS s_drop,
       approx_percentile(if(dropped, t_drop_s), 0.10) AS td10,
       approx_percentile(if(dropped, t_drop_s), 0.50) AS td50,
       approx_percentile(if(dropped, t_drop_s), 0.90) AS td90,
       approx_percentile(if(dropped, t_drop_s), 0.99) AS td99,
       CAST(count_if(hit60) AS double)/count(*) AS s_60,
       CAST(count_if(hit60_before_drop) AS double)/count(*) AS s_60_before,
       CAST(count_if(dropped AND hit60 AND seq_60 > seq_drop) AS double)/count(*) AS s_60_after,
       approx_percentile(x_a, 0.50) AS xa50,
       approx_percentile(if(dropped, x_drop / x_a), 0.10) AS xd10,
       approx_percentile(if(dropped, x_drop / x_a), 0.50) AS xd50,
       approx_percentile(if(dropped, x_drop / x_a), 0.90) AS xd90,
       approx_percentile(max_x_after / x_a, 0.50) AS mr50,
       approx_percentile(max_x_after / x_a, 0.95) AS mr95
FROM d GROUP BY anchor_kind
