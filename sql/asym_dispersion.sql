-- 2b -- DISPERSION of the per-token return.  The means in sql/asym_passage.sql
-- are driven by a very long right tail (max_x/x_a reaches 152.5, i.e. a price
-- ratio of 23,256x), so reporting a mean alone would mislead.  Same source,
-- same single read, same GROUPING SETS discipline; only the output differs.
-- `top1_share_of_mean` is max(ret)/n: the number of percentage points of the
-- cell mean that the single largest row contributes by itself.
WITH hb AS (
    SELECT * FROM dune.quantbino1695.result_flow_hbar
),
hf AS (
    SELECT token_mint, f_gini, f_creator
    FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'
),
j AS (
    SELECT b.*, f.f_gini, f.f_creator
    FROM hb b JOIN hf f ON f.token_mint = b.token_mint
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
b AS (
    SELECT rk.*,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3,
           CASE WHEN t_a_s < 1 THEN '1_lt1s' WHEN t_a_s < 3 THEN '2_1to3s'
                WHEN t_a_s < 10 THEN '3_3to10s' ELSE '4_gt10s' END AS tb
    FROM rk
),
p AS (
    SELECT b.x_a, b.final_x, b.g3, b.c3, b.tb,
           u.lab, u.rt, u.slt, u.xt, u.tt, u.rs, u.sls, u.xs, u.ts
    FROM b CROSS JOIN UNNEST(ARRAY[

        ROW('+50% / −20%', 1.5, sl_u50, x_u50, t_u50, 0.8, sl_d20, x_d20, t_d20),
        ROW('+50% / −30%', 1.5, sl_u50, x_u50, t_u50, 0.7, sl_d30, x_d30, t_d30),
        ROW('+50% / −50%', 1.5, sl_u50, x_u50, t_u50, 0.5, sl_d50, x_d50, t_d50),
        ROW('+76% / −20%', 1.76, sl_u76, x_u76, t_u76, 0.8, sl_d20, x_d20, t_d20),
        ROW('+76% / −30%', 1.76, sl_u76, x_u76, t_u76, 0.7, sl_d30, x_d30, t_d30),
        ROW('+76% / −50%', 1.76, sl_u76, x_u76, t_u76, 0.5, sl_d50, x_d50, t_d50),
        ROW('+105% / −20%', 2.05, sl_u05, x_u05, t_u05, 0.8, sl_d20, x_d20, t_d20),
        ROW('+105% / −30%', 2.05, sl_u05, x_u05, t_u05, 0.7, sl_d30, x_d30, t_d30),
        ROW('+105% / −50%', 2.05, sl_u05, x_u05, t_u05, 0.5, sl_d50, x_d50, t_d50),
        ROW('+135% / −20%', 2.35, sl_u35, x_u35, t_u35, 0.8, sl_d20, x_d20, t_d20),
        ROW('+135% / −30%', 2.35, sl_u35, x_u35, t_u35, 0.7, sl_d30, x_d30, t_d30),
        ROW('+135% / −50%', 2.35, sl_u35, x_u35, t_u35, 0.5, sl_d50, x_d50, t_d50),
        ROW('зорилтгүй / −20%', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), 0.8, sl_d20, x_d20, t_d20),
        ROW('зорилтгүй / −30%', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), 0.7, sl_d30, x_d30, t_d30),
        ROW('зорилтгүй / −50%', CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), 0.5, sl_d50, x_d50, t_d50)
    ]) AS u(lab, rt, slt, xt, tt, rs, sls, xs, ts)
),
o AS (
    SELECT p.*,
           (slt IS NOT NULL AND (sls IS NULL OR slt < sls)) AS win,
           (sls IS NOT NULL AND (slt IS NULL OR sls < slt)) AS loss,
           (slt IS NOT NULL AND sls IS NOT NULL AND slt = sls) AS same,
           (slt IS NULL AND sls IS NULL) AS cens
    FROM p
),
v AS (
    SELECT o.*,
           CASE WHEN win THEN rt      WHEN loss THEN rs      ELSE final_x/x_a END AS r_thr,
           CASE WHEN win THEN xt/x_a  WHEN loss THEN xs/x_a  ELSE final_x/x_a END AS r_ovr
    FROM o
),
e AS (
    SELECT v.*,
           ((((32190000000.0 * 0.5 / (x_a * (x_a + 0.5))) * (r_thr * x_a + 0.5) * (r_thr * x_a + 0.5) / (32190000000.0 + (32190000000.0 * 0.5 / (x_a * (x_a + 0.5))) * (r_thr * x_a + 0.5))) * (1 - 0.0125) - 0.5 / (1 - 0.0125)) / 0.5) AS th05, ((((32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r_thr * x_a + 1.0) * (r_thr * x_a + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r_thr * x_a + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) AS th10,
           ((((32190000000.0 * 0.5 / (x_a * (x_a + 0.5))) * (r_ovr * x_a + 0.5) * (r_ovr * x_a + 0.5) / (32190000000.0 + (32190000000.0 * 0.5 / (x_a * (x_a + 0.5))) * (r_ovr * x_a + 0.5))) * (1 - 0.0125) - 0.5 / (1 - 0.0125)) / 0.5) AS ov05, ((((32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r_ovr * x_a + 1.0) * (r_ovr * x_a + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r_ovr * x_a + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) AS ov10
    FROM v
)
SELECT lab, g3, c3, tb, CAST(count(*) AS double) AS n,
       avg(ov10) AS mean_ov,
       approx_percentile(ov10, 0.10) AS q10, approx_percentile(ov10, 0.25) AS q25,
       approx_percentile(ov10, 0.50) AS q50, approx_percentile(ov10, 0.75) AS q75,
       approx_percentile(ov10, 0.90) AS q90, approx_percentile(ov10, 0.99) AS q99,
       max(ov10) AS omax,
       CAST(count_if(ov10 > 0) AS double)/count(*) AS pos,
       -- how much of the MEAN one single row can carry
       max(ov10) / count(*) AS top1_share_of_mean
FROM e
GROUP BY GROUPING SETS ((lab), (lab, tb, g3), (lab, tb, c3))
ORDER BY lab, tb, g3, c3
