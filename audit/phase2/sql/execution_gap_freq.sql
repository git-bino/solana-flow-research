-- 3 -- frequency and concurrency over the UNION of the four executable cells.
--
-- A token can sit in both `gini g1` and `creator c1`, so the union is taken as
-- DISTINCT tokens -- it is one position per token, not two.
--
-- Position clock: entry at the anchor (delay 0), exit at the +76% crossing when
-- it happened and at the last observed trade otherwise (the no-stop variant).
-- Concurrency is a sweep line: +1 at entry, -1 at exit, running sum over time.
WITH gi AS (SELECT token_mint, t_a_s, t_final_s FROM dune.quantbino1695.result_flow_gapin),
hb AS (SELECT token_mint, t_u76 FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_gini, f_creator
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
tb AS (SELECT token_mint, launch_time FROM dune.quantbino1695.result_flow_token_base),
j AS (
    SELECT gi.token_mint, gi.t_a_s, gi.t_final_s, hb.t_u76,
           hf.f_gini, hf.f_creator, tb.launch_time
    FROM gi JOIN hf ON hf.token_mint = gi.token_mint
            JOIN hb ON hb.token_mint = gi.token_mint
            JOIN tb ON tb.token_mint = gi.token_mint
),
rk AS (
    SELECT j.*,
           CAST(rank() OVER (ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_gini) AS double) - 1)/2.0 AS mg,
           CAST(rank() OVER (ORDER BY f_creator) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_creator) AS double) - 1)/2.0 AS mc,
           CAST(count(*) OVER () AS double) AS n_tot
    FROM j
),
sel AS (
    SELECT token_mint, launch_time, t_a_s, coalesce(t_u76, t_final_s) AS hold_s,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3,
           CASE WHEN t_a_s < 3 THEN 'x' WHEN t_a_s < 10 THEN '3_3to10s'
                ELSE '4_gt10s' END AS tbk
    FROM rk
),
pos AS (
    SELECT DISTINCT token_mint, launch_time,
           to_unixtime(launch_time) + t_a_s              AS t_in,
           to_unixtime(launch_time) + t_a_s + hold_s     AS t_out
    FROM sel
    WHERE tbk <> 'x' AND (g3 = 1 OR c3 = 1)
),
ticks AS (
    SELECT t_in AS t,  1 AS d FROM pos
    UNION ALL
    SELECT t_out, -1 FROM pos
),
conc AS (
    SELECT t, sum(d) OVER (ORDER BY t ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS open_n
    FROM ticks
),
per_day AS (
    SELECT date(launch_time) AS ld, count(*) AS n FROM pos GROUP BY date(launch_time)
),
per_hour AS (
    SELECT date_trunc('hour', launch_time) AS lh, count(*) AS n
    FROM pos GROUP BY date_trunc('hour', launch_time)
)
SELECT 'positions' AS k, CAST(count(*) AS double) AS a, NULL AS b, NULL AS c,
       NULL AS d, NULL AS e FROM pos
UNION ALL
SELECT 'hold_seconds', approx_percentile(t_out - t_in, 0.10),
       approx_percentile(t_out - t_in, 0.50), approx_percentile(t_out - t_in, 0.90),
       max(t_out - t_in), avg(t_out - t_in) FROM pos
UNION ALL
SELECT 'per_launch_day', CAST(count(*) AS double), approx_percentile(CAST(n AS double), 0.10),
       approx_percentile(CAST(n AS double), 0.50), approx_percentile(CAST(n AS double), 0.90),
       CAST(max(n) AS double) FROM per_day
UNION ALL
SELECT 'per_hour', CAST(count(*) AS double), approx_percentile(CAST(n AS double), 0.50),
       approx_percentile(CAST(n AS double), 0.90), CAST(max(n) AS double),
       avg(CAST(n AS double)) FROM per_hour
UNION ALL
SELECT 'concurrent', approx_percentile(CAST(open_n AS double), 0.50),
       approx_percentile(CAST(open_n AS double), 0.90),
       approx_percentile(CAST(open_n AS double), 0.99),
       CAST(max(open_n) AS double), NULL FROM conc
