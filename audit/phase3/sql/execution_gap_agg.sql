-- 1 + 2 -- delayed fills and the corrected E[ret].  One pass, no `ntile`,
-- sources read once, every level of detail from one GROUPING SETS aggregation.
--
-- ENTRY that never filled (token died inside the delay) leaves the entry reserve
-- NULL; those rows are counted as NOT TRADED and are excluded from the mean but
-- reported as a share.  An order that never fills has no return -- it is not a
-- zero and not a loss.
--
-- EXIT that never filled (target hit but fewer than k events after the crossing)
-- falls back to the OBSERVED `final_x`: the position is still open at the window
-- edge.  Same for a target that was never hit (this is the no-stop variant).
--
-- Slippage is `cost_model.net_pnl`'s exact path with V = 0, pf = 0, fee 1.25%
-- PER SIDE, `dy` written as k*q/(x1*(x1+q)) -- checked against Decimal(60) at
-- 1.669e-14 in src/asymmetric_barriers.py.
WITH gi AS (SELECT * FROM dune.quantbino1695.result_flow_gapin),
go AS (SELECT * FROM dune.quantbino1695.result_flow_gapout),
hb AS (SELECT token_mint, x_u76, x_u35 FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_gini, f_creator
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
tb AS (SELECT token_mint, date(launch_time) AS ld
       FROM dune.quantbino1695.result_flow_token_base),
j AS (
    SELECT gi.*, go.x76_e1, go.x76_e3, go.x35_e1, go.x35_e3,
           hb.x_u76, hb.x_u35, hf.f_gini, hf.f_creator, tb.ld
    FROM gi JOIN hf ON hf.token_mint = gi.token_mint
            JOIN hb ON hb.token_mint = gi.token_mint
            JOIN tb ON tb.token_mint = gi.token_mint
            LEFT JOIN go ON go.token_mint = gi.token_mint
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
c AS (
    SELECT rk.*,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3,
           CASE WHEN t_a_s < 3 THEN 'x' WHEN t_a_s < 10 THEN '3_3to10s'
                ELSE '4_gt10s' END AS tbk
    FROM rk
),
cell AS (
    SELECT c.*, cc.cell FROM c CROSS JOIN UNNEST(ARRAY[
        ROW('gini g1', g3), ROW('creator c1', c3)]) AS cc(cell, tv)
    WHERE cc.tv = 1 AND c.tbk <> 'x'
),
p AS (
    SELECT cell, tbk, ld, x_a, x_e8, u.tgt, u.lab, u.xe, u.xx
    FROM cell CROSS JOIN UNNEST(ARRAY[

        ROW('+76%', 'e0 (одоогийн)', x_a, coalesce(x_u76, final_x)),
        ROW('+76%', 'e1 (1 event)', x_e1, coalesce(x_u76, final_x)),
        ROW('+76%', 'e3 (3 event)', x_e3, coalesce(x_u76, final_x)),
        ROW('+76%', 'e8 (8 event)', x_e8, coalesce(x_u76, final_x)),
        ROW('+76%', 't04 (0.4 с)', x_t04, coalesce(x_u76, final_x)),
        ROW('+76%', 't12 (1.2 с)', x_t12, coalesce(x_u76, final_x)),
        ROW('+76%', 't32 (3.2 с)', x_t32, coalesce(x_u76, final_x)),
        ROW('+76%', 'e0 × гарц 1', x_a, if(x_u76 IS NULL, final_x, coalesce(x76_e1, final_x))),
        ROW('+76%', 'e0 × гарц 3', x_a, if(x_u76 IS NULL, final_x, coalesce(x76_e3, final_x))),
        ROW('+76%', 'РЕАЛИСТИК e3 × гарц 3', x_e3, if(x_u76 IS NULL, final_x, coalesce(x76_e3, final_x))),
        ROW('+135%', 'e0 (одоогийн)', x_a, coalesce(x_u35, final_x)),
        ROW('+135%', 'e1 (1 event)', x_e1, coalesce(x_u35, final_x)),
        ROW('+135%', 'e3 (3 event)', x_e3, coalesce(x_u35, final_x)),
        ROW('+135%', 'e8 (8 event)', x_e8, coalesce(x_u35, final_x)),
        ROW('+135%', 't04 (0.4 с)', x_t04, coalesce(x_u35, final_x)),
        ROW('+135%', 't12 (1.2 с)', x_t12, coalesce(x_u35, final_x)),
        ROW('+135%', 't32 (3.2 с)', x_t32, coalesce(x_u35, final_x)),
        ROW('+135%', 'e0 × гарц 1', x_a, if(x_u35 IS NULL, final_x, coalesce(x35_e1, final_x))),
        ROW('+135%', 'e0 × гарц 3', x_a, if(x_u35 IS NULL, final_x, coalesce(x35_e3, final_x))),
        ROW('+135%', 'РЕАЛИСТИК e3 × гарц 3', x_e3, if(x_u35 IS NULL, final_x, coalesce(x35_e3, final_x)))
    ]) AS u(tgt, lab, xe, xx)
),
e AS (
    SELECT p.*, xe / x_a AS fill_ratio,
           if(xe IS NULL, NULL, ((((32190000000.0 * 1.0 / (xe * (xe + 1.0))) * (xx + 1.0) * (xx + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (xe * (xe + 1.0))) * (xx + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0)) AS ret
    FROM p
),
-- DEFECT FIXED (mine, 2026-08-21): `percent_rank()` ranks NULLs too, so at the
-- 8-event delay -- where 26.11% of rows never filled -- every trim level fell
-- inside the NULL block and trim1/trim5/trim10 all collapsed onto the mean.
-- Partitioning by `ret IS NULL` gives the filled rows their own 0..1 ranking.
--
-- `common8` marks the rows that fill at EVERY delay (they have an 8th event), so
-- the delays can also be compared on a CONSTANT population.  Without it the
-- means are not like-for-like: the rows dropped by a longer delay are the tokens
-- that died fast, which is not a random subset.
w AS (SELECT e.*, x_e8 IS NOT NULL AS common8,
             percent_rank() OVER (PARTITION BY cell, tbk, tgt, lab, (ret IS NULL)
                                  ORDER BY ret) AS pr FROM e)
SELECT cell, tbk, tgt, lab, CAST(ld AS varchar) AS ld, common8,
       CAST(count(*) AS double) AS n,
       CAST(count_if(xe IS NULL) AS double) AS n_nofill,
       approx_percentile(fill_ratio, 0.10) AS fr10,
       approx_percentile(fill_ratio, 0.50) AS fr50,
       approx_percentile(fill_ratio, 0.90) AS fr90,
       sum(ret) AS s_ret, avg(ret) AS mean_ret,
       avg(if(pr < 0.99 AND ret IS NOT NULL, ret)) AS trim01,
       avg(if(pr < 0.95 AND ret IS NOT NULL, ret)) AS trim05,
       avg(if(pr < 0.90 AND ret IS NOT NULL, ret)) AS trim10,
       CAST(count_if(ret > 0) AS double)/nullif(count_if(xe IS NOT NULL), 0) AS pos
FROM w
GROUP BY GROUPING SETS ((cell, tbk, tgt, lab), (cell, tbk, tgt, lab, ld),
                        (cell, tbk, tgt, lab, common8))
ORDER BY cell, tbk, tgt, lab, ld
