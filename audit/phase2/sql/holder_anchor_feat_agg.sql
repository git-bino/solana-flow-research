-- 1г -- distribution features at each anchor, aggregated off the hfeat matviews.
WITH hf AS (
    SELECT * FROM dune.quantbino1695.result_flow_hfeat_a
    UNION ALL SELECT * FROM dune.quantbino1695.result_flow_hfeat_b
),
long AS (
    SELECT anchor_kind, f.name, f.val FROM hf
    CROSS JOIN UNNEST(ARRAY[
        ROW('n_holders', CAST(f_n_holders AS double)), ROW('gini', f_gini),
        ROW('top1', f_top1), ROW('top3', f_top3), ROW('creator_share', f_creator),
        ROW('n_trades', CAST(f_n_trades AS double)),
        ROW('n_buyers', CAST(f_n_buyers AS double))
    ]) AS f(name, val)
)
SELECT anchor_kind, name, CAST(count(*) AS double) AS n,
       approx_percentile(val, 0.25) AS p25,
       approx_percentile(val, 0.50) AS p50,
       approx_percentile(val, 0.75) AS p75,
       avg(val) AS mean
FROM long GROUP BY anchor_kind, name
ORDER BY anchor_kind, name
