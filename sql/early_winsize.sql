-- Early identification: signal at T seconds, distribution vs growth.
-- {{T}} is substituted per observation point.
--
-- CHEAPENING (2026-08-21), all three applied:
--   (a) prior_count DROPPED -- AUC 0.4296/0.4977 and its CTE joined the 21M-row
--       createevent table, which was the single most expensive part.
--   (b) token-level facts come from the MATERIALIZED VIEW
--       dune.quantbino1695.result_flow_token_base (built once, 2.711 cr), so
--       each point reads them instead of rescanning 98 days of tradeevent.
--   (c) AUC now uses MID-RANKS.  `rank()` gives tied values the minimum rank,
--       which Mann-Whitney does not allow; with ~4.5 holders at 30s, top10 is
--       1.0 for most tokens and the ties dominated.  mid_rank = rank +
--       (tie_count - 1)/2.
--
-- NO LOOKAHEAD: every feature is built from `early`, filtered to
-- `evt_block_time <= launch_time + {{T}} seconds`.  The matview columns used as
-- LABELS (max_x, t_60, t_115) look past T by construction -- that is the target,
-- not a feature -- and `late60`/`late115` only mark tokens already across.
WITH base AS (
    SELECT token_mint, launch_time, creator, max_x, t_60, t_115
    FROM dune.quantbino1695.result_flow_token_base
),
early AS (
    SELECT t.mint, t.user, t.is_buy, b.creator,
           CAST(t.sol_amount AS bigint) AS lam,
           CAST(t.virtual_sol_reserves AS bigint) AS vsol,
           if(t.is_buy, CAST(t.token_amount AS bigint), -CAST(t.token_amount AS bigint)) AS du
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-05-19'
      AND t.evt_block_time >= b.launch_time
      AND t.evt_block_time <= b.launch_time + INTERVAL '{{T}}' SECOND
),
hold AS (SELECT mint, user, max(creator) AS creator, sum(du) AS u FROM early GROUP BY mint, user),
hrank AS (
    SELECT mint, user, creator, CAST(u AS double) AS u,
           row_number() OVER (PARTITION BY mint ORDER BY u DESC) AS rk_d,
           row_number() OVER (PARTITION BY mint ORDER BY u ASC)  AS rk_a,
           count(*) OVER (PARTITION BY mint) AS n_h,
           sum(CAST(u AS double)) OVER (PARTITION BY mint) AS tot
    FROM hold WHERE u > 0
),
hagg AS (
    SELECT mint, max(n_h) AS n_holders, max(tot) AS tot,
           sum(u) FILTER (WHERE rk_d = 1) AS top1,
           sum(u) FILTER (WHERE rk_d <= 3) AS top3,
           sum(u) FILTER (WHERE rk_d <= 10) AS top10,
           sum(u) FILTER (WHERE user = creator) AS cre,
           sum(u*u) AS sq, sum(CAST(rk_a AS double) * u) AS wsum
    FROM hrank GROUP BY mint
),
tagg AS (
    SELECT mint, count(*) AS n_tr,
           count(DISTINCT if(is_buy, user, NULL)) AS n_buy,
           avg(CAST(lam AS double)) AS m, stddev(CAST(lam AS double)) AS sd,
           CAST(count_if(is_buy) AS double) / greatest(count_if(NOT is_buy), 1) AS bs_ratio,
           CAST(count_if(lam IN (100000000,500000000,1000000000)) AS double)/count(*) AS rnd,
           CAST(max(vsol) AS double)/1e9 - 30.0 AS xg
    FROM early GROUP BY mint
),
feat AS (
    SELECT b.token_mint AS mint, b.max_x,
           coalesce(b.max_x, 0) >= 60  AS y60,
           coalesce(b.max_x, 0) >= 115 AS y115,
           (b.t_60  IS NOT NULL AND date_diff('second', b.launch_time, b.t_60)  <= {{T}}) AS late60,
           (b.t_115 IS NOT NULL AND date_diff('second', b.launch_time, b.t_115) <= {{T}}) AS late115,
           coalesce(CAST(h.n_holders AS double), 0)              AS f_n_holders,
           if(h.tot > 0, h.sq/(h.tot*h.tot), 1.0)                AS f_hhi,
           if(h.tot > 0, h.top1/h.tot, 1.0)                      AS f_top1,
           if(h.tot > 0, h.top3/h.tot, 1.0)                      AS f_top3,
           if(h.tot > 0, h.top10/h.tot, 1.0)                     AS f_top10,
           if(h.tot > 0, coalesce(h.cre,0)/h.tot, 0.0)           AS f_creator,
           if(h.n_holders > 1 AND h.tot > 0,
              2.0*h.wsum/(h.n_holders*h.tot) - CAST(h.n_holders+1 AS double)/h.n_holders,
              0.0)                                               AS f_gini,
           coalesce(CAST(t.n_tr AS double), 0)                    AS f_n_trades,
           coalesce(CAST(t.n_buy AS double), 0)                   AS f_n_buyers,
           coalesce(if(t.m > 0, t.sd/t.m, 0.0), 0.0)              AS f_cv,
           coalesce(t.bs_ratio, 0.0)                              AS f_bs,
           coalesce(t.rnd, 0.0)                                   AS f_round,
           coalesce(t.xg, 0.0)                                    AS f_xgrowth
    FROM base b LEFT JOIN hagg h ON h.mint = b.token_mint
                LEFT JOIN tagg t ON t.mint = b.token_mint
),
d AS (
    SELECT max_x, y60,
           ntile(10) OVER (ORDER BY f_xgrowth)   AS dx,
           ntile(10) OVER (ORDER BY f_n_holders) AS dh
    FROM feat WHERE NOT late60
),
u AS (
    SELECT 'x_growth' AS name, dx AS dec, max_x, y60 FROM d
    UNION ALL SELECT 'n_holders', dh, max_x, y60 FROM d
    UNION ALL SELECT 'BASE', 0, max_x, y60 FROM d
)
SELECT name, dec, count(*) AS n,
       CAST(count_if(y60) AS double)/count(*) AS base,
       approx_percentile(max_x, 0.50) AS p50,
       approx_percentile(max_x, 0.75) AS p75,
       approx_percentile(max_x, 0.90) AS p90,
       approx_percentile(max_x, 0.95) AS p95,
       approx_percentile(max_x, 0.99) AS p99,
       max(max_x) AS mx,
       avg(max_x) AS mean_x
FROM u GROUP BY name, dec ORDER BY name, dec
