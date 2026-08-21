-- AUDIT 4 FIX 1 -- CAUSAL UNIVERSE.
--
-- The universe was `max|x*y/k0 - 1| < 1e-6`, an invariant computed over the
-- token's WHOLE LIFE.  At the anchor nobody can know whether the token will
-- leave the invariant later, so that filter is whole-life lookahead.  It is
-- replaced here by the LAUNCH-TIME observable
--
--     createevent.is_mayhem_mode = false
--
-- carried in result_flow_clean.mayhem_flag = bool_or(is_mayhem_mode) over the
-- token's create events.  The flag is set when the token is created, so it is
-- known before the first trade.
--
-- The PRIOR-TOKEN universe is switched too: sql/b1_economics.sql used the
-- whole-life clean table for the earlier tokens as well, which put the same
-- lookahead inside the win-rate denominator.  Here `coh` is the causal universe
-- and it is the ONLY universe used, for the scored token and its priors alike.
--
-- Everything else -- the day-keyed lookahead-free win rate, the inclusive
-- cumulative sum, the single UNNEST before aggregation -- is unchanged from
-- sql/b1_economics.sql; see that file's header for those derivations.

-- 0 -- LOOKAHEAD-FREE rebuild of the wallet win-rate features.
--
-- ⚠ DEFECT 1 (LOOKAHEAD), confirmed by reading sql/pd_history_tok.sql line 16
-- and sql/wn_behaviour.sql line 30:
--       coalesce(b.max_x, 0.0) >= 60 AS win60
-- `max_x` in result_flow_token_base is the maximum reserve over the prior
-- token's WHOLE LIFE, i.e. up to 2026-08-15.  Scoring a token launched on
-- 2026-05-12 with "did this wallet's earlier token ever reach 60" uses whether
-- that earlier token reached 60 at ANY later date -- possibly weeks after the
-- scored token was born.  That is future information.  The claim written in the
-- 2026-08-21 wallet_network decisions row -- "the prior token's outcome was
-- already public before D" -- was WRONG and is corrected here.
--
-- CORRECT DEFINITION: a prior token counts as a win only if it had ALREADY
-- reached x >= 60 before the scored token's launch DAY.  `t_60` in
-- result_flow_token_base is the timestamp of the first crossing, so the win is
-- keyed to the day
--       d_w = greatest(day the wallet first traded it, day it crossed 60)
-- because both facts must be true before the scored day.  A token that never
-- crossed contributes no win at any day.
--
-- ⚠ DEFECT 2 (UNDERCOUNT, not lookahead), also in the original: it combined an
-- EXCLUSIVE window frame (`ROWS ... AND 1 PRECEDING`) with `cum.d <= ld`.  For a
-- wallet whose latest active day d' is strictly before ld, that returns the sum
-- over days < d', silently dropping d' itself even though d' is strictly prior.
-- Fixed here with an INCLUSIVE cumulative sum plus `cum.d < ld`, which is the
-- exact "all days strictly before the scored day" set.
--
-- ONE UNNEST (two rows per wallet-token) BEFORE the aggregation, never on top of
-- a windowed CTE.
WITH coh AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_clean
    WHERE mayhem_flag = false            -- LAUNCH-TIME observable, no lookahead
),
tb AS (
    SELECT b.token_mint, date(b.launch_time) AS ld, b.t_60
    FROM dune.quantbino1695.result_flow_token_base b JOIN coh c ON c.token_mint = b.token_mint
),
aw AS (SELECT DISTINCT token_mint, wallet FROM dune.quantbino1695.result_flow_ddsell
       WHERE anchor_kind = 'H20' AND u_anchor > 0),
wl AS (SELECT DISTINCT wallet FROM aw),
-- one row per (wallet, prior token): the day it counts in the denominator, and
-- the day it starts counting in the numerator (NULL = never)
wp AS (
    SELECT k.w, date(from_unixtime(k.ft)) AS d_n,
           CASE WHEN tb.t_60 IS NULL THEN NULL
                ELSE greatest(date(from_unixtime(k.ft)), date(tb.t_60)) END AS d_w
    FROM dune.quantbino1695.result_flow_wtok k
    JOIN tb ON tb.token_mint = k.mint
),
ev AS (
    SELECT w, u.d, u.dn, u.dw
    FROM wp CROSS JOIN UNNEST(ARRAY[ROW(d_n, 1, 0), ROW(d_w, 0, 1)]) AS u(d, dn, dw)
    WHERE u.d IS NOT NULL
),
wd AS (SELECT w, d, sum(dn) AS n, sum(dw) AS wn FROM ev GROUP BY w, d),
cum AS (
    SELECT w, d,
           sum(n)  OVER pw AS cn,
           sum(wn) OVER pw AS cw
    FROM wd
    WINDOW pw AS (PARTITION BY w ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
dates AS (SELECT DISTINCT ld FROM tb),
grid AS (
    SELECT wl.wallet, dates.ld,
           max(if(cum.d < dates.ld, cum.cn)) AS pn,
           max(if(cum.d < dates.ld, cum.cw)) AS pw
    FROM wl CROSS JOIN dates
    LEFT JOIN cum ON cum.w = wl.wallet AND cum.d < dates.ld
    GROUP BY wl.wallet, dates.ld
),
j AS (
    SELECT aw.token_mint,
           coalesce(g.pn, 0) > 0 AS exp,
           if(coalesce(g.pn,0) > 0, CAST(g.pw AS double)/g.pn) AS wr
    FROM aw JOIN tb ON tb.token_mint = aw.token_mint
            LEFT JOIN grid g ON g.wallet = aw.wallet AND g.ld = tb.ld
)
SELECT token_mint,
       approx_percentile(wr, 0.50)               AS wr_med,
       approx_percentile(wr, 0.90)               AS wr_p90,
       CAST(count_if(wr > 0.2) AS double)        AS n_wr20,
       CAST(count_if(exp) AS double)/count(*)    AS share_exp
FROM j GROUP BY token_mint
