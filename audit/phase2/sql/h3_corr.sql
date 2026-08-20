-- 1 -- Are `gini` and `creator_share` the same thing at the holder anchor?
--
-- COST SHAPE (the reason this looks the way it does).  The previous run's `cond`
-- query cost 60.697 cr: it defined a CTE containing a JOIN plus two `ntile()`
-- windows and then referenced that CTE in FOUR `UNION ALL` branches.  A CTE in
-- Dune SQL is not materialised, so the join and both windows were recomputed per
-- branch.  Here the source is scanned ONCE and every level of detail comes from
-- a single `GROUPING SETS` aggregation.  (That the 4x re-execution is the exact
-- cause is not proven -- it was not re-run to test it -- but the fix removes the
-- pattern either way.)
--
-- SPEARMAN uses MID-RANKS.  `rank()` gives ties the minimum rank; with 3 holders
-- at H3 both features have heavy ties, and min-ranks would bias the correlation.
--   mid_rank = rank() + (tie_count - 1) / 2
-- Spearman rho is then Pearson's `corr` of the two mid-rank columns.
--
-- TERTILES come from the mid-rank, not from `ntile()`: ntile is a second window
-- and splits ties arbitrarily between groups.
WITH hf AS (
    SELECT token_mint, anchor_kind, f_gini, f_creator, f_n_holders
    FROM dune.quantbino1695.result_flow_hfeat_a
    WHERE anchor_kind IN ('H3')
    UNION ALL
    SELECT token_mint, anchor_kind, f_gini, f_creator, f_n_holders
    FROM dune.quantbino1695.result_flow_hfeat_b
    WHERE anchor_kind IN ('H10', 'H20')
),
r AS (
    SELECT anchor_kind, f_gini, f_creator,
           CAST(rank() OVER (PARTITION BY anchor_kind ORDER BY f_gini) AS double)
             + (CAST(count(*) OVER (PARTITION BY anchor_kind, f_gini) AS double) - 1)/2.0 AS mg,
           CAST(rank() OVER (PARTITION BY anchor_kind ORDER BY f_creator) AS double)
             + (CAST(count(*) OVER (PARTITION BY anchor_kind, f_creator) AS double) - 1)/2.0 AS mc,
           CAST(count(*) OVER (PARTITION BY anchor_kind) AS double) AS n_tot
    FROM hf
),
t AS (
    SELECT anchor_kind, f_gini, f_creator, mg, mc, n_tot,
           least(3, greatest(1, CAST(ceil(3.0 * mg / n_tot) AS integer))) AS g3,
           least(3, greatest(1, CAST(ceil(3.0 * mc / n_tot) AS integer))) AS c3
    FROM r
)
SELECT anchor_kind, g3, c3,
       CAST(count(*) AS double) AS n,
       corr(mg, mc)                    AS spearman,
       approx_percentile(f_gini, 0.50) AS gini_p50,
       approx_percentile(f_creator, 0.50) AS cre_p50,
       min(f_gini) AS gini_min, max(f_gini) AS gini_max,
       min(f_creator) AS cre_min, max(f_creator) AS cre_max
FROM t
GROUP BY GROUPING SETS ((anchor_kind), (anchor_kind, g3), (anchor_kind, c3),
                        (anchor_kind, g3, c3))
ORDER BY anchor_kind, g3, c3
