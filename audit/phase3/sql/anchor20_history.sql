-- 2 (full) -- prior-history features of the 20 anchor wallets -> token outcome.
--
-- ⚠ SAME LOWER BOUND as the gate: "prior" means an earlier token INSIDE the
-- cohort window; pre-2026-05-10 pump.fun activity is invisible here.
--
-- NO LOOKAHEAD: for a token launched on day D, only the wallet's tokens whose
-- FIRST trade fell strictly before D are counted, accumulated by day.
--
-- SUBSTITUTION, stated (ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР).  The brief asks how
-- early the wallet was among holders on its prior tokens ("хэдэн дэх эзэмшигч").
-- That rank needs a running holder count on every prior token -- the shape that
-- cost 24.466 cr.  Instead the wallet's median SECONDS FROM LAUNCH to its first
-- trade on prior tokens is used: cheap, monotone in the same direction, and NOT
-- the same quantity.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
tb AS (
    SELECT b.token_mint, b.launch_time, date(b.launch_time) AS ld,
           coalesce(b.max_x, 0.0) >= 60 AS win60
    FROM dune.quantbino1695.result_flow_token_base b
    JOIN coh c ON c.token_mint = b.token_mint
),
aw AS (
    SELECT DISTINCT token_mint, wallet
    FROM dune.quantbino1695.result_flow_ddsell
    WHERE anchor_kind = 'H20' AND u_anchor > 0
),
wl AS (SELECT DISTINCT wallet FROM aw),
wt AS (
    SELECT t.user AS wallet, t.mint, min(t.evt_block_time) AS ft
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN wl ON wl.wallet = t.user
    JOIN coh c ON c.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-05-20'
    GROUP BY t.user, t.mint
),
wtx AS (
    SELECT wt.wallet, date(wt.ft) AS d, tb.win60,
           to_unixtime(wt.ft) - to_unixtime(tb.launch_time) AS delay_s
    FROM wt JOIN tb ON tb.token_mint = wt.mint
),
wd AS (
    SELECT wallet, d, count(*) AS n, count_if(win60) AS w,
           sum(delay_s) AS sd
    FROM wtx GROUP BY wallet, d
),
cum AS (
    SELECT wallet, d,
           sum(n) OVER (PARTITION BY wallet ORDER BY d
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS cn,
           sum(w) OVER (PARTITION BY wallet ORDER BY d
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS cw,
           sum(sd) OVER (PARTITION BY wallet ORDER BY d
                         ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS cd
    FROM wd
),
dates AS (SELECT DISTINCT ld FROM tb),
grid AS (
    SELECT wl.wallet, dates.ld,
           max(if(cum.d <= dates.ld, cum.cn)) AS pn,
           max(if(cum.d <= dates.ld, cum.cw)) AS pw,
           max(if(cum.d <= dates.ld, cum.cd)) AS pd
    FROM wl CROSS JOIN dates
    LEFT JOIN cum ON cum.wallet = wl.wallet AND cum.d <= dates.ld
    GROUP BY wl.wallet, dates.ld
),
j AS (
    SELECT aw.token_mint, aw.wallet, tb.win60,
           coalesce(g.pn, 0) AS pn, coalesce(g.pw, 0) AS pw,
           if(coalesce(g.pn,0) > 0, CAST(g.pw AS double)/g.pn, CAST(NULL AS double)) AS wr,
           if(coalesce(g.pn,0) > 0, g.pd / g.pn, CAST(NULL AS double)) AS mean_delay
    FROM aw JOIN tb ON tb.token_mint = aw.token_mint
            LEFT JOIN grid g ON g.wallet = aw.wallet AND g.ld = tb.ld
),
tok AS (
    SELECT token_mint, max(win60) AS win60,
           CAST(count(*) AS double) AS n_w,
           approx_percentile(wr, 0.50) AS wr_med,
           max(wr) AS wr_max,
           CAST(count_if(wr > 0.2) AS double) AS n_wr20,
           approx_percentile(mean_delay, 0.50) AS delay_med,
           approx_percentile(CAST(pn AS double), 0.50) AS pn_med
    FROM j GROUP BY token_mint
),
r AS (
    SELECT tok.*,
           CAST(rank() OVER (ORDER BY wr_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY wr_med) AS double) - 1)/2.0 AS m_wr,
           CAST(rank() OVER (ORDER BY CAST(n_wr20 AS double)) AS double)
             + (CAST(count(*) OVER (PARTITION BY n_wr20) AS double) - 1)/2.0 AS m_n20,
           CAST(rank() OVER (ORDER BY delay_med) AS double)
             + (CAST(count(*) OVER (PARTITION BY delay_med) AS double) - 1)/2.0 AS m_dl,
           CAST(count(*) OVER () AS double) AS n_tot
    FROM tok
),
b AS (
    SELECT r.*,
           least(5, greatest(1, CAST(ceil(5.0 * m_wr  / n_tot) AS integer))) AS g_wr,
           least(5, greatest(1, CAST(ceil(5.0 * m_n20 / n_tot) AS integer))) AS g_n20,
           least(5, greatest(1, CAST(ceil(5.0 * m_dl  / n_tot) AS integer))) AS g_dl
    FROM r
)
SELECT g_wr, g_n20, g_dl, CAST(count(*) AS double) AS n,
       CAST(count_if(win60) AS double)/count(*) AS s60,
       approx_percentile(wr_med, 0.50) AS wr_med, approx_percentile(wr_max, 0.50) AS wr_max,
       approx_percentile(CAST(n_wr20 AS double), 0.50) AS n20_med,
       approx_percentile(delay_med, 0.50) AS delay_med,
       approx_percentile(pn_med, 0.50) AS pn_med
FROM b
GROUP BY GROUPING SETS ((), (g_wr), (g_n20), (g_dl))
ORDER BY g_wr, g_n20, g_dl
