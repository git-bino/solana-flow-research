-- 3(B) -- per-token prior-history variables of the 20 anchor wallets.
-- Same construction and same NO-LOOKAHEAD accumulation (by launch DATE) as
-- sql/anchor20_history.sql.  Two changes, both stated:
--   * `wr_p90` replaces `wr_max` (the brief asks for median and p90).
--   * `share_exp` = share of the anchor wallets with any prior token, added.
-- ⚠ SAME LOWER BOUND: "prior" = an earlier token INSIDE the cohort window.
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
    FROM dune.quantbino1695.result_flow_token_base b JOIN coh c ON c.token_mint = b.token_mint
),
aw AS (
    SELECT DISTINCT token_mint, wallet FROM dune.quantbino1695.result_flow_ddsell
    WHERE anchor_kind = 'H20' AND u_anchor > 0
),
wl AS (SELECT DISTINCT wallet FROM aw),
wt AS (
    SELECT t.user AS wallet, t.mint, min(t.evt_block_time) AS ft
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN wl ON wl.wallet = t.user JOIN coh c ON c.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-05-20'
    GROUP BY t.user, t.mint
),
wtx AS (SELECT wt.wallet, date(wt.ft) AS d, tb.win60 FROM wt JOIN tb ON tb.token_mint = wt.mint),
wd AS (SELECT wallet, d, count(*) AS n, count_if(win60) AS w FROM wtx GROUP BY wallet, d),
cum AS (
    SELECT wallet, d,
           sum(n) OVER (PARTITION BY wallet ORDER BY d
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS cn,
           sum(w) OVER (PARTITION BY wallet ORDER BY d
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS cw
    FROM wd
),
dates AS (SELECT DISTINCT ld FROM tb),
grid AS (
    SELECT wl.wallet, dates.ld,
           max(if(cum.d <= dates.ld, cum.cn)) AS pn, max(if(cum.d <= dates.ld, cum.cw)) AS pw
    FROM wl CROSS JOIN dates
    LEFT JOIN cum ON cum.wallet = wl.wallet AND cum.d <= dates.ld
    GROUP BY wl.wallet, dates.ld
),
j AS (
    SELECT aw.token_mint,
           coalesce(g.pn, 0) > 0 AS exp,
           if(coalesce(g.pn,0) > 0, CAST(g.pw AS double)/g.pn, CAST(NULL AS double)) AS wr
    FROM aw JOIN tb ON tb.token_mint = aw.token_mint
            LEFT JOIN grid g ON g.wallet = aw.wallet AND g.ld = tb.ld
)
SELECT token_mint,
       approx_percentile(wr, 0.50) AS wr_med,
       approx_percentile(wr, 0.90) AS wr_p90,
       CAST(count_if(wr > 0.2) AS double) AS n_wr20,
       CAST(count_if(exp) AS double) / count(*) AS share_exp
FROM j GROUP BY token_mint
