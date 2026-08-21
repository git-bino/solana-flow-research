-- 2 -- what the 20 anchor wallets did on their PRIOR tokens.
--
-- NO LOOKAHEAD, proved by the accumulation: for a token launched on day D only
-- the wallet's tokens whose FIRST TRADE fell strictly before D are counted.
-- The window frame is `UNBOUNDED PRECEDING AND 1 PRECEDING` on the day key, so
-- day D itself can never enter its own features.  The prior token's outcome
-- (`win60`) is an outcome of a DIFFERENT, EARLIER token, which is information
-- already public before D.
--
-- HOLDING TIME.  first buy -> last sell; if the wallet never sold, the clock
-- runs to the end of the scan window, 2026-05-21 00:00:00.  That is a LOWER
-- bound on a still-open holding time, and is labelled as such.
--
-- ENTRY SIZE is the SOL of the wallet's FIRST BUY (`first_buy_sol`), not its
-- total SOL, so a wallet that added later is not counted as a bigger entrant.
--
-- SIZE RATIO = mean first-buy SOL on prior tokens that reached x >= 60, divided
-- by the mean on the ones that did not.  NULL when either side has no token.
--
-- ENTRY ORDER is `rk_buy` -- the buyer rank, NOT the transfer-aware holder rank
-- (see sql/wallet_network.sql).
WITH cu AS (
    SELECT token_mint,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
coh AS (SELECT token_mint FROM cu WHERE dev IS NOT NULL AND dev < 1e-6),
tb AS (
    SELECT b.token_mint, date(b.launch_time) AS ld, coalesce(b.max_x, 0.0) >= 60 AS win60
    FROM dune.quantbino1695.result_flow_token_base b JOIN coh c ON c.token_mint = b.token_mint
),
aw AS (SELECT DISTINCT token_mint, wallet FROM dune.quantbino1695.result_flow_ddsell
       WHERE anchor_kind = 'H20' AND u_anchor > 0),
wl AS (SELECT DISTINCT wallet FROM aw),
-- one row per (wallet, prior token)
wp AS (
    SELECT k.w, date(from_unixtime(k.ft)) AS d, tb.win60,
           coalesce(k.last_sell_ut, to_unixtime(TIMESTAMP '2026-05-21 00:00:00')) - k.ft AS hold_s,
           k.u_final > 0                AS still,
           k.first_buy_sol              AS esol,
           CAST(k.rk_buy AS double)     AS rk
    FROM dune.quantbino1695.result_flow_wtok k
    JOIN tb ON tb.token_mint = k.mint
),
wd AS (
    SELECT w, d,
           count(*)                                   AS n,
           sum(hold_s)                                AS s_hold,
           count_if(still)                            AS n_still,
           sum(esol)                                  AS s_sol,
           sum(rk)                                    AS s_rk,
           count_if(win60)                            AS n_win,
           sum(if(win60, esol, 0.0))                  AS s_sol_win
    FROM wp GROUP BY w, d
),
cum AS (
    SELECT w, d,
           sum(n)        OVER pw AS c_n,   sum(s_hold) OVER pw AS c_hold,
           sum(n_still)  OVER pw AS c_st,  sum(s_sol)  OVER pw AS c_sol,
           sum(s_rk)     OVER pw AS c_rk,  sum(n_win)  OVER pw AS c_nw,
           sum(s_sol_win) OVER pw AS c_solw
    FROM wd
    WINDOW pw AS (PARTITION BY w ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
),
dates AS (SELECT DISTINCT ld FROM tb),
grid AS (
    SELECT wl.wallet, dates.ld,
           max(if(cum.d <= dates.ld, cum.c_n))    AS c_n,
           max(if(cum.d <= dates.ld, cum.c_hold)) AS c_hold,
           max(if(cum.d <= dates.ld, cum.c_st))   AS c_st,
           max(if(cum.d <= dates.ld, cum.c_sol))  AS c_sol,
           max(if(cum.d <= dates.ld, cum.c_rk))   AS c_rk,
           max(if(cum.d <= dates.ld, cum.c_nw))   AS c_nw,
           max(if(cum.d <= dates.ld, cum.c_solw)) AS c_solw
    FROM wl CROSS JOIN dates
    LEFT JOIN cum ON cum.w = wl.wallet AND cum.d <= dates.ld
    GROUP BY wl.wallet, dates.ld
),
j AS (
    SELECT aw.token_mint,
           g.c_hold / nullif(CAST(g.c_n AS double), 0)              AS b_hold_s,
           CAST(g.c_st AS double) / nullif(CAST(g.c_n AS double), 0) AS b_still,
           g.c_sol / nullif(CAST(g.c_n AS double), 0)               AS b_esol,
           g.c_rk  / nullif(CAST(g.c_n AS double), 0)               AS b_rk,
           CASE WHEN g.c_nw > 0 AND g.c_n > g.c_nw AND (g.c_sol - g.c_solw) > 0
                THEN (g.c_solw / CAST(g.c_nw AS double))
                     / ((g.c_sol - g.c_solw) / CAST(g.c_n - g.c_nw AS double))
           END                                                       AS b_ratio
    FROM aw JOIN tb ON tb.token_mint = aw.token_mint
            LEFT JOIN grid g ON g.wallet = aw.wallet AND g.ld = tb.ld
)
SELECT token_mint,
       approx_percentile(b_hold_s, 0.50) AS m_hold_s,
       approx_percentile(b_still,  0.50) AS m_still,
       approx_percentile(b_esol,   0.50) AS m_esol,
       approx_percentile(b_rk,     0.50) AS m_rk,
       approx_percentile(b_ratio,  0.50) AS m_ratio
FROM j GROUP BY token_mint
