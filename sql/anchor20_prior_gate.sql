-- 2 (gate) -- do the 20 anchor wallets have prior pump.fun history?
--
-- ⚠ LOWER BOUND, stated.  "Prior" is measured WITHIN the cohort launch window
-- [2026-05-10, 2026-05-19): a wallet counts as experienced if it first traded
-- some OTHER cohort token before this token's launch.  Activity on pump.fun
-- tokens launched BEFORE 2026-05-10 is NOT visible here -- capturing it needs a
-- tradeevent scan over the full history (21M createevents), far above budget.
-- The measured share is therefore a FLOOR on the true share.
--
-- No fan-out: per wallet the prior count is accumulated by launch DATE (9 dates)
-- and joined on (wallet, launch_date), instead of pairing every anchor wallet
-- with every token it ever touched.
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
tb AS (
    SELECT b.token_mint, b.launch_time, date(b.launch_time) AS ld
    FROM dune.quantbino1695.result_flow_token_base b
    JOIN coh c ON c.token_mint = b.token_mint
),
aw AS (
    SELECT DISTINCT token_mint, wallet
    FROM dune.quantbino1695.result_flow_ddsell
    WHERE anchor_kind = 'H20' AND u_anchor > 0
),
wl AS (SELECT DISTINCT wallet FROM aw),
wt AS (   -- (wallet, token) first touch, cohort tokens only
    SELECT t.user AS wallet, t.mint, min(t.evt_block_time) AS ft
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN wl ON wl.wallet = t.user
    JOIN coh c ON c.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-05-20'
    GROUP BY t.user, t.mint
),
wd AS (SELECT wallet, date(ft) AS d, count(*) AS n FROM wt GROUP BY wallet, date(ft)),
cum AS (
    SELECT wallet, d,
           sum(n) OVER (PARTITION BY wallet ORDER BY d
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_before_day
    FROM wd
),
dates AS (SELECT DISTINCT ld FROM tb),
grid AS (
    SELECT wl.wallet, dates.ld,
           max(if(cum.d <= dates.ld, cum.prior_before_day)) AS prior_cum
    FROM wl CROSS JOIN dates
    LEFT JOIN cum ON cum.wallet = wl.wallet AND cum.d <= dates.ld
    GROUP BY wl.wallet, dates.ld
),
j AS (
    SELECT aw.token_mint, aw.wallet, coalesce(g.prior_cum, 0) AS prior_tokens
    FROM aw JOIN tb ON tb.token_mint = aw.token_mint
            LEFT JOIN grid g ON g.wallet = aw.wallet AND g.ld = tb.ld
),
tokagg AS (
    SELECT token_mint, CAST(count(*) AS double) AS n_w,
           CAST(count_if(prior_tokens > 0) AS double) AS n_exp,
           CAST(count_if(prior_tokens > 0) AS double)/count(*) AS share_exp
    FROM j GROUP BY token_mint
)
SELECT 'wallet' AS lvl, CAST(count(*) AS double) AS n,
       CAST(count_if(prior_tokens > 0) AS double)/count(*) AS share_exp,
       approx_percentile(CAST(prior_tokens AS double), 0.50) AS p50,
       approx_percentile(CAST(prior_tokens AS double), 0.90) AS p90,
       CAST(max(prior_tokens) AS double) AS pmax, NULL AS q10, NULL AS q90
FROM j
UNION ALL
SELECT 'token', CAST(count(*) AS double), avg(share_exp),
       approx_percentile(share_exp, 0.50), approx_percentile(share_exp, 0.90),
       max(share_exp), approx_percentile(share_exp, 0.10), approx_percentile(n_w, 0.50)
FROM tokagg
