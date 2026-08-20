-- 2 + 3 (+ 1's conditional cells) -- ONE pass, one source read, no `ntile`.
--
-- Everything §1в/§2/§3 needs comes out of a single `GROUPING SETS` aggregation
-- over one join.  The previous `cond` query cost 60.697 cr by referencing a
-- join-plus-two-`ntile()` CTE in four UNION branches; nothing here is referenced
-- more than once and there is no `ntile`.
--
-- TERTILES from MID-RANKS, cut inside each anchor, so ties (heavy at H3, where
-- there are only 3 holders) are not split arbitrarily between groups.
--
-- FIRST PASSAGE is decided on SLOT, as before.  The four outcomes are exclusive
-- and exhaustive by construction: win, loss, same_slot, censored.
--   win   = target slot exists and (no stop slot, or target slot < stop slot)
--   loss  = stop   slot exists and (no target slot, or stop slot < target slot)
--   same  = both exist and are equal          -- counted, never tie-broken
--   cens  = neither exists inside the event window
-- CENSORED IS NEVER REPLACED by zero or by a finite value.  The censored group's
-- `final_x / x_a` is reported so where those tokens ended is visible.
--
-- TIME BUCKETS on `t_a_s`, the anchor's seconds since launch: <1, 1-3, 3-10, >10.
WITH hp AS (
    SELECT token_mint, anchor_kind, x_a, t_a_s, final_x,
           sl_g20, sl_g36, sl_l20, sl_l30
    FROM dune.quantbino1695.result_flow_hpath_a WHERE anchor_kind = 'H3'
    UNION ALL
    SELECT token_mint, anchor_kind, x_a, t_a_s, final_x,
           sl_g20, sl_g36, sl_l20, sl_l30
    FROM dune.quantbino1695.result_flow_hpath_b WHERE anchor_kind IN ('H10','H20')
),
hf AS (
    SELECT token_mint, anchor_kind, f_gini, f_creator
    FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'
    UNION ALL
    SELECT token_mint, anchor_kind, f_gini, f_creator
    FROM dune.quantbino1695.result_flow_hfeat_b WHERE anchor_kind IN ('H10','H20')
),
j AS (
    SELECT p.anchor_kind, p.x_a, p.t_a_s, p.final_x,
           p.sl_g20, p.sl_g36, p.sl_l20, p.sl_l30,
           f.f_gini, f.f_creator
    FROM hp p JOIN hf f ON f.token_mint = p.token_mint
                       AND f.anchor_kind = p.anchor_kind
),
r AS (
    SELECT j.*,
           CAST(rank() OVER (PARTITION BY anchor_kind ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY anchor_kind, f_gini) AS double) - 1)/2.0 AS mg,
           CAST(rank() OVER (PARTITION BY anchor_kind ORDER BY f_creator) AS double)
             + (CAST(count(*) OVER (PARTITION BY anchor_kind, f_creator) AS double) - 1)/2.0 AS mc,
           CAST(count(*) OVER (PARTITION BY anchor_kind) AS double) AS n_tot
    FROM j
),
c AS (
    SELECT anchor_kind, x_a, t_a_s, final_x / x_a AS fr,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3,
           CASE WHEN t_a_s < 1 THEN '1_lt1s' WHEN t_a_s < 3 THEN '2_1to3s'
                WHEN t_a_s < 10 THEN '3_3to10s' ELSE '4_gt10s' END AS tb,
           (sl_g20 IS NOT NULL AND (sl_l20 IS NULL OR sl_g20 < sl_l20)) AS w20,
           (sl_l20 IS NOT NULL AND (sl_g20 IS NULL OR sl_l20 < sl_g20)) AS l20,
           (sl_g20 IS NOT NULL AND sl_l20 IS NOT NULL AND sl_g20 = sl_l20) AS s20,
           (sl_g20 IS NULL AND sl_l20 IS NULL) AS x20,
           (sl_g36 IS NOT NULL AND (sl_l30 IS NULL OR sl_g36 < sl_l30)) AS w36,
           (sl_l30 IS NOT NULL AND (sl_g36 IS NULL OR sl_l30 < sl_g36)) AS l36,
           (sl_g36 IS NOT NULL AND sl_l30 IS NOT NULL AND sl_g36 = sl_l30) AS s36,
           (sl_g36 IS NULL AND sl_l30 IS NULL) AS x36
    FROM r
)
SELECT anchor_kind, g3, c3, tb,
       CAST(count(*) AS double) AS n,
       CAST(count_if(w20) AS double) AS w20, CAST(count_if(l20) AS double) AS l20,
       CAST(count_if(s20) AS double) AS s20, CAST(count_if(x20) AS double) AS x20,
       CAST(count_if(w36) AS double) AS w36, CAST(count_if(l36) AS double) AS l36,
       CAST(count_if(s36) AS double) AS s36, CAST(count_if(x36) AS double) AS x36,
       approx_percentile(x_a, 0.50)   AS x_a_p50,
       approx_percentile(t_a_s, 0.50) AS t_a_p50,
       -- where the CENSORED (+20/-20) tokens ended, relative to the anchor
       approx_percentile(if(x20, fr), 0.10) AS cfr_p10,
       approx_percentile(if(x20, fr), 0.25) AS cfr_p25,
       approx_percentile(if(x20, fr), 0.50) AS cfr_p50,
       approx_percentile(if(x20, fr), 0.75) AS cfr_p75,
       approx_percentile(if(x20, fr), 0.90) AS cfr_p90,
       approx_percentile(fr, 0.50)          AS fr_p50
FROM c
GROUP BY GROUPING SETS (
    (anchor_kind),
    (anchor_kind, g3),
    (anchor_kind, c3),
    (anchor_kind, c3, g3),
    (anchor_kind, tb),
    (anchor_kind, tb, g3)
)
ORDER BY anchor_kind, tb, c3, g3
