-- AUDIT 4 FIX 2 -- four terminal states, NO FALLBACKS.
--
-- CAUSAL universe (createevent.is_mayhem_mode = false).  Config: T = 60 s,
-- S = infinity, G = x >= 60, q = 0.5, fixed_cost_per_leg = 0.001, H20 anchor,
-- entry and exit delay 3 events.
--
-- STATES
--   CLOSED_TARGET   x >= 60 fired first AND the 3rd event after it exists
--   CLOSED_TIME     the 60 s limit fired first AND that 3rd event exists
--   OPEN_NO_FILL    a trigger fired but the 3rd event after it does not exist
--   OPEN_NO_TRIGGER no trigger ever fired
--
-- FALLBACKS ARE FORBIDDEN.  `final_x`, `entry_price` and `last_x` are NOT used
-- to price anything.  An OPEN position has NO realised PnL: it is excluded from
-- the closed-only mean and enters the all-positions mean as 0, which is a LOWER
-- BOUND, not an estimate.  The line `coalesce(x_ex_raw, ...)` that produced the
-- earlier numbers does not appear in this file.
-- `x_last / x_entry` for OPEN rows is reported for DIAGNOSIS ONLY and is never
-- turned into a return.
--
-- ret uses the k-free rearrangement verified to 4.940e-57 against
-- src/cost_model.py::net_pnl:  out = q*x2^2 / (x1*(x1+q) + q*x2)
--
-- Ranks are taken on a population with no NULL ret; grouping() labels every row.
WITH coh AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_clean WHERE mayhem_flag = false
),
sub AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_pdhist3
    WHERE wr_med IS NOT NULL AND wr_p90 IS NOT NULL
      AND wr_med >= 0.572927597 AND wr_p90 >= 1.000000000
),
g AS (
    SELECT b.token_mint, b.ld, b.x_en AS x1, b.final_x,
           b.q60, b.x60t, b.g60, b.xg60,
           s.token_mint IS NOT NULL AS f2
    FROM dune.quantbino1695.result_flow_b1grid b
    JOIN coh c ON c.token_mint = b.token_mint
    LEFT JOIN sub s ON s.token_mint = b.token_mint
    WHERE b.x_en IS NOT NULL AND b.x_en > 0
),
st AS (
    SELECT ld, f2, x1, final_x,
           CASE WHEN g60 IS NOT NULL AND (q60 IS NULL OR g60 <= q60)
                     THEN if(xg60 IS NOT NULL, 'CLOSED_TARGET', 'OPEN_NO_FILL')
                WHEN q60 IS NOT NULL
                     THEN if(x60t IS NOT NULL, 'CLOSED_TIME', 'OPEN_NO_FILL')
                ELSE 'OPEN_NO_TRIGGER' END AS state,
           CASE WHEN g60 IS NOT NULL AND (q60 IS NULL OR g60 <= q60) THEN xg60
                WHEN q60 IS NOT NULL THEN x60t END AS x_exit   -- NULL when OPEN
    FROM g
),
r AS (
    SELECT ld, f2, state, x1, final_x,
           if(x_exit IS NOT NULL,
              ((0.5*(x_exit+0.5)*(x_exit+0.5) / (x1*(x1+0.5) + 0.5*(x_exit+0.5))) * 0.9875
               - 0.5/0.9875 - 0.002) / 0.5) AS ret
    FROM st
),
p AS (
    SELECT r.*,
           percent_rank() OVER (PARTITION BY (ret IS NULL) ORDER BY ret)     AS pa,
           percent_rank() OVER (PARTITION BY f2, (ret IS NULL) ORDER BY ret) AS pf
    FROM r
)
SELECT f2, ld, CAST(grouping(f2, ld) AS integer) AS gset,
       CAST(count(*) AS double)                                      AS n_all,
       CAST(count_if(state='CLOSED_TARGET') AS double)               AS n_ct,
       CAST(count_if(state='CLOSED_TIME') AS double)                 AS n_cm,
       CAST(count_if(state='OPEN_NO_FILL') AS double)                AS n_of,
       CAST(count_if(state='OPEN_NO_TRIGGER') AS double)             AS n_ot,
       sum(ret)                                                      AS s_closed,
       CAST(count_if(ret IS NOT NULL) AS double)                     AS n_closed,
       CAST(count_if(ret > 0) AS double)                             AS n_pos,
       approx_percentile(ret, 0.50)                                  AS med_closed,
       sum(if(pa > 0.01 AND pa < 0.99, ret))/nullif(CAST(count_if(ret IS NOT NULL AND pa > 0.01 AND pa < 0.99) AS double),0) AS t1_a,
       sum(if(pa > 0.05 AND pa < 0.95, ret))/nullif(CAST(count_if(ret IS NOT NULL AND pa > 0.05 AND pa < 0.95) AS double),0) AS t5_a,
       sum(if(pa > 0.10 AND pa < 0.90, ret))/nullif(CAST(count_if(ret IS NOT NULL AND pa > 0.10 AND pa < 0.90) AS double),0) AS t10_a,
       sum(if(pf > 0.01 AND pf < 0.99, ret))/nullif(CAST(count_if(ret IS NOT NULL AND pf > 0.01 AND pf < 0.99) AS double),0) AS t1_f,
       sum(if(pf > 0.05 AND pf < 0.95, ret))/nullif(CAST(count_if(ret IS NOT NULL AND pf > 0.05 AND pf < 0.95) AS double),0) AS t5_f,
       sum(if(pf > 0.10 AND pf < 0.90, ret))/nullif(CAST(count_if(ret IS NOT NULL AND pf > 0.10 AND pf < 0.90) AS double),0) AS t10_f,
       -- DIAGNOSTIC ONLY, never priced
       approx_percentile(if(ret IS NULL, final_x / x1), 0.10)        AS o10,
       approx_percentile(if(ret IS NULL, final_x / x1), 0.50)        AS o50,
       approx_percentile(if(ret IS NULL, final_x / x1), 0.90)        AS o90
FROM p GROUP BY GROUPING SETS ((), (f2), (ld), (f2, ld))
