-- 1 + 2 -- H3 economics on the CORRECTED price arithmetic.
--
-- FIX (research lead, 2026-08-21).  The earlier `win*(+0.20) + loss*(-0.20)`
-- was wrong twice over:
--   (a) `x` is the SOL RESERVE, not the price.  With x*y = k constant the price
--       is P = x^2/k, so a +20% move in x is +44% in price (1.20^2 - 1) and a
--       -20% move is -36% (0.80^2 - 1).  For the +36/-30 pair: +85% and -51%.
--       Censored and same-slot rows are valued on their OBSERVED final_x/x_a,
--       not on a threshold.
--   (b) The fee is 1.25% PER SIDE and multiplicative, not 2.5% subtracted once.
--
-- PRECONDITION MEASURED, NOT ASSUMED: `P ∝ x^2` needs x*y = k, which a mayhem
-- virtual-param rewrite would break.  Counted first (sql/h3_mayhem_probe.sql):
-- 0 of 262,129 cohort tokens appear in pump_evt_updatemayhemvirtualparamsevent
-- over the event window, so k = 30 * 1,073,000,000 = 3.219e10 holds throughout.
--
-- SLIPPAGE IS THE EXACT PATH of src/cost_model.py's `net_pnl`, not an
-- approximation.  With V = 0 and pf = 0 that function is
--     dy   = k/x1 - k/(x1+q)
--     x2   = x1 + q + W
--     out  = dy*x2^2 / (k + dy*x2)
--     pnl  = out*(1-f) - q/(1-f)
-- and here x1 = x_a, W = (r - 1)*x_a so x2 = r*x_a + q.  `dy` is written below
-- as k*q/(x1*(x1+q)), which is algebraically the SAME expression with the
-- cancelling difference removed -- that is why cost_model needs Decimal(60) and
-- this does not.  src/h3_economics.py checks this form against
-- `cost_model.net_pnl` at Decimal(60) over the real (x_a, r, q) ranges and
-- reports the measured maximum relative difference.
--
-- COST SHAPE: one read of each matview, no `ntile` (tertiles from mid-ranks),
-- every level of detail from a single GROUPING SETS pass.
WITH hp AS (
    SELECT token_mint, x_a, t_a_s, final_x, sl_g20, sl_g36, sl_l20, sl_l30
    FROM dune.quantbino1695.result_flow_hpath_a WHERE anchor_kind = 'H3'
),
hf AS (
    SELECT token_mint, f_gini, f_creator
    FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'
),
j AS (
    SELECT p.x_a, p.t_a_s, p.final_x, p.sl_g20, p.sl_g36, p.sl_l20, p.sl_l30,
           f.f_gini, f.f_creator
    FROM hp p JOIN hf f ON f.token_mint = p.token_mint
),
r AS (
    SELECT j.*,
           CAST(rank() OVER (ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_gini) AS double) - 1)/2.0 AS mg,
           CAST(rank() OVER (ORDER BY f_creator) AS double)
             + (CAST(count(*) OVER (PARTITION BY f_creator) AS double) - 1)/2.0 AS mc,
           CAST(count(*) OVER () AS double) AS n_tot
    FROM j
),
c AS (
    SELECT x_a, t_a_s,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3,
           CASE WHEN t_a_s < 1 THEN '1_lt1s' WHEN t_a_s < 3 THEN '2_1to3s'
                WHEN t_a_s < 10 THEN '3_3to10s' ELSE '4_gt10s' END AS tb,
           (sl_g20 IS NOT NULL AND (sl_l20 IS NULL OR sl_g20 < sl_l20)) AS w20,
           (sl_l20 IS NOT NULL AND (sl_g20 IS NULL OR sl_l20 < sl_g20)) AS l20,
           (sl_g20 IS NOT NULL AND sl_l20 IS NOT NULL AND sl_g20 = sl_l20) AS s20,
           (sl_g20 IS NULL AND sl_l20 IS NULL) AS x20,
           (sl_g36 IS NOT NULL AND (sl_l30 IS NULL OR sl_g36 < sl_l30)) AS w36,
           (sl_l30 IS NOT NULL AND (sl_g36 IS NULL OR sl_l30 < sl_g36)) AS l36,
           (sl_g36 IS NOT NULL AND sl_l30 IS NOT NULL AND sl_g36 = sl_l30) AS s36,
           (sl_g36 IS NULL AND sl_l30 IS NULL) AS x36,
           final_x / x_a AS fr
    FROM r
),
-- exit reserve ratio: threshold when the pair resolved, OBSERVED otherwise
z AS (
    SELECT c.*,
           CASE WHEN w20 THEN 1.20 WHEN l20 THEN 0.80 ELSE fr END AS r20,
           CASE WHEN w36 THEN 1.36 WHEN l36 THEN 0.70 ELSE fr END AS r36
    FROM c
),
e AS (
    SELECT z.*,
           r20*r20 - 1                          AS raw20,
           r36*r36 - 1                          AS raw36,
           r20*r20*(1-0.0125)*(1-0.0125) - 1          AS fee20,
           r36*r36*(1-0.0125)*(1-0.0125) - 1          AS fee36,
           ((((32190000000.0 * 0.5 / (x_a * (x_a + 0.5))) * (r20 * x_a + 0.5) * (r20 * x_a + 0.5) / (32190000000.0 + (32190000000.0 * 0.5 / (x_a * (x_a + 0.5))) * (r20 * x_a + 0.5))) * (1 - 0.0125) - 0.5 / (1 - 0.0125)) / 0.5) AS s20_05,
           ((((32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r20 * x_a + 1.0) * (r20 * x_a + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r20 * x_a + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) AS s20_10,
           ((((32190000000.0 * 2.0 / (x_a * (x_a + 2.0))) * (r20 * x_a + 2.0) * (r20 * x_a + 2.0) / (32190000000.0 + (32190000000.0 * 2.0 / (x_a * (x_a + 2.0))) * (r20 * x_a + 2.0))) * (1 - 0.0125) - 2.0 / (1 - 0.0125)) / 2.0) AS s20_20,
           ((((32190000000.0 * 0.5 / (x_a * (x_a + 0.5))) * (r36 * x_a + 0.5) * (r36 * x_a + 0.5) / (32190000000.0 + (32190000000.0 * 0.5 / (x_a * (x_a + 0.5))) * (r36 * x_a + 0.5))) * (1 - 0.0125) - 0.5 / (1 - 0.0125)) / 0.5) AS s36_05,
           ((((32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r36 * x_a + 1.0) * (r36 * x_a + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_a * (x_a + 1.0))) * (r36 * x_a + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) AS s36_10,
           ((((32190000000.0 * 2.0 / (x_a * (x_a + 2.0))) * (r36 * x_a + 2.0) * (r36 * x_a + 2.0) / (32190000000.0 + (32190000000.0 * 2.0 / (x_a * (x_a + 2.0))) * (r36 * x_a + 2.0))) * (1 - 0.0125) - 2.0 / (1 - 0.0125)) / 2.0) AS s36_20
    FROM z
)
SELECT g3, c3, tb, CAST(count(*) AS double) AS n,
       CAST(count_if(w20) AS double) AS w20, CAST(count_if(l20) AS double) AS l20,
       CAST(count_if(s20) AS double) AS s20, CAST(count_if(x20) AS double) AS x20,
       CAST(count_if(w36) AS double) AS w36, CAST(count_if(l36) AS double) AS l36,
       CAST(count_if(s36) AS double) AS s36, CAST(count_if(x36) AS double) AS x36,
       approx_percentile(x_a, 0.50) AS x_a_p50,
       avg(raw20) AS raw20, avg(fee20) AS fee20,
       avg(raw36) AS raw36, avg(fee36) AS fee36,
       avg(s20_05) AS s20_05, CAST(count_if(s20_05 > 0) AS double)/count(*) AS p20_05,
       avg(s20_10) AS s20_10, CAST(count_if(s20_10 > 0) AS double)/count(*) AS p20_10,
       avg(s20_20) AS s20_20, CAST(count_if(s20_20 > 0) AS double)/count(*) AS p20_20,
       avg(s36_05) AS s36_05, CAST(count_if(s36_05 > 0) AS double)/count(*) AS p36_05,
       avg(s36_10) AS s36_10, CAST(count_if(s36_10 > 0) AS double)/count(*) AS p36_10,
       avg(s36_20) AS s36_20, CAST(count_if(s36_20 > 0) AS double)/count(*) AS p36_20
FROM e
GROUP BY GROUPING SETS ((), (g3), (c3), (tb), (tb, g3), (tb, c3))
ORDER BY tb, g3, c3
