-- A.2 -- holder distribution AT THE MOMENT `x` first reaches 40 / 50 / 60.
--
-- NO LOOKAHEAD.  Every feature is built from trades with `evt_block_time <=`
-- the anchor and transfers with `block_slot <=` the anchor's slot.  Nothing
-- after the crossing enters any feature.  The anchor itself is derived inside
-- this query from `virtual_sol_reserves`, not read from a label table.
--
-- LEDGER IS TRANSFER-AWARE, the same mechanism as `oh_a` in extract_v2: a
-- wallet's balance is (tokens bought - tokens sold) + (tokens received -
-- tokens sent).  A trade-only ledger leaves a sender holding tokens it no
-- longer has.  Coverage was checked before writing this: the transfer
-- matviews run 2026-05-10 .. 2026-08-15 with no gap (xf_02 covers
-- 2026-05-10..05-15, xf_03 covers 05-16..05-21), and their token scope is
-- creations in [2026-05-10, 2026-07-03), which contains the whole cohort.
--
-- The transfer matviews carry `block_slot` but NOT `block_time`, so the cut at
-- the anchor is made on SLOT.  Slot and block time are both monotone, so this
-- is the same cut.
--
-- EVENT WINDOW.  Trades are read over [2026-05-10, 2026-05-20], i.e. the launch
-- window plus one day.  `t_anchor_s` has p90 = 130 s at level 60, so this is
-- generous, but tokens that first cross a level LATER than 2026-05-20 are
-- missing from this query and the row `coverage_*` counts exactly how many.

