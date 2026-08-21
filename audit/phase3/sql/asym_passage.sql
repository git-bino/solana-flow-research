-- 2 + 3 -- asymmetric first passage, threshold-valued AND overshoot-valued.
--
-- The 15 (target, stop) pairs are UNNESTed from a small literal array, so the
-- heavy source -- the hbar matview -- is read ONCE and the outcome logic is
-- written ONCE.  No `ntile`; tertiles from mid-ranks.  Every level of detail
-- comes from a single GROUPING SETS pass.
--
-- "no target" (`зорилтгүй`) has a NULL target slot, so `win` can never fire: the
-- row either stops out or is held to the end of the event window and valued on
-- its OBSERVED `final_x`.
--
-- CENSORED AND SAME-SLOT rows are valued on OBSERVED `final_x / x_a`, never on
-- the stop level.  Censoring is reported, never replaced.
--
-- TWO VALUATIONS per row, so §4 is visible rather than assumed away:
--   r_thr -- exit exactly at the barrier level (understates the win side)
--   r_ovr -- exit at the reserve ON the crossing event, which overshoots ABOVE
--            the level upward and BELOW it downward.  Both directions.
--
-- ECONOMICS: P = x^2/k (mayhem prevalence measured at 0/262,129), fee 1.25% PER
-- SIDE, and the exact path of `src/cost_model.py`'s `net_pnl` with V=0, pf=0,
-- `dy` written as k*q/(x1*(x1+q)) -- algebraically identical, no cancellation.
-- `src/asymmetric_barriers.py` re-checks that form against cost_model at
-- Decimal(60) and reports the measured maximum relative difference.
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
       CAST(count_if(win) AS double)  AS w, CAST(count_if(loss) AS double) AS l,
       CAST(count_if(same) AS double) AS s, CAST(count_if(cens) AS double) AS c,
       approx_percentile(if(win,  tt), 0.50) AS tw50,
       approx_percentile(if(win,  tt), 0.90) AS tw90,
       approx_percentile(if(loss, ts), 0.50) AS tl50,
       approx_percentile(if(loss, ts), 0.90) AS tl90,
       avg(th05) AS th05, avg(th10) AS th10,
       avg(ov05) AS ov05, avg(ov10) AS ov10,
       CAST(count_if(ov10 > 0) AS double)/count(*) AS pos10,
       approx_percentile(if(win, xt/x_a/rt), 0.50) AS ovr_win_p50,
       approx_percentile(if(loss, xs/x_a/rs), 0.50) AS ovr_loss_p50
FROM e
GROUP BY GROUPING SETS ((lab), (lab, g3), (lab, c3), (lab, tb), (lab, tb, g3), (lab, tb, c3))
ORDER BY lab, tb, g3, c3
