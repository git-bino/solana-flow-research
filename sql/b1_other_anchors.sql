-- 3 -- the same filter at H10 and H15, from existing matviews only.
-- `win` at an anchor = x >= 60 reached AFTER that anchor
-- (result_flow_hpath_b.sl_60 IS NOT NULL), the same definition used at H20.
-- B1 quintiles are the GLOBAL H20-derived quintiles of the LOOKAHEAD-FREE
-- wr_med (result_flow_pdhist2); the token set is the one that has the anchor.
-- Ranks are taken only after `WHERE ... IS NOT NULL`; grouping() is emitted.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
h AS (
    SELECT token_mint, wr_med, wr_p90 FROM dune.quantbino1695.result_flow_pdhist2
    WHERE wr_med IS NOT NULL AND wr_p90 IS NOT NULL
),
r AS (
    SELECT token_mint,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double)-1)/2.0 AS mb,
           CAST(rank() OVER (ORDER BY wr_p90) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_p90) AS double)-1)/2.0 AS m2,
           CAST(count(*) OVER () AS double) AS nn, wr_med
    FROM h
),
fl AS (
    SELECT token_mint, wr_med,
           least(5,greatest(1,CAST(ceil(5.0*mb/nn) AS integer))) AS qb,
           ceil(5.0*mb/nn) >= 5 AND ceil(5.0*m2/nn) >= 5 AS f2
    FROM r
),
a AS (
    SELECT p.token_mint, p.anchor_kind, p.x_a, p.sl_60 IS NOT NULL AS win
    FROM dune.quantbino1695.result_flow_hpath_b p
    JOIN coh c ON c.token_mint = p.token_mint
    WHERE p.anchor_kind IN ('H10','H15','H20') AND p.x_a IS NOT NULL
),
b AS (
    SELECT a.anchor_kind, a.x_a, a.win, fl.wr_med, fl.qb, fl.f2
    FROM a JOIN fl ON fl.token_mint = a.token_mint
),
rk AS (
    SELECT b.*,
           CAST(rank() OVER (PARTITION BY anchor_kind ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY anchor_kind, wr_med) AS double)-1)/2.0 AS m,
           CAST(rank() OVER (PARTITION BY anchor_kind ORDER BY x_a) AS double)
             + (CAST(count(*) OVER (PARTITION BY anchor_kind, x_a) AS double)-1)/2.0 AS mx,
           CAST(count(*) OVER (PARTITION BY anchor_kind) AS double) AS nf
    FROM b
),
g AS (
    SELECT rk.*, least(5,greatest(1,CAST(ceil(5.0*mx/nf) AS integer))) AS qx,
           least(5,greatest(1,CAST(ceil(5.0*m/nf)  AS integer))) AS qba
    FROM rk
)
SELECT anchor_kind, qx, qba, f2,
       CAST(grouping(anchor_kind, qx, qba, f2) AS integer) AS gset,
       CAST(count(*) AS double) AS n,
       CAST(count_if(win) AS double)/count(*) AS s60,
       approx_percentile(x_a, 0.50) AS xa50,
       (sum(if(win, m, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double),0) AS auc_b1
FROM g
GROUP BY GROUPING SETS ((anchor_kind), (anchor_kind, qx), (anchor_kind, qba),
                        (anchor_kind, qx, qba), (anchor_kind, f2))
ORDER BY anchor_kind, qx, qba
