-- Audit 3, defect 1 -- MAYHEM ATTRIBUTION.
--
-- WHY THIS EXISTS.  `sql/h3_mayhem_probe.sql` checked only
-- `pump_evt_updatemayhemvirtualparamsevent`, found 0 cohort tokens, and the
-- `P ∝ x²` precondition was recorded as satisfied on that basis.  That table
-- records PARAMETER REWRITES.  Mayhem is set at LAUNCH -- `createevent.
-- is_mayhem_mode` -- and carried on every trade as `tradeevent.mayhem_mode`.
-- The earlier probe therefore could not have detected launch-time mayhem at all.
--
-- The flag used here is `bool_or(is_mayhem_mode)` from createevent over the
-- launch window, i.e. mayhem AT LAUNCH.  The tradeevent-side flag needs a 98-day
-- scan and is measured separately in sql/mayhem_xy_drift.sql.
--
-- P&L is the frozen rule's realistic variant: entry 3 trade events after the
-- anchor, exit 3 trade events after the target crossing, no stop, q = 1,
-- fee 1.25% per side, cost_model's exact path.
WITH ce AS (
    SELECT mint, bool_or(is_mayhem_mode) AS mayhem_launch
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
tb AS (SELECT token_mint FROM dune.quantbino1695.result_flow_token_base),
coh AS (
    SELECT tb.token_mint, coalesce(ce.mayhem_launch, false) AS mh
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
           hf.f_gini, hf.f_creator, coh.mh
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
    SELECT cell, tbk, mh, x_e3 AS x_in, u.tgt, u.x_out, u.hit
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
    SELECT e.*, percent_rank() OVER (PARTITION BY cell, tbk, tgt, (ret IS NULL)
                                     ORDER BY ret DESC) AS pr_desc
    FROM e
)
-- (a) cohort-wide launch mayhem
SELECT 'cohort' AS scope, '-' AS cell, '-' AS tbk, '-' AS tgt,
       CAST(count(*) AS double) AS n,
       CAST(count_if(mh) AS double) AS n_mayhem,
       CAST(count_if(mh) AS double)/count(*) AS share_mayhem,
       NULL AS pnl_all, NULL AS pnl_mayhem
FROM coh
UNION ALL
-- (b) mayhem share in the four executable cells, and (g) P&L attribution
SELECT 'cell', cell, tbk, tgt,
       CAST(count(*) AS double), CAST(count_if(mh) AS double),
       CAST(count_if(mh) AS double)/count(*),
       sum(ret), sum(if(mh, ret))
FROM w GROUP BY cell, tbk, tgt
UNION ALL
-- (c) mayhem share of the top 1 / 5 / 10 percent of P&L
SELECT 'top01', cell, tbk, tgt,
       CAST(count_if(pr_desc < 0.01 AND ret IS NOT NULL) AS double),
       CAST(count_if(pr_desc < 0.01 AND ret IS NOT NULL AND mh) AS double),
       CAST(count_if(pr_desc < 0.01 AND ret IS NOT NULL AND mh) AS double)
         / nullif(count_if(pr_desc < 0.01 AND ret IS NOT NULL), 0),
       sum(if(pr_desc < 0.01, ret)), sum(if(pr_desc < 0.01 AND mh, ret))
FROM w GROUP BY cell, tbk, tgt
UNION ALL
SELECT 'top05', cell, tbk, tgt,
       CAST(count_if(pr_desc < 0.05 AND ret IS NOT NULL) AS double),
       CAST(count_if(pr_desc < 0.05 AND ret IS NOT NULL AND mh) AS double),
       CAST(count_if(pr_desc < 0.05 AND ret IS NOT NULL AND mh) AS double)
         / nullif(count_if(pr_desc < 0.05 AND ret IS NOT NULL), 0),
       sum(if(pr_desc < 0.05, ret)), sum(if(pr_desc < 0.05 AND mh, ret))
FROM w GROUP BY cell, tbk, tgt
UNION ALL
SELECT 'top10', cell, tbk, tgt,
       CAST(count_if(pr_desc < 0.10 AND ret IS NOT NULL) AS double),
       CAST(count_if(pr_desc < 0.10 AND ret IS NOT NULL AND mh) AS double),
       CAST(count_if(pr_desc < 0.10 AND ret IS NOT NULL AND mh) AS double)
         / nullif(count_if(pr_desc < 0.10 AND ret IS NOT NULL), 0),
       sum(if(pr_desc < 0.10, ret)), sum(if(pr_desc < 0.10 AND mh, ret))
FROM w GROUP BY cell, tbk, tgt
ORDER BY scope, cell, tbk, tgt
