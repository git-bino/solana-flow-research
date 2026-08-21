-- 2 + CI -- pooled ('all') AUC and per-launch-day AUC in ONE pass.
-- Two rank windows, different partitions:
--   m_all : PARTITION BY name           -> pooled AUC over clean + dirty together
--   m_day : PARTITION BY uni, name, ld  -> day-level AUC for the cluster bootstrap
-- No UNION ALL.  Cluster structure: the row is a TOKEN and every token has
-- exactly one launch day, so token is NESTED in day -- a ONE-WAY launch-day
-- bootstrap on NINE clusters, run locally at 0 credit from these day sums.
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
tb AS (SELECT token_mint, date(launch_time) AS ld
       FROM dune.quantbino1695.result_flow_token_base),
j AS (
    SELECT hb.x_a, hb.t_a_s, hb.max_x_after / hb.x_a AS r, tb.ld,
           hf.f_n_holders, hf.f_gini, hf.f_top1, hf.f_top3, hf.f_creator,
           hf.f_n_trades, hf.f_n_buyers,
           CASE WHEN cu.dev < 1e-6 THEN 'clean' ELSE 'dirty' END AS uni
    FROM hb JOIN hf ON hf.token_mint = hb.token_mint
            JOIN cu ON cu.token_mint = hb.token_mint
            JOIN tb ON tb.token_mint = hb.token_mint
    WHERE cu.dev IS NOT NULL
),
long AS (
    SELECT uni, ld, r, f.name, f.val FROM j
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
    SELECT uni, ld, name, r,
           CAST(rank() OVER (PARTITION BY name ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY name, val) AS double) - 1)/2.0 AS m_all,
           CAST(rank() OVER (PARTITION BY uni, name, ld ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY uni, name, ld, val) AS double) - 1)/2.0 AS m_day
    FROM long
)
SELECT uni, name, CAST(ld AS varchar) AS ld, CAST(count(*) AS double) AS n,
       CAST(count_if(r >= 1.76) AS double) AS y176,
       sum(if(r >= 1.76, m_all)) AS s_all,
       sum(if(r >= 1.76, m_day)) AS s_day,
       CAST(count_if(r >= 1.50) AS double) AS y150,
       sum(if(r >= 1.50, m_all)) AS s150_all
FROM mr
GROUP BY GROUPING SETS ((name), (uni, name, ld))
ORDER BY name, uni, ld
