-- 4 -- scale of the highest-trim5 cell: B1q5 x B2q5, T = 60 s, S = inf, G = x60.
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР only in WHICH cell is measured (the one with
-- the highest trim5); no combination is being selected as a result.
--
-- CONCURRENCY is a sweep: +1 at each entry time, -1 at each exit time, running
-- sum over the merged, time-ordered stream.  Positions from different launch
-- days overlap in wall-clock time, so the sweep is GLOBAL, not per day.
WITH h AS (
    SELECT token_mint, wr_med, wr_p90 FROM dune.quantbino1695.result_flow_pdhist2
    WHERE wr_med IS NOT NULL AND wr_p90 IS NOT NULL
),
r AS (
    SELECT token_mint,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double)-1)/2.0 AS mb,
           CAST(rank() OVER (ORDER BY wr_p90) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_p90) AS double)-1)/2.0 AS m2,
           CAST(count(*) OVER () AS double) AS nn
    FROM h
),
fl AS (SELECT token_mint FROM r
       WHERE ceil(5.0*mb/nn) >= 5 AND ceil(5.0*m2/nn) >= 5),
b AS (
    SELECT g.token_mint, g.ld, g.ut_en, g.x_en,
           CASE WHEN g.g60 IS NOT NULL AND (g.q60 IS NULL OR g.g60 <= g.q60) THEN g.ug60
                WHEN g.q60 IS NOT NULL THEN g.u60t ELSE g.final_ut END AS ut_ex
    FROM dune.quantbino1695.result_flow_b1grid g
    JOIN fl ON fl.token_mint = g.token_mint
    WHERE g.x_en IS NOT NULL AND g.x_en > 0
),
p AS (SELECT token_mint, ld, ut_en, coalesce(ut_ex, ut_en) AS ut_ex FROM b),
ev AS (
    SELECT u.t, u.d FROM p CROSS JOIN UNNEST(ARRAY[ROW(ut_en, 1), ROW(ut_ex, -1)]) AS u(t, d)
),
sw AS (
    SELECT t, sum(sum(d)) OVER (ORDER BY t ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS c
    FROM ev GROUP BY t
)
SELECT 'concurrency' AS part, CAST(NULL AS varchar) AS ld,
       CAST(count(*) AS double) AS n,
       approx_percentile(CAST(c AS double), 0.50) AS v50,
       approx_percentile(CAST(c AS double), 0.90) AS v90,
       CAST(max(c) AS double) AS vmax
FROM sw
UNION ALL
SELECT 'hold_s', NULL, CAST(count(*) AS double),
       approx_percentile(ut_ex - ut_en, 0.50), approx_percentile(ut_ex - ut_en, 0.90),
       max(ut_ex - ut_en)
FROM p
UNION ALL
SELECT 'per_day', CAST(ld AS varchar), CAST(count(*) AS double), NULL, NULL, NULL
FROM p GROUP BY ld
ORDER BY part, ld
