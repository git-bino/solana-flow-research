-- 4 -- first-passage win rate CONDITIONED on the anchor-moment distribution.
--
-- Anchor H3: the widest coverage of the six (153,027 rows in the path matview).
-- Tokens are cut into TERTILES of `gini` and, separately, of `creator_share`,
-- both measured AT the anchor, so the grouping uses no information from after it.
WITH hp AS (SELECT * FROM dune.quantbino1695.result_flow_hpath_a WHERE anchor_kind = 'H3'),
hf AS (SELECT * FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
j AS (
    SELECT p.token_mint, p.sl_g20, p.sl_g36, p.sl_l20, p.sl_l30, p.sl_l50,
           f.f_gini, f.f_creator,
           ntile(3) OVER (ORDER BY f.f_gini)    AS g3,
           ntile(3) OVER (ORDER BY f.f_creator) AS c3
    FROM hp p JOIN hf f ON f.token_mint = p.token_mint
)
SELECT 'gini' AS split_by, g3 AS grp, '+20%' AS target, '-20%' AS stop,
       CAST(count(*) AS double) AS n,
       approx_percentile(f_gini, 0.5) AS grp_median,
       CAST(count_if(sl_g20 IS NOT NULL AND (sl_l20 IS NULL OR sl_g20 < sl_l20)) AS double)/count(*) AS win,
       CAST(count_if(sl_l20 IS NOT NULL AND (sl_g20 IS NULL OR sl_l20 < sl_g20)) AS double)/count(*) AS loss,
       CAST(count_if(sl_g20 IS NULL AND sl_l20 IS NULL) AS double)/count(*) AS censored
FROM j GROUP BY g3
UNION ALL
SELECT 'gini', g3, '+36%', '-30%', CAST(count(*) AS double),
       approx_percentile(f_gini, 0.5),
       CAST(count_if(sl_g36 IS NOT NULL AND (sl_l30 IS NULL OR sl_g36 < sl_l30)) AS double)/count(*),
       CAST(count_if(sl_l30 IS NOT NULL AND (sl_g36 IS NULL OR sl_l30 < sl_g36)) AS double)/count(*),
       CAST(count_if(sl_g36 IS NULL AND sl_l30 IS NULL) AS double)/count(*)
FROM j GROUP BY g3
UNION ALL
SELECT 'creator_share', c3, '+20%', '-20%', CAST(count(*) AS double),
       approx_percentile(f_creator, 0.5),
       CAST(count_if(sl_g20 IS NOT NULL AND (sl_l20 IS NULL OR sl_g20 < sl_l20)) AS double)/count(*),
       CAST(count_if(sl_l20 IS NOT NULL AND (sl_g20 IS NULL OR sl_l20 < sl_g20)) AS double)/count(*),
       CAST(count_if(sl_g20 IS NULL AND sl_l20 IS NULL) AS double)/count(*)
FROM j GROUP BY c3
UNION ALL
SELECT 'creator_share', c3, '+36%', '-30%', CAST(count(*) AS double),
       approx_percentile(f_creator, 0.5),
       CAST(count_if(sl_g36 IS NOT NULL AND (sl_l30 IS NULL OR sl_g36 < sl_l30)) AS double)/count(*),
       CAST(count_if(sl_l30 IS NOT NULL AND (sl_g36 IS NULL OR sl_l30 < sl_g36)) AS double)/count(*),
       CAST(count_if(sl_g36 IS NULL AND sl_l30 IS NULL) AS double)/count(*)
FROM j GROUP BY c3
ORDER BY split_by, target, grp
