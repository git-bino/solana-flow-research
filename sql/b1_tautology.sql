-- 1 + 3 -- is B1_wr_med a restatement of the entry price, and which features
-- are price-independent?
--
-- CLEAN universe only (max|x*y/k0 - 1| < 1e-6), H20 anchor, x_a = the reserve
-- AFTER the anchor event, target = x >= 60 reached after the anchor.
--
-- THE TWO REPEATED DEFECTS ARE HANDLED EXPLICITLY:
--   * `rank()` ranks NULL-valued rows (Trino puts them last), so every feature
--     is ranked ONLY after `WHERE val IS NOT NULL`.  x_a is RE-RANKED inside the
--     same non-null subset (`mx` is partitioned by feat), because a Spearman on
--     a subset needs both variables ranked on that subset.
--   * `GROUPING SETS` rows are disambiguated with `grouping(feat, grp)` emitted
--     as `gset`, never by "which column is NULL".
--
-- ONE UNNEST, THEN windows -- not UNNEST on top of a windowed CTE, which is the
-- shape that produced the 684,531-row blow-up.  Row budget: 25,353 x 10
-- features = 253,530 rows before the NULL filter.
--
-- SPEARMAN is Pearson on mid-ranks, so corr(m, mx) is Spearman with the usual
-- tie correction.
--
-- PRICE GAIN to 60 is (60/x_a)^2 - 1 because P = x^2/k.  It is a PRICE ratio
-- only: no fee, no slippage, no fixed_cost_per_leg.
WITH p AS (
    SELECT token_mint, ld, x_a, win, min_x_win, t_a_s
    FROM dune.quantbino1695.result_flow_pd
),
b AS (
    SELECT p.token_mint, p.ld, p.x_a, p.win, p.min_x_win, p.t_a_s,
           if(p.x_a > 30.0, a.sol_in / (p.x_a - 30.0)) AS r1,
           w.m_hold_s, w.m_still, w.m_ratio,
           h.wr_med, h.wr_p90, h.n_wr20,
           a.t10_20, CAST(a.f_n_trades AS double) AS n_tr
    FROM p LEFT JOIN dune.quantbino1695.result_flow_wanch  a ON a.token_mint = p.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_wbeh   w ON w.token_mint = p.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_pdhist h ON h.token_mint = p.token_mint
),
long AS (
    SELECT ld, x_a, win, min_x_win, u.feat, u.val
    FROM b CROSS JOIN UNNEST(ARRAY[
        ROW('R1_share_20',  r1),       ROW('C1_hold_s',   m_hold_s),
        ROW('C2_still',     m_still),  ROW('C5_ratio',    m_ratio),
        ROW('B1_wr_med',    wr_med),   ROW('B2_wr_p90',   wr_p90),
        ROW('B3_n_wr20',    n_wr20),   ROW('D3_t10_20',   t10_20),
        ROW('D4_n_trades',  n_tr),     ROW('A1_t_anchor', t_a_s)
    ]) AS u(feat, val)
    WHERE u.val IS NOT NULL
),
rk AS (
    SELECT feat, ld, win, x_a, min_x_win, val,
           CAST(rank() OVER (PARTITION BY feat ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY feat, val) AS double) - 1)/2.0 AS m,
           CAST(rank() OVER (PARTITION BY feat ORDER BY x_a) AS double)
             + (CAST(count(*) OVER (PARTITION BY feat, x_a) AS double) - 1)/2.0 AS mx,
           CAST(count(*) OVER (PARTITION BY feat) AS double) AS nf
    FROM long
),
g AS (SELECT rk.*, least(5, greatest(1, CAST(ceil(5.0*m/nf) AS integer))) AS grp FROM rk)
SELECT feat, grp,
       CAST(grouping(feat, grp) AS integer)                     AS gset,
       CAST(count(*) AS double)                                 AS n,
       CAST(count_if(win) AS double)/count(*)                    AS s60,
       corr(m, mx)                                               AS spearman,
       approx_percentile(val, 0.50)                              AS v50,
       approx_percentile(x_a, 0.25)                              AS xa25,
       approx_percentile(x_a, 0.50)                              AS xa50,
       approx_percentile(x_a, 0.75)                              AS xa75,
       approx_percentile(power(60.0 / x_a, 2) - 1.0, 0.50)        AS gain50,
       approx_percentile(if(NOT win, min_x_win / x_a), 0.50)      AS l50,
       (sum(if(win, m, 0.0)) - CAST(count_if(win) AS double)*(CAST(count_if(win) AS double)+1)/2.0)
         / nullif(CAST(count_if(win) AS double)*CAST(count_if(NOT win) AS double),0) AS auc
FROM g GROUP BY GROUPING SETS ((feat), (feat, grp)) ORDER BY feat, grp
