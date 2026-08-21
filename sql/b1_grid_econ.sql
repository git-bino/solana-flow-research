-- 1 -- the 45-combination exit grid on three subsets, with the exact
-- cost-model arithmetic evaluated ON DUNE.
--
-- WHY ON DUNE: a per-token export is 25,353 rows x ~25 columns; at the measured
-- retrieval price (11.748 cr per 1e6 result bytes) that is ~60 cr, more than the
-- whole task budget.  The arithmetic of src/cost_model.py::net_pnl is therefore
-- transcribed here, term for term, with V = 0 and pf = 0:
--     x1 = x_entry
--     dy = k*q / (x1*(x1+q))                  [cancellation-free form of
--                                              k/x1 - k/(x1+q)]
--     x2 = x_exit + q                         [x1 + q + W, W = x_exit - x_entry]
--     out = dy*x2^2 / (k + dy*x2)
--     net = out*(1-f) - q/(1-f) - 2*fixed_cost_per_leg
--     ret = net / q
-- k = 3.219e10, f = 0.0125 per side.  Python runs this in Decimal(60); here it
-- is float64.  The cancellation-free `dy` is exactly why that is safe -- the
-- measured Decimal-vs-float parity of this rewrite is 1.669e-14.
--
-- SUBSETS use the LOOKAHEAD-FREE features from result_flow_pdhist2 (§0), NOT the
-- original result_flow_pdhist.  Quintiles are global mid-rank quintiles taken
-- only after `WHERE ... IS NOT NULL` (the repeated rank()-on-NULL defect), and
-- every output row carries grouping().
--
-- TIE-BREAK: if two triggers fire at the same seq, the STOP is taken first, then
-- the target, then the time exit.  Stated, not silently ordered.
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
fl AS (
    SELECT token_mint,
           ceil(5.0*mb/nn) >= 5 AS f1,
           ceil(5.0*mb/nn) >= 5 AND ceil(5.0*m2/nn) >= 5 AS f2
    FROM r
),
b AS (
    SELECT g.*, coalesce(fl.f1, false) AS f1, coalesce(fl.f2, false) AS f2
    FROM dune.quantbino1695.result_flow_b1grid g
    LEFT JOIN fl ON fl.token_mint = g.token_mint
    WHERE g.x_en IS NOT NULL AND g.x_en > 0
),
c AS (
    SELECT b.ld, b.f1, b.f2, b.x_en AS x1, b.ut_en, b.final_x, b.final_ut,
           u.tl, u.sl, u.gl, u.ts, u.tx, u.tu, u.ss, u.sx, u.su, u.gs, u.gx, u.gu
    FROM b CROSS JOIN UNNEST(ARRAY[
        ROW('10','0.90','x60', q10, x10, u10, s90, xs90, us90, g60, xg60, ug60),
        ROW('10','0.90','xa15', q10, x10, u10, s90, xs90, us90, g15, xg15, ug15),
        ROW('10','0.90','xa20', q10, x10, u10, s90, xs90, us90, g20, xg20, ug20),
        ROW('10','0.85','x60', q10, x10, u10, s85, xs85, us85, g60, xg60, ug60),
        ROW('10','0.85','xa15', q10, x10, u10, s85, xs85, us85, g15, xg15, ug15),
        ROW('10','0.85','xa20', q10, x10, u10, s85, xs85, us85, g20, xg20, ug20),
        ROW('10','inf','x60', q10, x10, u10, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g60, xg60, ug60),
        ROW('10','inf','xa15', q10, x10, u10, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g15, xg15, ug15),
        ROW('10','inf','xa20', q10, x10, u10, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g20, xg20, ug20),
        ROW('20','0.90','x60', q20, x20, u20, s90, xs90, us90, g60, xg60, ug60),
        ROW('20','0.90','xa15', q20, x20, u20, s90, xs90, us90, g15, xg15, ug15),
        ROW('20','0.90','xa20', q20, x20, u20, s90, xs90, us90, g20, xg20, ug20),
        ROW('20','0.85','x60', q20, x20, u20, s85, xs85, us85, g60, xg60, ug60),
        ROW('20','0.85','xa15', q20, x20, u20, s85, xs85, us85, g15, xg15, ug15),
        ROW('20','0.85','xa20', q20, x20, u20, s85, xs85, us85, g20, xg20, ug20),
        ROW('20','inf','x60', q20, x20, u20, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g60, xg60, ug60),
        ROW('20','inf','xa15', q20, x20, u20, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g15, xg15, ug15),
        ROW('20','inf','xa20', q20, x20, u20, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g20, xg20, ug20),
        ROW('30','0.90','x60', q30, x30, u30, s90, xs90, us90, g60, xg60, ug60),
        ROW('30','0.90','xa15', q30, x30, u30, s90, xs90, us90, g15, xg15, ug15),
        ROW('30','0.90','xa20', q30, x30, u30, s90, xs90, us90, g20, xg20, ug20),
        ROW('30','0.85','x60', q30, x30, u30, s85, xs85, us85, g60, xg60, ug60),
        ROW('30','0.85','xa15', q30, x30, u30, s85, xs85, us85, g15, xg15, ug15),
        ROW('30','0.85','xa20', q30, x30, u30, s85, xs85, us85, g20, xg20, ug20),
        ROW('30','inf','x60', q30, x30, u30, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g60, xg60, ug60),
        ROW('30','inf','xa15', q30, x30, u30, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g15, xg15, ug15),
        ROW('30','inf','xa20', q30, x30, u30, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g20, xg20, ug20),
        ROW('60','0.90','x60', q60, x60t, u60t, s90, xs90, us90, g60, xg60, ug60),
        ROW('60','0.90','xa15', q60, x60t, u60t, s90, xs90, us90, g15, xg15, ug15),
        ROW('60','0.90','xa20', q60, x60t, u60t, s90, xs90, us90, g20, xg20, ug20),
        ROW('60','0.85','x60', q60, x60t, u60t, s85, xs85, us85, g60, xg60, ug60),
        ROW('60','0.85','xa15', q60, x60t, u60t, s85, xs85, us85, g15, xg15, ug15),
        ROW('60','0.85','xa20', q60, x60t, u60t, s85, xs85, us85, g20, xg20, ug20),
        ROW('60','inf','x60', q60, x60t, u60t, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g60, xg60, ug60),
        ROW('60','inf','xa15', q60, x60t, u60t, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g15, xg15, ug15),
        ROW('60','inf','xa20', q60, x60t, u60t, CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g20, xg20, ug20),
        ROW('inf','0.90','x60', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), s90, xs90, us90, g60, xg60, ug60),
        ROW('inf','0.90','xa15', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), s90, xs90, us90, g15, xg15, ug15),
        ROW('inf','0.90','xa20', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), s90, xs90, us90, g20, xg20, ug20),
        ROW('inf','0.85','x60', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), s85, xs85, us85, g60, xg60, ug60),
        ROW('inf','0.85','xa15', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), s85, xs85, us85, g15, xg15, ug15),
        ROW('inf','0.85','xa20', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), s85, xs85, us85, g20, xg20, ug20),
        ROW('inf','inf','x60', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g60, xg60, ug60),
        ROW('inf','inf','xa15', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g15, xg15, ug15),
        ROW('inf','inf','xa20', CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), CAST(NULL AS bigint), CAST(NULL AS double), CAST(NULL AS double), g20, xg20, ug20)
    ]) AS u(tl, sl, gl, ts, tx, tu, ss, sx, su, gs, gx, gu)
),
e AS (
    SELECT ld, f1, f2, tl, sl, gl, x1, ut_en,
           CASE WHEN ss IS NOT NULL AND (gs IS NULL OR ss <= gs)
                                   AND (ts IS NULL OR ss <= ts) THEN 'S'
                WHEN gs IS NOT NULL AND (ts IS NULL OR gs <= ts) THEN 'G'
                WHEN ts IS NOT NULL THEN 'T'
                ELSE 'E' END AS why,
           CASE WHEN ss IS NOT NULL AND (gs IS NULL OR ss <= gs)
                                   AND (ts IS NULL OR ss <= ts) THEN sx
                WHEN gs IS NOT NULL AND (ts IS NULL OR gs <= ts) THEN gx
                WHEN ts IS NOT NULL THEN tx
                ELSE final_x END AS x_ex_raw,
           CASE WHEN ss IS NOT NULL AND (gs IS NULL OR ss <= gs)
                                   AND (ts IS NULL OR ss <= ts) THEN su
                WHEN gs IS NOT NULL AND (ts IS NULL OR gs <= ts) THEN gu
                WHEN ts IS NOT NULL THEN tu
                ELSE final_ut END AS ut_ex_raw
    FROM c
),
f AS (
    SELECT ld, f1, f2, tl, sl, gl, why, x1, ut_en,
           coalesce(x_ex_raw, 0.0) AS x_ex_c, x_ex_raw, ut_ex_raw
    FROM e
),
z AS (
    SELECT ld, f1, f2, tl, sl, gl, why, ut_ex_raw - ut_en AS hold_s,
           x1, coalesce(x_ex_raw, x1) AS x_ex
    FROM f
)
SELECT tl, sl, gl, ld, f1, f2,
       CAST(grouping(tl, sl, gl, ld, f1, f2) AS integer) AS gset,
       CAST(count(*) AS double) AS n,
       sum((( (3.219e10*0.05/(x1*(x1+0.05))) * (x_ex+0.05)*(x_ex+0.05) / (3.219e10 + (3.219e10*0.05/(x1*(x1+0.05)))*(x_ex+0.05)) ) * 0.9875 - 0.05/0.9875 - 2*0.0) / 0.05) AS s_a, CAST(count_if(((( (3.219e10*0.05/(x1*(x1+0.05))) * (x_ex+0.05)*(x_ex+0.05) / (3.219e10 + (3.219e10*0.05/(x1*(x1+0.05)))*(x_ex+0.05)) ) * 0.9875 - 0.05/0.9875 - 2*0.0) / 0.05) > 0) AS double) AS p_a,
       sum((( (3.219e10*0.05/(x1*(x1+0.05))) * (x_ex+0.05)*(x_ex+0.05) / (3.219e10 + (3.219e10*0.05/(x1*(x1+0.05)))*(x_ex+0.05)) ) * 0.9875 - 0.05/0.9875 - 2*0.001) / 0.05) AS s_b, CAST(count_if(((( (3.219e10*0.05/(x1*(x1+0.05))) * (x_ex+0.05)*(x_ex+0.05) / (3.219e10 + (3.219e10*0.05/(x1*(x1+0.05)))*(x_ex+0.05)) ) * 0.9875 - 0.05/0.9875 - 2*0.001) / 0.05) > 0) AS double) AS p_b,
       sum((( (3.219e10*0.5/(x1*(x1+0.5))) * (x_ex+0.5)*(x_ex+0.5) / (3.219e10 + (3.219e10*0.5/(x1*(x1+0.5)))*(x_ex+0.5)) ) * 0.9875 - 0.5/0.9875 - 2*0.0) / 0.5) AS s_c, CAST(count_if(((( (3.219e10*0.5/(x1*(x1+0.5))) * (x_ex+0.5)*(x_ex+0.5) / (3.219e10 + (3.219e10*0.5/(x1*(x1+0.5)))*(x_ex+0.5)) ) * 0.9875 - 0.5/0.9875 - 2*0.0) / 0.5) > 0) AS double) AS p_c,
       sum((( (3.219e10*0.5/(x1*(x1+0.5))) * (x_ex+0.5)*(x_ex+0.5) / (3.219e10 + (3.219e10*0.5/(x1*(x1+0.5)))*(x_ex+0.5)) ) * 0.9875 - 0.5/0.9875 - 2*0.001) / 0.5) AS s_d, CAST(count_if(((( (3.219e10*0.5/(x1*(x1+0.5))) * (x_ex+0.5)*(x_ex+0.5) / (3.219e10 + (3.219e10*0.5/(x1*(x1+0.5)))*(x_ex+0.5)) ) * 0.9875 - 0.5/0.9875 - 2*0.001) / 0.5) > 0) AS double) AS p_d,
       approx_percentile((( (3.219e10*0.05/(x1*(x1+0.05))) * (x_ex+0.05)*(x_ex+0.05) / (3.219e10 + (3.219e10*0.05/(x1*(x1+0.05)))*(x_ex+0.05)) ) * 0.9875 - 0.05/0.9875 - 2*0.0) / 0.05, 0.50) AS med_a,
       CAST(count_if(why='T') AS double) AS w_t,
       CAST(count_if(why='S') AS double) AS w_s,
       CAST(count_if(why='G') AS double) AS w_g,
       CAST(count_if(why='E') AS double) AS w_e,
       approx_percentile(hold_s, 0.50) AS hold50
FROM z
GROUP BY GROUPING SETS ((tl,sl,gl,ld), (tl,sl,gl,f1,ld), (tl,sl,gl,f1,f2,ld))
