-- 1 -- discrimination INSIDE the clean universe, H3 anchor.
--
-- FEATURE SET (stated, not assumed).  The brief's 12 burst features
-- (`net_flow_5slot`, `depth_x`, `oh_ratio_a`, `accel`, `burst_age_slot`, ...)
-- live in `flow.burst_v2`, which is keyed by BURST TRIGGER, not by the H3
-- anchor, is local-only, and carries no clean/dirty flag.  There is no defined
-- join from a burst trigger to an H3 anchor, so the ANCHOR-CONTEXT set named as
-- the alternative is used instead:
--     n_holders, gini, top1, top3, creator_share, n_trades, n_buyers, x_a, t_a_s
-- `x_growth` is not listed separately: it is `x_a - 30`, a strictly increasing
-- transform of `x_a`, so its AUC and its decile table are IDENTICAL.
-- All nine are known AT the anchor -- none uses an event after it.
--
-- AUC uses MID-RANKS: `rank()` gives ties the minimum rank and Mann-Whitney
-- needs the average.  Deciles come from the same mid-rank, not from `ntile`,
-- which splits ties arbitrarily between groups.
--
-- ONE window, ONE GROUPING SETS pass, NO `UNION ALL` -- a UNION ALL branch
-- re-executes the CTE it references (`cond` 60.697 cr, `clean_baselines` 3.805
-- against a 0.2 estimate).
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
hb AS (SELECT token_mint, x_a, t_a_s, max_x_after FROM dune.quantbino1695.result_flow_hbar),
hf AS (SELECT token_mint, f_n_holders, f_gini, f_top1, f_top3, f_creator,
              f_n_trades, f_n_buyers
       FROM dune.quantbino1695.result_flow_hfeat_a WHERE anchor_kind = 'H3'),
j AS (
    SELECT hb.x_a, hb.t_a_s, hb.max_x_after / hb.x_a AS r,
           hf.f_n_holders, hf.f_gini, hf.f_top1, hf.f_top3, hf.f_creator,
           hf.f_n_trades, hf.f_n_buyers,
           CASE WHEN cu.dev < 1e-6 THEN 'clean' ELSE 'dirty' END AS uni
    FROM hb JOIN hf ON hf.token_mint = hb.token_mint
            JOIN cu ON cu.token_mint = hb.token_mint
    WHERE cu.dev IS NOT NULL
),
long AS (
    SELECT uni, r, f.name, f.val FROM j
    CROSS JOIN UNNEST(ARRAY[
        ROW('n_holders', CAST(f_n_holders AS double)),
        ROW('gini', f_gini),
        ROW('top1', f_top1),
        ROW('top3', f_top3),
        ROW('creator_share', f_creator),
        ROW('n_trades', CAST(f_n_trades AS double)),
        ROW('n_buyers', CAST(f_n_buyers AS double)),
        ROW('x_a', x_a),
        ROW('t_a_s', t_a_s)
    ]) AS f(name, val)
),
mr AS (
    SELECT uni, name, r, val,
           CAST(rank() OVER (PARTITION BY uni, name ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY uni, name, val) AS double) - 1)/2.0 AS m,
           CAST(count(*) OVER (PARTITION BY uni, name) AS double) AS n_tot
    FROM long
),
d AS (
    SELECT mr.*, least(10, greatest(1, CAST(ceil(10.0 * m / n_tot) AS integer))) AS dec
    FROM mr
)
SELECT uni, name, dec, CAST(count(*) AS double) AS n,
       CAST(count_if(r >= 1.50) AS double) AS y150,
       CAST(count_if(r >= 1.76) AS double) AS y176,
       CAST(count_if(r >= 2.05) AS double) AS y205,
       sum(if(r >= 1.50, m)) AS s150,
       sum(if(r >= 1.76, m)) AS s176,
       sum(if(r >= 2.05, m)) AS s205
FROM d
GROUP BY GROUPING SETS ((uni, name), (uni, name, dec))
ORDER BY uni, name, dec
