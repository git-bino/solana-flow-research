-- 3 (aggregate) -- re-entry levels against entry at the anchor.
-- `t_launch_s` = seconds from LAUNCH to the trigger, so the two rows are on the
-- same clock as the anchor row.
WITH f AS (SELECT * FROM dune.quantbino1695.result_flow_reentry_fwd),
d AS (
    SELECT token_mint, x_a, t_a_s, max_x_after, seq_60, anchor_unix
    FROM dune.quantbino1695.result_flow_dd WHERE anchor_kind = 'H20'
),
tb AS (SELECT token_mint, to_unixtime(launch_time) AS lu
       FROM dune.quantbino1695.result_flow_token_base),
p AS (
    SELECT f.token_mint, tb.lu, u.lab, u.xe, u.ue, u.mn, u.mx, u.hit
    FROM f JOIN tb ON tb.token_mint = f.token_mint
    CROSS JOIN UNNEST(ARRAY[
        ROW('x<=32', x32, u32, mn32, mx32, h32),
        ROW('x<=35', x35, u35, mn35, mx35, h35),
        ROW('x<=38', x38, u38, mn38, mx38, h38)
    ]) AS u(lab, xe, ue, mn, mx, hit)
)
SELECT lab, CAST(count(*) AS double) AS n_all,
       CAST(count_if(xe IS NOT NULL) AS double) AS n,
       approx_percentile(ue - lu, 0.50) AS t_launch50,
       approx_percentile(xe, 0.50) AS xe50,
       CAST(count_if(hit > 0) AS double)/nullif(count_if(xe IS NOT NULL),0) AS s60,
       approx_percentile(mn / xe, 0.10) AS mn10,
       approx_percentile(mn / xe, 0.50) AS mn50,
       approx_percentile(mx / xe, 0.50) AS mx50,
       approx_percentile(mx / xe, 0.90) AS mx90,
       approx_percentile(mx / xe, 0.95) AS mx95
FROM p GROUP BY lab
UNION ALL
SELECT 'ANCHOR H20', CAST(count(*) AS double), CAST(count(*) AS double),
       approx_percentile(t_a_s, 0.50), approx_percentile(x_a, 0.50),
       CAST(count_if(seq_60 IS NOT NULL) AS double)/count(*),
       NULL, NULL,
       approx_percentile(max_x_after / x_a, 0.50),
       approx_percentile(max_x_after / x_a, 0.90),
       approx_percentile(max_x_after / x_a, 0.95)
FROM d
ORDER BY lab
