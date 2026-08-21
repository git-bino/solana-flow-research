-- 3 -- distribution AT the H10 anchor -> fate, clean universe.
--
-- SUBSTITUTION, stated.  The brief asks for the distribution AT THE PEAK holder
-- count.  The peak is not available (see sql/holder_growth.sql).  The moment the
-- holder count FIRST reaches 10 is available and is used instead -- it is also
-- the stricter choice, since it is known at that moment rather than in hindsight.
-- Tokens with an H10 anchor: the 4_10to14, 5_15to19 and 6_20plus bins.
--
-- `hhi` and `top10` are NOT in result_flow_hfeat_b (it stores n_holders, gini,
-- top1, top3, creator_share, n_trades, n_buyers), so those two are NOT reported
-- rather than approximated.
--
-- Quintiles from MID-RANKS, not `ntile`.  One GROUPING SETS pass, no UNION ALL.
WITH cu AS (
    SELECT token_mint, max_x, lifetime_s, t_last,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT * FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
anch AS (
    SELECT token_mint,
           max(if(anchor_kind = 'H15', 1, 0)) AS h15,
           max(if(anchor_kind = 'H20', 1, 0)) AS h20
    FROM dune.quantbino1695.result_flow_holder_anchor GROUP BY token_mint
),
hf AS (
    SELECT token_mint, f_gini, f_top1, f_top3, f_creator
    FROM dune.quantbino1695.result_flow_hfeat_b WHERE anchor_kind = 'H10'
),
cp AS (SELECT DISTINCT mint FROM pumpdotfun_solana.pump_evt_completeevent
       WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date <= DATE '2026-08-15'),
j AS (
    SELECT c.token_mint, c.max_x, c.lifetime_s,
           hf.f_gini, hf.f_top1, hf.f_top3, hf.f_creator,
           CASE WHEN coalesce(a.h20,0) = 1 THEN '6_20plus'
                WHEN coalesce(a.h15,0) = 1 THEN '5_15to19'
                ELSE '4_10to14' END AS bin,
           (coalesce(c.max_x, 0.0) >= 115 OR cp.mint IS NOT NULL) AS migrated
    FROM coh c JOIN hf ON hf.token_mint = c.token_mint
               LEFT JOIN anch a ON a.token_mint = c.token_mint
               LEFT JOIN cp ON cp.mint = c.token_mint
),
long AS (
    SELECT j.*, f.name, f.val FROM j
    CROSS JOIN UNNEST(ARRAY[
        ROW('gini', f_gini), ROW('top1', f_top1),
        ROW('top3', f_top3), ROW('creator_share', f_creator)
    ]) AS f(name, val)
),
q AS (
    SELECT long.*,
           CAST(rank() OVER (PARTITION BY name ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY name, val) AS double) - 1)/2.0 AS m,
           CAST(count(*) OVER (PARTITION BY name) AS double) AS n_tot
    FROM long
),
g AS (SELECT q.*, least(5, greatest(1, CAST(ceil(5.0 * m / n_tot) AS integer))) AS grp FROM q)
SELECT name, grp, bin, CAST(count(*) AS double) AS n,
       approx_percentile(val, 0.50) AS grp_med,
       approx_percentile(max_x, 0.50) AS mx50,
       approx_percentile(max_x, 0.90) AS mx90,
       CAST(count_if(max_x > 60) AS double)/count(*) AS s60,
       CAST(count_if(migrated) AS double)/count(*) AS s_mig,
       approx_percentile(lifetime_s, 0.50) AS life50
FROM g
GROUP BY GROUPING SETS ((name), (name, grp), (name, grp, bin), (name, bin))
ORDER BY name, grp, bin
