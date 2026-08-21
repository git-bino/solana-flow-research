-- 3 -- cluster CI inputs, trimming, and the x <= 115 truncation.
--
-- CLUSTER STRUCTURE, written out: the row is a TOKEN and every token has exactly
-- ONE launch day, so token is NESTED inside launch-day and the two-way
-- pigeonhole construction does not apply -- this is a ONE-WAY launch-day cluster
-- bootstrap, B = 1,000, on **9 clusters**.  Nine is thin; the interval width
-- below is set by those nine numbers, not by the ~39,000 tokens.  The bootstrap
-- itself runs locally at 0 credit from the per-day (n, sum) pairs this query
-- returns.
--
-- TRIMMING uses `percent_rank()` inside each (cell, pair), so the top 1/5/10%
-- removed is per reported cell, not global.
--
-- TRUNCATION AT 115: §1 measured that no trade occurs after either migration
-- marker and that max_x_pre == max_x_all, i.e. the >115 reserves ARE on the
-- curve -- so this cap is a SENSITIVITY, not a correction.  It caps the exit
-- reserve at 115 SOL and leaves everything else identical.
WITH hb AS (SELECT * FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_gini, f_creator
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
tb AS (SELECT token_mint, date(launch_time) AS ld
       FROM dune.quantbino1695.result_flow_token_base),
j AS (SELECT b.*, f.f_gini, f.f_creator, t.ld
      FROM hb b JOIN hf f ON f.token_mint = b.token_mint
                JOIN tb t ON t.token_mint = b.token_mint),
rk AS (
    SELECT j.*,
           CAST(rank() OVER (ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_gini) AS double) - 1)/2.0 AS mg,
           CAST(rank() OVER (ORDER BY f_creator) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_creator) AS double) - 1)/2.0 AS mc,
           CAST(count(*) OVER () AS double) AS n_tot
    FROM j
),
b2 AS (
    SELECT rk.*,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3,
           CASE WHEN t_a_s < 3 THEN 'x' WHEN t_a_s < 10 THEN '3_3to10s'
                ELSE '4_gt10s' END AS tbk
    FROM rk
),
cellrows AS (
    SELECT b2.*, cc.cell FROM b2 CROSS JOIN UNNEST(ARRAY[
        ROW('gini g1', g3), ROW('creator c1', c3)]) AS cc(cell, tv)
    WHERE cc.tv = 1 AND b2.tbk <> 'x'
),
p AS (
    SELECT c.cell, c.tbk, c.ld, c.x_a, c.final_x,
           u.lab, u.rt, u.slt, u.xt, u.rs, u.sls, u.xs
    FROM cellrows c CROSS JOIN UNNEST(ARRAY[

        ROW('+76% / −50%', 1.76, sl_u76, x_u76, 0.5, sl_d50, x_d50),
        ROW('+135% / −50%', 2.35, sl_u35, x_u35, 0.5, sl_d50, x_d50),
        ROW('+76% / −20%', 1.76, sl_u76, x_u76, 0.8, sl_d20, x_d20),
        ROW('+135% / −20%', 2.35, sl_u35, x_u35, 0.8, sl_d20, x_d20),
        ROW('+76% / зогсоолгүй', 1.76, sl_u76, x_u76, CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double)),
        ROW('+135% / зогсоолгүй', 2.35, sl_u35, x_u35, CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double))
    ]) AS u(lab, rt, slt, xt, rs, sls, xs)
),
v AS (
    SELECT p.*,
           CASE WHEN slt IS NOT NULL AND (sls IS NULL OR slt < sls) THEN xt/x_a
                WHEN sls IS NOT NULL AND (slt IS NULL OR sls < slt) THEN xs/x_a
                ELSE final_x/x_a END AS r
    FROM p
),
e AS (
    SELECT v.*, ((((32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r * x_a + 1.0) * (r * x_a + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r * x_a + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) AS ret,
           ((((32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (least(r, 115.0 / x_a) * x_a + 1.0) * (least(r, 115.0 / x_a) * x_a + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (least(r, 115.0 / x_a) * x_a + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) AS ret_cap
    FROM v
),
w AS (
    SELECT e.*, percent_rank() OVER (PARTITION BY cell, tbk, lab ORDER BY ret) AS pr
    FROM e
)
SELECT cell, tbk, lab, CAST(ld AS varchar) AS ld,
       CAST(count(*) AS double) AS n,
       sum(ret) AS s_ret, avg(ret) AS mean_ret,
       avg(if(pr < 0.99, ret)) AS trim01,
       avg(if(pr < 0.95, ret)) AS trim05,
       avg(if(pr < 0.90, ret)) AS trim10,
       avg(ret_cap) AS mean_cap
FROM w
GROUP BY GROUPING SETS ((cell, tbk, lab), (cell, tbk, lab, ld))
ORDER BY cell, tbk, lab, ld
