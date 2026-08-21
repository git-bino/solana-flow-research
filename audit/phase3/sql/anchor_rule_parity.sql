-- 1 + 3 -- numerical parity for src/anchor_rule.py, and the EXACT proportional
-- return at each q.
--
-- WHAT THIS CHECKS AND WHAT IT DOES NOT.  It rebuilds the selection, the exit
-- fallback and the pricing from the stored matviews and lands them against the
-- figure `sql/execution_gap_agg.sql` produced.  It does NOT re-detect the anchor
-- or re-extract the delayed fills -- those live in result_flow_holder_anchor /
-- gapin / gapout and re-deriving them would need the 24.466 cr running-holder
-- pass.  The scope is stated rather than implied.
--
-- The slippage is written in the OTHER algebraic form on purpose:
--     dy = k/x1 - k/(x1+q)        (here)
--     dy = k*q / (x1*(x1+q))      (execution_gap_agg.sql, anchor_rule.py)
-- Identical by algebra; if the two agree to 1e-9 the agreement is not a copy.
--
-- TERTILE POPULATION must match execution_gap_agg.sql exactly or `n` will not:
-- there the mid-rank ran over gapin INNER JOIN hfeat INNER JOIN hbar INNER JOIN
-- token_base, before any cell filter.  Same here.
--
-- CELL: gini tertile 1, t_a_s in [3, 10).  ENTRY: x_e3.  EXIT: the +76% crossing
-- three trades later, else the observed final_x.  No stop.
WITH gi AS (
    SELECT token_mint, x_a, t_a_s, x_e3, final_x, seq_u76, seq_u35
    FROM dune.quantbino1695.result_flow_gapin
),
go AS (SELECT token_mint, x76_e3, x35_e3 FROM dune.quantbino1695.result_flow_gapout),
hb AS (SELECT token_mint, x_u76, x_u35 FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_gini, f_creator
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
tb AS (SELECT token_mint FROM dune.quantbino1695.result_flow_token_base),
j AS (
    SELECT gi.token_mint, gi.x_a, gi.t_a_s, gi.x_e3, gi.final_x,
           gi.seq_u76, gi.seq_u35, go.x76_e3, go.x35_e3, hb.x_u76, hb.x_u35,
           hf.f_gini, hf.f_creator
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
lab AS (
    SELECT rk.*,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3,
           CASE WHEN t_a_s < 3 THEN 'x' WHEN t_a_s < 10 THEN '3_3to10s'
                ELSE '4_gt10s' END AS tbk
    FROM rk
),
cellrows AS (
    SELECT lab.*, cc.cell FROM lab CROSS JOIN UNNEST(ARRAY[
        ROW('gini g1', g3), ROW('creator c1', c3)]) AS cc(cell, tv)
    WHERE cc.tv = 1 AND lab.tbk <> 'x'
),
v AS (
    SELECT cell, tbk, x_a, x_e3 AS x_in, u.tgt, u.x_out, u.hit_target
    FROM cellrows CROSS JOIN UNNEST(ARRAY[
        ROW('+76%',  CASE WHEN x_u76 IS NULL THEN final_x
                          ELSE coalesce(x76_e3, final_x) END, seq_u76 IS NOT NULL),
        ROW('+135%', CASE WHEN x_u35 IS NULL THEN final_x
                          ELSE coalesce(x35_e3, final_x) END, seq_u35 IS NOT NULL)
    ]) AS u(tgt, x_out, hit_target)
),
qq AS (SELECT * FROM UNNEST(ARRAY[0.05, 0.1, 0.5, 1.0, 2.0, 5.0]) AS t(q)),
e AS (
    SELECT v.cell, v.tbk, v.tgt, qq.q, v.hit_target, v.x_in,
           CASE WHEN v.x_in IS NULL THEN NULL ELSE
             ((32190000000.0 / v.x_in - 32190000000.0 / (v.x_in + qq.q))
                * (v.x_out + qq.q) * (v.x_out + qq.q)
                / (32190000000.0
                   + (32190000000.0 / v.x_in - 32190000000.0 / (v.x_in + qq.q))
                     * (v.x_out + qq.q))
              * (1 - 0.0125) - qq.q / (1 - 0.0125)) / qq.q END AS ret
    FROM v CROSS JOIN qq
),
w AS (SELECT e.*, percent_rank() OVER (PARTITION BY cell, tbk, tgt, q, (ret IS NULL)
                                       ORDER BY ret) AS pr FROM e)
SELECT cell, tbk, tgt, q,
       CAST(count(*) AS double) AS n,
       CAST(count_if(x_in IS NULL) AS double) AS n_nofill,
       avg(ret) AS mean_ret,
       approx_percentile(ret, 0.50) AS median_ret,
       CAST(count_if(hit_target) AS double)/count(*) AS share_hit,
       CAST(count_if(NOT hit_target) AS double)/count(*) AS share_censored,
       CAST(count_if(ret > 0) AS double)/nullif(count_if(x_in IS NOT NULL), 0) AS pos,
       avg(if(pr < 0.95 AND ret IS NOT NULL, ret)) AS trim05
FROM w
GROUP BY cell, tbk, tgt, q
ORDER BY cell, tbk, tgt, q
