-- 3 -- ORDERING CHECK on the (A2, A3, A4) variables.
-- They are measured AT THE DRAWDOWN.  If the 60-crossing happens BEFORE the
-- drawdown, the variable is measured after the outcome is already decided and
-- carries lookahead.  This counts exactly how often that is the case.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
d AS (
    SELECT d.token_mint, d.seq_drop, d.seq_60, d.t_drop_s, d.t_60_s
    FROM dune.quantbino1695.result_flow_dd d JOIN coh c ON c.token_mint = d.token_mint
    WHERE d.anchor_kind = 'H20'
),
o AS (
    SELECT CASE WHEN seq_60 IS NULL THEN '3_no60'
                WHEN seq_drop IS NULL THEN '4_no_drop'
                WHEN seq_60 < seq_drop THEN '1_60_before_drop'
                ELSE '2_drop_before_60' END AS ord,
           t_60_s, t_drop_s
    FROM d
)
SELECT ord, CAST(count(*) AS double) AS n,
       approx_percentile(t_60_s, 0.50) AS t60,
       approx_percentile(t_drop_s, 0.50) AS tdrop
FROM o GROUP BY GROUPING SETS ((), (ord)) ORDER BY ord
