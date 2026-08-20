-- Audit 3, defect 1 (part 2) -- every headline number recomputed WITH and
-- WITHOUT launch-time mayhem, side by side, plus per-launch-day sums for the
-- one-way cluster bootstrap (token is nested in day; 9 clusters).
-- `mh` = mayhem at launch (createevent.is_mayhem_mode).
WITH ce AS (
    SELECT mint, bool_or(is_mayhem_mode) AS mayhem_launch
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
tb AS (SELECT token_mint, date(launch_time) AS ld FROM dune.quantbino1695.result_flow_token_base),
coh AS (
    SELECT tb.token_mint, tb.ld, coalesce(ce.mayhem_launch, false) AS mh
    FROM tb LEFT JOIN ce ON ce.mint = tb.token_mint
),
gi AS (SELECT token_mint, x_a, t_a_s, x_e3, final_x, seq_u76, seq_u35
       FROM dune.quantbino1695.result_flow_gapin),
go AS (SELECT token_mint, x76_e3, x35_e3 FROM dune.quantbino1695.result_flow_gapout),
hb AS (SELECT token_mint, x_u76, x_u35 FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_gini, f_creator
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
j AS (
    SELECT gi.*, go.x76_e3, go.x35_e3, hb.x_u76, hb.x_u35,
           hf.f_gini, hf.f_creator, coh.mh, coh.ld
    FROM gi JOIN hf ON hf.token_mint = gi.token_mint
            JOIN hb ON hb.token_mint = gi.token_mint
            JOIN coh ON coh.token_mint = gi.token_mint
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
    SELECT cell, tbk, mh, ld, x_e3 AS x_in, u.tgt, u.x_out, u.hit
    FROM cellrows CROSS JOIN UNNEST(ARRAY[
        ROW('+76%',  CASE WHEN x_u76 IS NULL THEN final_x
                          ELSE coalesce(x76_e3, final_x) END, seq_u76 IS NOT NULL),
        ROW('+135%', CASE WHEN x_u35 IS NULL THEN final_x
                          ELSE coalesce(x35_e3, final_x) END, seq_u35 IS NOT NULL)
    ]) AS u(tgt, x_out, hit)
),
e AS (
    SELECT v.*, CASE WHEN x_in IS NULL THEN NULL ELSE ((((32190000000.0 * 1.0 / (x_in * (x_in + 1.0))) * (x_out + 1.0) * (x_out + 1.0) / (32190000000.0 + (32190000000.0 * 1.0 / (x_in * (x_in + 1.0))) * (x_out + 1.0))) * (1 - 0.0125) - 1.0 / (1 - 0.0125)) / 1.0) END AS ret
    FROM v
),
w AS (
    SELECT e.*, percent_rank() OVER (PARTITION BY cell, tbk, tgt, mh, (ret IS NULL)
                                     ORDER BY ret) AS pr
    FROM e
)
SELECT cell, tbk, tgt, mh, CAST(ld AS varchar) AS ld,
       CAST(count(*) AS double) AS n,
       CAST(count_if(x_in IS NULL) AS double) AS n_nofill,
       sum(ret) AS s_ret, avg(ret) AS mean_ret,
       approx_percentile(ret, 0.50) AS median_ret,
       avg(if(pr < 0.99 AND ret IS NOT NULL, ret)) AS trim01,
       avg(if(pr < 0.95 AND ret IS NOT NULL, ret)) AS trim05,
       avg(if(pr < 0.90 AND ret IS NOT NULL, ret)) AS trim10,
       CAST(count_if(hit) AS double)/count(*) AS share_hit,
       CAST(count_if(ret > 0) AS double)/nullif(count_if(x_in IS NOT NULL),0) AS pos
FROM w
GROUP BY GROUPING SETS ((cell, tbk, tgt, mh), (cell, tbk, tgt, mh, ld))
ORDER BY cell, tbk, tgt, mh, ld
