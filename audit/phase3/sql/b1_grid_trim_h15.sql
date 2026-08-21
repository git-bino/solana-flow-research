-- 3 -- H15 repeat: same six combinations, same filter, same arithmetic.
-- 2 -- trimmed means for the six highest-E[ret] combinations.
--
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР: the brief asks for trims on EVERY positive
-- combination (83 of 135).  Trimming needs a rank window over the combination's
-- rows; at 45 combinations the same shape already cost 16.579 cr and only 15.257
-- of the 40-credit budget remain, so the six combinations with the highest
-- E[ret] are trimmed instead.  The reduction is a COST decision, not a result.
--
-- q = 0.05, fixed_cost_per_leg = 0 (the headline cell).  Same cost arithmetic and
-- same tie-break as sql/b1_grid_econ.sql.
--
-- THREE POPULATIONS, THREE WINDOWS.  `percent_rank()` over (combo) is the ALL
-- population; over (combo, f1) it splits B1q5 from its complement, so the
-- f1 = true side is exactly B1q5; likewise (combo, f2).  Each grouping set reads
-- the column belonging to its own population -- they are never mixed.
-- `ret` is never NULL here, so no rank-on-NULL case arises.
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
fl AS (SELECT token_mint, ceil(5.0*mb/nn) >= 5 AS f1,
              ceil(5.0*mb/nn) >= 5 AND ceil(5.0*m2/nn) >= 5 AS f2 FROM r),
b AS (
    SELECT g.*, coalesce(fl.f1,false) AS f1, coalesce(fl.f2,false) AS f2
    FROM dune.quantbino1695.result_flow_b1grid15 g
    LEFT JOIN fl ON fl.token_mint = g.token_mint
    WHERE g.x_en IS NOT NULL AND g.x_en > 0
),
c AS (
    SELECT b.f1, b.f2, b.x_en AS x1, b.final_x,
           u.tl, u.sl, u.gl, u.ts, u.tx, u.gs, u.gx, u.ss, u.sx
    FROM b CROSS JOIN UNNEST(ARRAY[
        ROW('60','inf','xa15', q60, x60t, g15, xg15, CAST(NULL AS bigint), CAST(NULL AS double)),
        ROW('60','inf','x60', q60, x60t, g60, xg60, CAST(NULL AS bigint), CAST(NULL AS double)),
        ROW('inf','0.90','x60', CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60, s90, xs90),
        ROW('60','inf','xa20', q60, x60t, g20, xg20, CAST(NULL AS bigint), CAST(NULL AS double)),
        ROW('inf','0.85','x60', CAST(NULL AS bigint), CAST(NULL AS double), g60, xg60, s85, xs85),
        ROW('30','inf','x60', q30, x30, g60, xg60, CAST(NULL AS bigint), CAST(NULL AS double))
    ]) AS u(tl, sl, gl, ts, tx, gs, gx, ss, sx)
),
e AS (
    SELECT f1, f2, tl, sl, gl, x1,
           CASE WHEN ss IS NOT NULL AND (gs IS NULL OR ss <= gs) AND (ts IS NULL OR ss <= ts) THEN sx
                WHEN gs IS NOT NULL AND (ts IS NULL OR gs <= ts) THEN gx
                WHEN ts IS NOT NULL THEN tx ELSE final_x END AS x_ex_raw
    FROM c
),
z AS (SELECT f1, f2, tl, sl, gl, x1, coalesce(x_ex_raw, x1) AS x_ex FROM e),
w AS (
    SELECT f1, f2, tl, sl, gl, (( (3.219e10*0.05/(x1*(x1+0.05))) * (x_ex+0.05)*(x_ex+0.05) / (3.219e10 + (3.219e10*0.05/(x1*(x1+0.05)))*(x_ex+0.05)) ) * 0.9875 - 0.05/0.9875) / 0.05 AS ret FROM z
),
pr AS (
    SELECT w.*,
           percent_rank() OVER (PARTITION BY tl, sl, gl ORDER BY ret)     AS pa,
           percent_rank() OVER (PARTITION BY tl, sl, gl, f1 ORDER BY ret) AS p1,
           percent_rank() OVER (PARTITION BY tl, sl, gl, f2 ORDER BY ret) AS p2
    FROM w
)
SELECT tl, sl, gl, f1, f2,
       CAST(grouping(tl, sl, gl, f1, f2) AS integer) AS gset,
       CAST(count(*) AS double) AS n, sum(ret) AS s_raw,
       sum(if(pa > 0.01 AND pa < 0.99, ret)) AS t1s_a,
       CAST(count_if(pa > 0.01 AND pa < 0.99) AS double) AS t1n_a,
       sum(if(p1 > 0.01 AND p1 < 0.99, ret)) AS t1s_b,
       CAST(count_if(p1 > 0.01 AND p1 < 0.99) AS double) AS t1n_b,
       sum(if(p2 > 0.01 AND p2 < 0.99, ret)) AS t1s_c,
       CAST(count_if(p2 > 0.01 AND p2 < 0.99) AS double) AS t1n_c,
       sum(if(pa > 0.05 AND pa < 0.95, ret)) AS t5s_a,
       CAST(count_if(pa > 0.05 AND pa < 0.95) AS double) AS t5n_a,
       sum(if(p1 > 0.05 AND p1 < 0.95, ret)) AS t5s_b,
       CAST(count_if(p1 > 0.05 AND p1 < 0.95) AS double) AS t5n_b,
       sum(if(p2 > 0.05 AND p2 < 0.95, ret)) AS t5s_c,
       CAST(count_if(p2 > 0.05 AND p2 < 0.95) AS double) AS t5n_c,
       sum(if(pa > 0.1 AND pa < 0.9, ret)) AS t10s_a,
       CAST(count_if(pa > 0.1 AND pa < 0.9) AS double) AS t10n_a,
       sum(if(p1 > 0.1 AND p1 < 0.9, ret)) AS t10s_b,
       CAST(count_if(p1 > 0.1 AND p1 < 0.9) AS double) AS t10n_b,
       sum(if(p2 > 0.1 AND p2 < 0.9, ret)) AS t10s_c,
       CAST(count_if(p2 > 0.1 AND p2 < 0.9) AS double) AS t10n_c
FROM pr GROUP BY GROUPING SETS ((tl,sl,gl), (tl,sl,gl,f1), (tl,sl,gl,f1,f2))
