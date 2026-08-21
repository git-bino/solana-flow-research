-- 3 + 4 -- numeric reconciliation of the frozen rule, and the unfilled-exit
-- convention measured both ways.
--
-- CONFIG (frozen, research lead 2026-08-21): B1q5 x B2q5 selected by the
-- NEAREST-RANK boundaries, T = 60 s, S = infinity, G = x >= 60, q = 0.5,
-- fixed_cost_per_leg = 0.001, entry/exit delay 3 events, anchor H20.
-- The subset is taken with `>= boundary`, which is what src/b1_rule.py does;
-- the boundaries are the frozen numbers from sql/b1_boundaries.sql.
--
-- TWO ALGEBRAS ON PURPOSE.  A match between two transcriptions of the SAME
-- expression proves nothing, so the second form is derived rather than copied:
--
--     dy   = k*q/(x1*(x1+q))                     xe = x1+q
--     out  = dy*x2^2/(k + dy*x2)
--          = [k*q/(x1*xe)]*x2^2 / (k*(1 + q*x2/(x1*xe)))
--          = q*x2^2 / (x1*xe + q*x2)             <-- k CANCELS COMPLETELY
--
-- `ret_o` uses the first form (k = 3.219e10 appears three times); `ret_a` uses
-- the second (k does not appear at all).  Checked against
-- src/cost_model.py::net_pnl in Decimal(60) over 252 grid points before this
-- query was written: max |delta| = 4.940e-57.
--
-- TWO UNFILLED-EXIT CONVENTIONS.  When the trigger fires with fewer than three
-- trade events left the exit never fills.
--   A "entry_price"  exit at the ENTRY reserve -- a fee-only round trip.  This
--                    is what sql/b1_grid_econ.sql did and what the published
--                    numbers use.  It is the OPTIMISTIC reading.
--   B "last_x"       exit at the LAST OBSERVED reserve -- the trader who cannot
--                    get out sits there while the price falls.
--
-- percent_rank() is taken over a population with no NULL ret, so the repeated
-- rank-on-NULL defect cannot arise here.
WITH h AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_pdhist2
    WHERE wr_med IS NOT NULL AND wr_p90 IS NOT NULL
      AND wr_med >= 0.572916667 AND wr_p90 >= 1.000000000
),
b AS (
    SELECT g.token_mint, g.x_en AS x1, g.final_x, g.q60, g.x60t, g.g60, g.xg60
    FROM dune.quantbino1695.result_flow_b1grid g
    JOIN h ON h.token_mint = g.token_mint
    WHERE g.x_en IS NOT NULL AND g.x_en > 0
),
e AS (
    SELECT x1, final_x,
           CASE WHEN g60 IS NOT NULL AND (q60 IS NULL OR g60 <= q60) THEN 'G'
                WHEN q60 IS NOT NULL THEN 'T' ELSE 'E' END AS why,
           CASE WHEN g60 IS NOT NULL AND (q60 IS NULL OR g60 <= q60) THEN xg60
                WHEN q60 IS NOT NULL THEN x60t ELSE final_x END AS x_raw
    FROM b
),
z AS (
    SELECT why, x1, x_raw IS NULL AS unfilled,
           coalesce(x_raw, x1)      AS xa_conv,   -- A: entry_price
           coalesce(x_raw, final_x) AS xb_conv    -- B: last observed x
    FROM e
),
r AS (
    SELECT why, unfilled, x1,
           -- ORIGINAL form, k explicit
           (((3.219e10*0.5/(x1*(x1+0.5))) * (xa_conv+0.5)*(xa_conv+0.5)
             / (3.219e10 + (3.219e10*0.5/(x1*(x1+0.5)))*(xa_conv+0.5))) * 0.9875
            - 0.5/0.9875 - 0.002) / 0.5 AS ret_ao,
           -- ALTERNATE form, k-free
           ((0.5*(xa_conv+0.5)*(xa_conv+0.5) / (x1*(x1+0.5) + 0.5*(xa_conv+0.5))) * 0.9875
            - 0.5/0.9875 - 0.002) / 0.5 AS ret_aa,
           (((3.219e10*0.5/(x1*(x1+0.5))) * (xb_conv+0.5)*(xb_conv+0.5)
             / (3.219e10 + (3.219e10*0.5/(x1*(x1+0.5)))*(xb_conv+0.5))) * 0.9875
            - 0.5/0.9875 - 0.002) / 0.5 AS ret_bo,
           ((0.5*(xb_conv+0.5)*(xb_conv+0.5) / (x1*(x1+0.5) + 0.5*(xb_conv+0.5))) * 0.9875
            - 0.5/0.9875 - 0.002) / 0.5 AS ret_ba
    FROM z
),
p AS (
    SELECT r.*,
           percent_rank() OVER (ORDER BY ret_ao) AS pa,
           percent_rank() OVER (ORDER BY ret_bo) AS pb
    FROM r
)
SELECT CAST(count(*) AS double)                       AS n,
       CAST(count_if(unfilled) AS double)             AS n_unfilled,
       avg(ret_ao) AS ea_o, avg(ret_aa) AS ea_a,
       max(abs(ret_ao - ret_aa))                      AS d_alg_a,
       avg(ret_bo) AS eb_o, avg(ret_ba) AS eb_a,
       max(abs(ret_bo - ret_ba))                      AS d_alg_b,
       approx_percentile(ret_ao, 0.50) AS med_a,
       approx_percentile(ret_bo, 0.50) AS med_b,
       CAST(count_if(ret_ao > 0) AS double)/count(*)  AS pos_a,
       CAST(count_if(ret_bo > 0) AS double)/count(*)  AS pos_b,
       sum(if(pa > 0.01 AND pa < 0.99, ret_ao))/nullif(CAST(count_if(pa > 0.01 AND pa < 0.99) AS double),0) AS t1_a,
       sum(if(pa > 0.05 AND pa < 0.95, ret_ao))/nullif(CAST(count_if(pa > 0.05 AND pa < 0.95) AS double),0) AS t5_a,
       sum(if(pa > 0.10 AND pa < 0.90, ret_ao))/nullif(CAST(count_if(pa > 0.10 AND pa < 0.90) AS double),0) AS t10_a,
       sum(if(pb > 0.01 AND pb < 0.99, ret_bo))/nullif(CAST(count_if(pb > 0.01 AND pb < 0.99) AS double),0) AS t1_b,
       sum(if(pb > 0.05 AND pb < 0.95, ret_bo))/nullif(CAST(count_if(pb > 0.05 AND pb < 0.95) AS double),0) AS t5_b,
       sum(if(pb > 0.10 AND pb < 0.90, ret_bo))/nullif(CAST(count_if(pb > 0.10 AND pb < 0.90) AS double),0) AS t10_b,
       CAST(count_if(why='T') AS double)/count(*)     AS w_t,
       CAST(count_if(why='G') AS double)/count(*)     AS w_g,
       CAST(count_if(why='E') AS double)/count(*)     AS w_e
FROM p
