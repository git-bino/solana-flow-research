-- 2b/2c/2d -- stop reachability and the no-stop variant.
--
-- §2a measured the floor: `x = 30` is NOT a hard floor -- 24.23% of tokens go
-- below it and min(x) reaches 1.011.  Reachability is therefore reported against
-- BOTH readings: the structural launch reserve 30, and the token's own observed
-- minimum (which is a backward-looking check on whether the level was in fact
-- touched, not a rule input).
--
-- No-stop variant: exit at the target if it was hit (at the OVERSHOOT reserve),
-- otherwise at the observed `final_x`.  Its loss bound is the p01/min of the
-- realised return, reported rather than assumed.
WITH hb AS (SELECT * FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_gini, f_creator
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
mg AS (SELECT token_mint, min_x_all FROM dune.quantbino1695.result_flow_mig),
j AS (
    SELECT b.*, f.f_gini, f.f_creator, m.min_x_all
    FROM hb b JOIN hf f ON f.token_mint = b.token_mint
              JOIN mg m ON m.token_mint = b.token_mint
),
p AS (
    SELECT j.x_a, j.final_x, j.min_x_all, j.t_a_s,
           CASE WHEN t_a_s < 1 THEN '1_lt1s' WHEN t_a_s < 3 THEN '2_1to3s'
                WHEN t_a_s < 10 THEN '3_3to10s' ELSE '4_gt10s' END AS tb,
           u.lab, u.rt, u.slt, u.xt, u.rs, u.sls, u.xs
    FROM j CROSS JOIN UNNEST(ARRAY[

        ROW('+76% / −50%', 1.76, sl_u76, x_u76, 0.5, sl_d50, x_d50),
        ROW('+135% / −50%', 2.35, sl_u35, x_u35, 0.5, sl_d50, x_d50),
        ROW('+76% / −20%', 1.76, sl_u76, x_u76, 0.8, sl_d20, x_d20),
        ROW('+76% / зогсоолгүй', 1.76, sl_u76, x_u76, CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double)),
        ROW('+135% / зогсоолгүй', 2.35, sl_u35, x_u35, CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double))
    ]) AS u(lab, rt, slt, xt, rs, sls, xs)
),
o AS (
    SELECT p.*,
           (slt IS NOT NULL AND (sls IS NULL OR slt < sls)) AS win,
           (sls IS NOT NULL AND (slt IS NULL OR sls < slt)) AS loss,
           (slt IS NULL AND sls IS NULL) AS cens,
           -- stop level above the structural launch reserve of 30
           (rs IS NOT NULL AND rs * x_a > 30.0) AS reach30
    FROM p
),
v AS (
    SELECT o.*, CASE WHEN win THEN xt/x_a WHEN loss THEN xs/x_a ELSE final_x/x_a END AS r
    FROM o
),
e AS (SELECT v.*, ((((32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r * x_a + 1.0) * (r * x_a + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r * x_a + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) AS ret FROM v)
SELECT lab, reach30, tb, CAST(count(*) AS double) AS n,
       CAST(count_if(win) AS double) AS w, CAST(count_if(loss) AS double) AS l,
       CAST(count_if(cens) AS double) AS c,
       avg(ret) AS mean_ret,
       approx_percentile(ret, 0.01) AS q01, approx_percentile(ret, 0.10) AS q10,
       approx_percentile(ret, 0.50) AS q50, approx_percentile(ret, 0.90) AS q90,
       min(ret) AS rmin, max(ret) AS rmax,
       CAST(count_if(ret > 0) AS double)/count(*) AS pos,
       approx_percentile(x_a, 0.50) AS x_a_p50,
       CAST(count_if(0.80 * x_a > 30.0) AS double)/count(*) AS s_r20_30,
       CAST(count_if(0.50 * x_a > 30.0) AS double)/count(*) AS s_r50_30,
       CAST(count_if(0.80 * x_a > min_x_all) AS double)/count(*) AS s_r20_obs,
       CAST(count_if(0.50 * x_a > min_x_all) AS double)/count(*) AS s_r50_obs
FROM e
GROUP BY GROUPING SETS ((lab), (lab, reach30), (lab, tb), (lab, tb, reach30))
ORDER BY lab, reach30, tb
