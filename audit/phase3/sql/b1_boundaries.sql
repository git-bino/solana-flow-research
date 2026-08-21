-- 1 + 2 -- the quintile boundaries under BOTH percentile conventions.
--
-- DECISION (research lead, 2026-08-21): NEAREST-RANK is authoritative.
-- `approx_percentile` is a t-digest -- an approximation whose answer depends on
-- the data it saw -- and a frozen rule boundary has to be exact and reproducible
-- on the holdout.  This query keeps both so the switch is quantified, not
-- assumed harmless.
--
-- NEAREST-RANK p80 = sorted[ceil(0.8*n) - 1] zero-based, i.e. the value at
-- row_number() = ceil(0.8*n).  NULLs are removed BEFORE any ranking (the
-- repeated rank()-on-NULL defect).
WITH h AS (
    SELECT token_mint, wr_med, wr_p90
    FROM dune.quantbino1695.result_flow_pdhist2
    WHERE wr_med IS NOT NULL AND wr_p90 IS NOT NULL
),
r AS (
    SELECT token_mint, wr_med, wr_p90,
           row_number() OVER (ORDER BY wr_med)  AS rn1,
           row_number() OVER (ORDER BY wr_p90)  AS rn2,
           CAST(count(*) OVER () AS bigint)     AS n,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double)-1)/2.0 AS m1,
           CAST(rank() OVER (ORDER BY wr_p90) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_p90) AS double)-1)/2.0 AS m2
    FROM h
),
b AS (
    SELECT max(n) AS n,
           max(if(rn1 = CAST(ceil(0.8 * n) AS bigint), wr_med)) AS b1_nr,
           max(if(rn2 = CAST(ceil(0.8 * n) AS bigint), wr_p90)) AS b2_nr,
           approx_percentile(wr_med, 0.80)  AS b1_ap,
           approx_percentile(wr_p90, 0.80)  AS b2_ap,
           -- the mid-rank quintile boundary actually used by the analysis:
           -- the smallest value whose mid-rank lands in group 5
           min(if(ceil(5.0 * m1 / n) >= 5, wr_med)) AS b1_mr,
           min(if(ceil(5.0 * m2 / n) >= 5, wr_p90)) AS b2_mr
    FROM r
),
j AS (
    SELECT r.wr_med, r.wr_p90, r.m1, r.m2, r.n AS n,
           b.b1_nr, b.b2_nr, b.b1_ap, b.b2_ap, b.b1_mr, b.b2_mr, p.win
    FROM r CROSS JOIN b
    JOIN dune.quantbino1695.result_flow_pd p ON p.token_mint = r.token_mint
)
SELECT CAST(max(n) AS double) AS n_pop,
       max(b1_nr) AS b1_nr, max(b2_nr) AS b2_nr,
       max(b1_ap) AS b1_ap, max(b2_ap) AS b2_ap,
       max(b1_mr) AS b1_mr, max(b2_mr) AS b2_mr,
       CAST(count_if(wr_med >= b1_nr AND wr_p90 >= b2_nr) AS double) AS n_nr,
       CAST(count_if(wr_med >= b1_ap AND wr_p90 >= b2_ap) AS double) AS n_ap,
       CAST(count_if(ceil(5.0*m1/n) >= 5 AND ceil(5.0*m2/n) >= 5) AS double) AS n_mr,
       CAST(count_if(win AND wr_med >= b1_nr AND wr_p90 >= b2_nr) AS double)
         / nullif(CAST(count_if(wr_med >= b1_nr AND wr_p90 >= b2_nr) AS double),0) AS s60_nr,
       CAST(count_if(win AND wr_med >= b1_ap AND wr_p90 >= b2_ap) AS double)
         / nullif(CAST(count_if(wr_med >= b1_ap AND wr_p90 >= b2_ap) AS double),0) AS s60_ap,
       CAST(count_if(win AND ceil(5.0*m1/n) >= 5 AND ceil(5.0*m2/n) >= 5) AS double)
         / nullif(CAST(count_if(ceil(5.0*m1/n) >= 5 AND ceil(5.0*m2/n) >= 5) AS double),0) AS s60_mr
FROM j
