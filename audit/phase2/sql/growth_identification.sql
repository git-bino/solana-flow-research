-- Growth identification: can a token be recognised BEFORE it crosses a threshold?
--
-- Run once per observation point T (seconds since launch); {{T}} is substituted.
-- Long format on purpose: one output row per (feature, decile), plus one per
-- feature for the AUC.  A wide form would need 14 features x 2 targets of window
-- functions in a single SELECT, which is the shape that killed probe A2.
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР.
--
-- NO LOOKAHEAD.  Every feature is built from `early`, which is filtered to
-- `evt_block_time <= created_at + {{T}} seconds`.  The only columns that read
-- past T are the LABELS (max_x over the full window) and `already`, which marks
-- tokens that had crossed before T.  `prior_count` counts a creator's tokens
-- created strictly before this token.
--
-- Scan cost: features need only launch window + 1 day, because T <= 300s; the
-- labels need the full event window.  Measured 1.315 cr for 3 launch days.
WITH cohort AS (
    SELECT mint, min(evt_block_time) AS created_at, min(user) AS creator
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
prior AS (
    SELECT co.mint,
           count(a.mint) FILTER (WHERE a.evt_block_time < co.created_at) AS n_prior
    FROM cohort co
    LEFT JOIN pumpdotfun_solana.pump_evt_createevent a ON a.user = co.creator
    GROUP BY co.mint
),
lab AS (
    SELECT t.mint,
           max(CAST(t.virtual_sol_reserves AS bigint)) AS max_x_lam,
           min(t.evt_block_time) FILTER (WHERE CAST(t.virtual_sol_reserves AS bigint) >= 60000000000)  AS t60,
           min(t.evt_block_time) FILTER (WHERE CAST(t.virtual_sol_reserves AS bigint) >= 115000000000) AS t115
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN cohort c ON c.mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
      AND t.evt_block_time < TIMESTAMP '2026-08-15 23:59:00 UTC'
    GROUP BY t.mint
),
early AS (
    SELECT t.mint, t.user, t.is_buy, c.creator,
           CAST(t.sol_amount AS bigint) AS lam,
           CAST(t.virtual_sol_reserves AS bigint) AS vsol,
           if(t.is_buy, CAST(t.token_amount AS bigint), -CAST(t.token_amount AS bigint)) AS du
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN cohort c ON c.mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-05-19'
      AND t.evt_block_time >= c.created_at
      AND t.evt_block_time <= c.created_at + INTERVAL '{{T}}' SECOND
),
hold AS (
    SELECT mint, user, max(creator) AS creator, sum(du) AS u
    FROM early GROUP BY mint, user
),
hpos AS (SELECT mint, user, creator, CAST(u AS double) AS u FROM hold WHERE u > 0),
hrank AS (
    SELECT mint, user, creator, u,
           row_number() OVER (PARTITION BY mint ORDER BY u DESC) AS rk_desc,
           row_number() OVER (PARTITION BY mint ORDER BY u ASC)  AS rk_asc,
           count(*)  OVER (PARTITION BY mint) AS n_h,
           sum(u)    OVER (PARTITION BY mint) AS tot_u
    FROM hpos
),
hagg AS (
    SELECT mint, max(n_h) AS n_holders, max(tot_u) AS tot_u,
           sum(u) FILTER (WHERE rk_desc = 1)  AS top1,
           sum(u) FILTER (WHERE rk_desc <= 3) AS top3,
           sum(u) FILTER (WHERE rk_desc <= 10) AS top10,
           sum(u) FILTER (WHERE user = creator) AS cre_u,
           sum(u * u) AS sq_u,
           -- Gini via the sorted-rank identity: G = 2*sum(i*x_i)/(n*sum x) - (n+1)/n
           sum(CAST(rk_asc AS double) * u) AS wsum
    FROM hrank GROUP BY mint
),
tagg AS (
    SELECT mint, count(*) AS n_tr,
           count(DISTINCT if(is_buy, user, NULL)) AS n_buy,
           avg(CAST(lam AS double)) AS m_lam,
           stddev(CAST(lam AS double)) AS sd_lam,
           CAST(count_if(is_buy) AS double) / count(*) AS buy_share,
           CAST(count_if(lam IN (100000000, 500000000, 1000000000)) AS double) / count(*) AS round_share,
           CAST(max(vsol) AS double) / 1e9 - 30.0 AS x_growth
    FROM early GROUP BY mint
),
feat AS (
    SELECT c.mint,
           l.max_x_lam >= 60000000000  AS y60,
           l.max_x_lam >= 115000000000 AS y115,
           (l.t60  IS NOT NULL AND date_diff('second', c.created_at, l.t60)  <= {{T}}) AS late60,
           (l.t115 IS NOT NULL AND date_diff('second', c.created_at, l.t115) <= {{T}}) AS late115,
           coalesce(CAST(h.n_holders AS double), 0)                            AS f_n_holders,
           if(h.tot_u > 0, h.sq_u / (h.tot_u * h.tot_u), 1.0)                   AS f_hhi,
           if(h.tot_u > 0, h.top1  / h.tot_u, 1.0)                              AS f_top1,
           if(h.tot_u > 0, h.top3  / h.tot_u, 1.0)                              AS f_top3,
           if(h.tot_u > 0, h.top10 / h.tot_u, 1.0)                              AS f_top10,
           if(h.tot_u > 0, coalesce(h.cre_u, 0) / h.tot_u, 0.0)                 AS f_creator,
           if(h.n_holders > 1 AND h.tot_u > 0,
              2.0 * h.wsum / (h.n_holders * h.tot_u)
              - CAST(h.n_holders + 1 AS double) / h.n_holders, 0.0)             AS f_gini,
           coalesce(CAST(t.n_tr  AS double), 0)                                 AS f_n_trades,
           coalesce(CAST(t.n_buy AS double), 0)                                 AS f_n_buyers,
           coalesce(if(t.m_lam > 0, t.sd_lam / t.m_lam, 0.0), 0.0)              AS f_cv,
           coalesce(t.buy_share, 0.0)                                           AS f_buy_share,
           coalesce(t.round_share, 0.0)                                         AS f_round,
           coalesce(t.x_growth, 0.0)                                            AS f_xgrowth,
           CAST(p.n_prior AS double)                                            AS f_prior
    FROM cohort c
    JOIN lab l ON l.mint = c.mint
    LEFT JOIN hagg h ON h.mint = c.mint
    LEFT JOIN tagg t ON t.mint = c.mint
    LEFT JOIN prior p ON p.mint = c.mint
),
long AS (
    SELECT mint, y60, y115, late60, late115, f.name, f.val
    FROM feat CROSS JOIN UNNEST(ARRAY[
        ROW('n_holders', f_n_holders), ROW('hhi', f_hhi), ROW('top1', f_top1),
        ROW('top3', f_top3), ROW('top10', f_top10), ROW('creator_share', f_creator),
        ROW('gini', f_gini), ROW('n_trades', f_n_trades), ROW('n_buyers', f_n_buyers),
        ROW('size_cv', f_cv), ROW('buy_share', f_buy_share),
        ROW('round_share', f_round), ROW('x_growth', f_xgrowth),
        ROW('prior_count', f_prior)
    ]) AS f(name, val)
),
-- 60-ийн зорилт: аль хэдийн давсныг ХАСАХГҮЙ, тусад нь тоолж, үлдсэн дээр AUC
r60 AS (
    SELECT name, y60,
           rank() OVER (PARTITION BY name ORDER BY val) AS rk
    FROM long WHERE NOT late60
),
r115 AS (
    SELECT name, y115,
           rank() OVER (PARTITION BY name ORDER BY val) AS rk
    FROM long WHERE NOT late115
),
d60 AS (
    SELECT name, ntile(10) OVER (PARTITION BY name ORDER BY val) AS dec, y60
    FROM long WHERE NOT late60
)
SELECT 'auc' AS kind, a.name, CAST(NULL AS bigint) AS dec,
       a.n1 AS n_pos, a.n0 AS n_neg,
       (a.rsum - CAST(a.n1 AS double)*(a.n1+1)/2.0) / (CAST(a.n1 AS double)*a.n0) AS auc60,
       b.auc115, CAST(NULL AS double) AS rate
FROM (SELECT name, sum(CAST(rk AS double)) FILTER (WHERE y60) AS rsum,
             count_if(y60) AS n1, count_if(NOT y60) AS n0 FROM r60 GROUP BY name) a
JOIN (SELECT name,
             (sum(CAST(rk AS double)) FILTER (WHERE y115)
              - CAST(count_if(y115) AS double)*(count_if(y115)+1)/2.0)
             / (CAST(count_if(y115) AS double)*count_if(NOT y115)) AS auc115
      FROM r115 GROUP BY name) b ON b.name = a.name
UNION ALL
SELECT 'decile', name, CAST(dec AS bigint), count_if(y60), count_if(NOT y60),
       CAST(NULL AS double), CAST(NULL AS double),
       CAST(count_if(y60) AS double) / count(*)
FROM d60 GROUP BY name, dec