WITH base AS (
    SELECT token_mint, launch_time, creator
    FROM dune.quantbino1695.result_flow_token_base
),
ev AS (
    SELECT t.mint, t.user, t.is_buy,
           CAST(t.token_amount AS double)        AS ta,
           t.evt_block_time                      AS bt,
           t.evt_block_slot                      AS sl,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x,
           b.creator
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-05-20'
),
anch AS (
    SELECT mint,
           min(if(x >= 40, bt)) AS t40, min(if(x >= 40, sl)) AS s40,
           min(if(x >= 50, bt)) AS t50, min(if(x >= 50, sl)) AS s50,
           min(if(x >= 60, bt)) AS t60, min(if(x >= 60, sl)) AS s60
    FROM ev GROUP BY mint
),
al AS (
    SELECT mint, 40 AS lvl, t40 AS t_a, s40 AS s_a FROM anch WHERE t40 IS NOT NULL
    UNION ALL
    SELECT mint, 50, t50, s50 FROM anch WHERE t50 IS NOT NULL
    UNION ALL
    SELECT mint, 60, t60, s60 FROM anch WHERE t60 IS NOT NULL
),
-- trade side of the ledger, up to and including the anchor
led_tr AS (
    SELECT a.mint, a.lvl, e.user AS w, sum(if(e.is_buy, e.ta, -e.ta)) AS du
    FROM al a JOIN ev e ON e.mint = a.mint AND e.bt <= a.t_a
    GROUP BY a.mint, a.lvl, e.user
),
tr AS (
    SELECT a.mint, a.lvl, count(*) AS n_trades,
           count(DISTINCT if(e.is_buy, e.user)) AS n_buyers,
           max(e.creator) AS creator
    FROM al a JOIN ev e ON e.mint = a.mint AND e.bt <= a.t_a
    GROUP BY a.mint, a.lvl
),
xf_raw AS (
    SELECT token_mint_address AS mint, block_slot, from_owner, to_owner,
           CAST(amount AS double) AS amount
    FROM ({{XF_UNION}}) u
    WHERE block_date >= DATE '2026-05-10' AND block_date <= DATE '2026-05-20'
),
xf_leg AS (
    SELECT mint, block_slot, to_owner   AS w,  amount AS du FROM xf_raw
    UNION ALL
    SELECT mint, block_slot, from_owner AS w, -amount AS du FROM xf_raw
),
led_xf AS (
    SELECT a.mint, a.lvl, x.w, sum(x.du) AS du
    FROM al a JOIN xf_leg x ON x.mint = a.mint AND x.block_slot <= a.s_a
    GROUP BY a.mint, a.lvl, x.w
),
led AS (
    SELECT mint, lvl, w, sum(du) AS u FROM (
        SELECT mint, lvl, w, du FROM led_tr
        UNION ALL SELECT mint, lvl, w, du FROM led_xf
    ) GROUP BY mint, lvl, w
),
hrank AS (
    SELECT l.mint, l.lvl, l.w, l.u, t.creator,
           row_number() OVER (PARTITION BY l.mint, l.lvl ORDER BY l.u DESC) AS rk_d,
           row_number() OVER (PARTITION BY l.mint, l.lvl ORDER BY l.u ASC)  AS rk_a,
           count(*)     OVER (PARTITION BY l.mint, l.lvl) AS n_h,
           sum(l.u)     OVER (PARTITION BY l.mint, l.lvl) AS tot
    FROM led l JOIN tr t ON t.mint = l.mint AND t.lvl = l.lvl
    WHERE l.u > 0
),
hagg AS (
    SELECT h.mint, h.lvl,
           max(h.n_h) AS n_holders, max(h.tot) AS tot,
           sum(h.u) FILTER (WHERE h.rk_d = 1)  AS top1,
           sum(h.u) FILTER (WHERE h.rk_d <= 3) AS top3,
           sum(h.u) FILTER (WHERE h.rk_d <= 10) AS top10,
           sum(h.u) FILTER (WHERE h.w = h.creator) AS cre,
           sum(CAST(h.rk_a AS double) * h.u) AS wsum
    FROM hrank h
    GROUP BY h.mint, h.lvl
),
feat AS (
    SELECT t.mint, t.lvl,
           CAST(h.n_holders AS double)                       AS f_n_holders,
           if(h.tot > 0, h.top1 / h.tot, 1.0)                AS f_top1,
           if(h.tot > 0, h.top3 / h.tot, 1.0)                AS f_top3,
           if(h.tot > 0, h.top10 / h.tot, 1.0)               AS f_top10,
           if(h.tot > 0, coalesce(h.cre, 0) / h.tot, 0.0)    AS f_creator,
           if(h.n_holders > 1 AND h.tot > 0,
              2.0 * h.wsum / (CAST(h.n_holders AS double) * h.tot)
                - (CAST(h.n_holders AS double) + 1) / CAST(h.n_holders AS double),
              0.0)                                           AS f_gini,
           CAST(t.n_trades AS double)                        AS f_n_trades,
           CAST(t.n_buyers AS double)                        AS f_n_buyers
    FROM tr t JOIN hagg h ON h.mint = t.mint AND h.lvl = t.lvl
),
long AS (
    SELECT lvl, f.name, f.val FROM feat
    CROSS JOIN UNNEST(ARRAY[
        ROW('n_holders', f_n_holders), ROW('gini', f_gini),
        ROW('top1', f_top1), ROW('top3', f_top3), ROW('top10', f_top10),
        ROW('creator_share', f_creator),
        ROW('n_trades', f_n_trades), ROW('n_buyers', f_n_buyers)
    ]) AS f(name, val)
)
SELECT lvl, name, CAST(count(*) AS double) AS n,
       approx_percentile(val, 0.25) AS p25,
       approx_percentile(val, 0.50) AS p50,
       approx_percentile(val, 0.75) AS p75,
       avg(val) AS mean,
       CAST(count_if(val < 3) AS double) / count(*) AS share_lt3
FROM long GROUP BY lvl, name

UNION ALL
SELECT lvl, 'coverage_tokens', CAST(count(*) AS double),
       NULL, NULL, NULL, NULL, NULL
FROM al GROUP BY lvl

ORDER BY lvl, name
