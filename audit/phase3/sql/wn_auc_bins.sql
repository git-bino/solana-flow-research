-- 2 + 3 -- launch-day cluster bootstrap input, same construction as
-- sql/pd_auc_bins.sql: per (feature, launch day, 60 global quantile bins) the
-- winner and loser counts.  The bootstrap itself runs locally at 0 credits.
WITH p AS (SELECT token_mint, ld, win FROM dune.quantbino1695.result_flow_pd),
b AS (
    SELECT p.ld, p.win, w.m_hold_s, w.m_still, w.m_esol, w.m_rk, w.m_ratio,
           a.sol_in, a.top1_nc, a.t10_20, CAST(a.f_n_trades AS double) AS n_tr
    FROM p LEFT JOIN dune.quantbino1695.result_flow_wbeh  w ON w.token_mint = p.token_mint
           LEFT JOIN dune.quantbino1695.result_flow_wanch a ON a.token_mint = p.token_mint
),
long AS (
    SELECT ld, win, u.feat, u.val
    FROM b CROSS JOIN UNNEST(ARRAY[
        ROW(1, m_hold_s), ROW(2, m_still), ROW(3, m_esol), ROW(4, m_rk), ROW(5, m_ratio),
        ROW(6, sol_in),   ROW(7, top1_nc), ROW(8, t10_20), ROW(9, n_tr)
    ]) AS u(feat, val)
    WHERE u.val IS NOT NULL
),
rk AS (
    SELECT feat, ld, win,
           CAST(rank() OVER (PARTITION BY feat ORDER BY val) AS double)
             + (CAST(count(*) OVER (PARTITION BY feat, val) AS double) - 1)/2.0 AS m,
           CAST(count(*) OVER (PARTITION BY feat) AS double) AS nf
    FROM long
)
SELECT feat AS f, ld AS d,
       least(60, greatest(1, CAST(ceil(60.0*m/nf) AS integer))) AS b,
       CAST(count_if(win) AS bigint) AS np, CAST(count_if(NOT win) AS bigint) AS nn
FROM rk GROUP BY feat, ld, least(60, greatest(1, CAST(ceil(60.0*m/nf) AS integer)))
