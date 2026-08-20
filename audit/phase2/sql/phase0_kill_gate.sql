-- Phase 0 KILL gate — curve reconstruction checks 1a / 1b / 1c (spec §7, v1.3).
--
-- ONE window per execution.  AGGREGATE ONLY: the query returns a single row of
-- counters and percentiles, so nothing is exported and the retrieval cost is nil.
--
--   launch window  [2026-05-19 00:00, 2026-05-28 00:00)      <- substituted per chunk
--   event window   [2026-05-19 00:00, 2026-08-15 23:59)
--   universe       createevent.virtual_sol_reserves = 30000000000  (FIX 9)
--
-- Chunk 1's window is NOT re-run here: it was measured in
-- docs/phase0_quote_mint_verify.md (1a 15,310,479/15,310,479 = 100.0000%,
-- 1b p50 8.21e-12 / p99 3.27e-11 / max 3.33e-11, 1c 241,718/241,718 = 100.00%).
--
-- Checks, all over consecutive event pairs in (mint, slot, tx_index, ix_index) order:
--   1a  d(virtual_sol_reserves)   = +sol_amount   on a buy, -sol_amount   on a sell
--       d(virtual_token_reserves) = -token_amount on a buy, +token_amount on a sell
--       reported separately for pairs that touch a mayhem row, since mayhem
--       reparameterises the curve and the identity is not expected to hold across
--       a segment boundary.
--   1b  |d(x*y)/(x*y)| percentiles, non-mayhem pairs.  Threshold 1e-9.
--   1c  every token's FIRST trade must start from x_pre = 30 SOL, and the number
--       of distinct implied x0 values must be 1.
--   extra  curve-implied average price vs the realised sol_amount/token_amount.
--       The implied token count is written as k*dx/(x_pre*x_post) rather than
--       k/x_pre - k/x_post: algebraically identical, but the difference form
--       cancels catastrophically in float64 for small trades and would report
--       numerical noise as model error.
WITH sel AS (
    SELECT mint,
           max(CAST(virtual_sol_reserves   AS bigint)) AS x0_lam,
           max(CAST(virtual_token_reserves AS bigint)) AS y0_units
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-19'
      AND evt_block_date <  DATE '2026-05-28'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
ev AS (
    SELECT s.mint,
           s.x0_lam,
           s.y0_units,
           t.evt_block_slot AS slot,
           t.evt_tx_index   AS txi,
           coalesce(t.evt_outer_instruction_index, 0) * 64
             + coalesce(t.evt_inner_instruction_index, 0) AS ixi,
           t.is_buy,
           CAST(t.sol_amount   AS bigint) AS lam,
           CAST(t.token_amount AS bigint) AS units,
           CAST(t.virtual_sol_reserves   AS bigint) AS vsol,
           CAST(t.virtual_token_reserves AS bigint) AS vtok,
           coalesce(t.mayhem_mode, false) AS mayhem
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN sel s ON t.mint = s.mint
    WHERE t.evt_block_date >= DATE '2026-05-19'
      AND t.evt_block_date <= DATE '2026-08-15'
      AND t.evt_block_time <  TIMESTAMP '2026-08-15 23:59:00'
),
seqd AS (
    SELECT *,
           row_number() OVER w AS seq,
           lag(vsol)   OVER w AS prev_vsol,
           lag(vtok)   OVER w AS prev_vtok,
           lag(mayhem) OVER w AS prev_mayhem
    FROM ev
    WINDOW w AS (PARTITION BY mint ORDER BY slot, txi, ixi)
),
-- Separate pass: a window function cannot be nested inside another's arguments,
-- so `seq` has to exist as a column before it can be minimised over the token.
seqm AS (
    SELECT *,
           -- first event index at which this token is in mayhem mode, so a mayhem
           -- pair can be placed relative to the start of its mayhem segment.
           min(if(mayhem, seq)) OVER (PARTITION BY mint) AS first_mayhem_seq
    FROM seqd
),
pairs AS (
    SELECT mint, seq, is_buy, lam, units, vsol, vtok, x0_lam, y0_units,
           mayhem OR prev_mayhem AS pair_mayhem,
           seq - first_mayhem_seq AS pos_in_mayhem,
           vsol - prev_vsol AS d_sol,
           vtok - prev_vtok AS d_tok,
           if(is_buy,  lam, -lam)   AS exp_d_sol,
           if(is_buy, -units, units) AS exp_d_tok,
           CAST(prev_vsol AS double) * CAST(prev_vtok AS double) AS prev_k,
           CAST(vsol      AS double) * CAST(vtok      AS double) AS k
    FROM seqm
    WHERE prev_vsol IS NOT NULL
),
-- 1c: the first trade of every token, and the reserve it started from.
firsts AS (
    SELECT mint,
           if(is_buy, vsol - lam, vsol + lam) AS x_pre_first
    FROM seqd
    WHERE seq = 1
),
-- extra: curve-implied token count for every non-mayhem trade with a predecessor.
priced AS (
    SELECT units,
           lam,
           abs(CAST(x0_lam AS double) * CAST(y0_units AS double)
               * CAST(lam AS double)
               / (CAST(vsol - d_sol AS double) * CAST(vsol AS double))) AS implied_units
    FROM pairs
    WHERE NOT pair_mayhem
      AND units > 0
      AND vsol - d_sol > 0
      AND vsol > 0
)
SELECT
    -- ---- volume ----
    (SELECT count(*) FROM sel)   AS tokens_in_window,
    (SELECT count(*) FROM ev)    AS events_scanned,
    count(*)                     AS pairs_total,

    -- ---- 1a, non-mayhem ----
    count_if(NOT pair_mayhem)                                        AS a_pairs_nonmayhem,
    count_if(NOT pair_mayhem AND d_sol = exp_d_sol)                  AS a_sol_match,
    count_if(NOT pair_mayhem AND d_tok = exp_d_tok)                  AS a_tok_match,

    -- ---- 1a, mayhem-touching pairs, reported separately (not a FAIL) ----
    count_if(pair_mayhem)                                            AS a_pairs_mayhem,
    count_if(pair_mayhem AND d_sol = exp_d_sol)                      AS a_sol_match_mayhem,
    count_if(pair_mayhem AND d_tok = exp_d_tok)                      AS a_tok_match_mayhem,

    -- ---- 1b: |d(x*y)/(x*y)|, non-mayhem.  prev_k > 0 guard: a zero denominator
    -- produced NaN once before, which approx_percentile rejects outright.
    approx_percentile(CASE WHEN NOT pair_mayhem AND prev_k > 0
                           THEN abs(k - prev_k) / prev_k END, 0.50) AS b_p50,
    approx_percentile(CASE WHEN NOT pair_mayhem AND prev_k > 0
                           THEN abs(k - prev_k) / prev_k END, 0.99) AS b_p99,
    max(CASE WHEN NOT pair_mayhem AND prev_k > 0
             THEN abs(k - prev_k) / prev_k END)                     AS b_max,

    -- ---- 1b on MAYHEM pairs: window 2 measured 1b on non-mayhem only, so the
    -- mayhem side of the product invariant was never looked at.  Numbers only,
    -- no PASS/FAIL: mayhem reparameterises the curve by design.
    approx_percentile(CASE WHEN pair_mayhem AND prev_k > 0
                           THEN abs(k - prev_k) / prev_k END, 0.50) AS bm_p50,
    approx_percentile(CASE WHEN pair_mayhem AND prev_k > 0
                           THEN abs(k - prev_k) / prev_k END, 0.99) AS bm_p99,
    max(CASE WHEN pair_mayhem AND prev_k > 0
             THEN abs(k - prev_k) / prev_k END)                     AS bm_max,
    count_if(pair_mayhem AND prev_k > 0)                            AS bm_pairs,

    -- ---- where the matching mayhem pairs sit relative to the mayhem segment
    -- start: clustered at the boundary, or spread through the segment?
    approx_percentile(CASE WHEN pair_mayhem AND d_sol = exp_d_sol
                           THEN CAST(pos_in_mayhem AS double) END, 0.50) AS m_pos_match_p50,
    approx_percentile(CASE WHEN pair_mayhem AND d_sol = exp_d_sol
                           THEN CAST(pos_in_mayhem AS double) END, 0.90) AS m_pos_match_p90,
    approx_percentile(CASE WHEN pair_mayhem AND d_sol <> exp_d_sol
                           THEN CAST(pos_in_mayhem AS double) END, 0.50) AS m_pos_miss_p50,
    approx_percentile(CASE WHEN pair_mayhem AND d_sol <> exp_d_sol
                           THEN CAST(pos_in_mayhem AS double) END, 0.90) AS m_pos_miss_p90,
    count_if(pair_mayhem AND d_sol =  exp_d_sol AND pos_in_mayhem <= 1)  AS m_match_pos01,
    count_if(pair_mayhem AND d_sol <> exp_d_sol AND pos_in_mayhem <= 1)  AS m_miss_pos01,
    count_if(pair_mayhem AND d_sol =  exp_d_sol AND pos_in_mayhem > 10)  AS m_match_pos_gt10,
    count_if(pair_mayhem AND d_sol <> exp_d_sol AND pos_in_mayhem > 10)  AS m_miss_pos_gt10,

    -- ---- 1c ----
    (SELECT count(*) FROM firsts)                                    AS c_tokens_with_trades,
    (SELECT count_if(x_pre_first = 30000000000) FROM firsts)         AS c_first_at_30sol,
    (SELECT count(DISTINCT x_pre_first) FROM firsts)                 AS c_distinct_x0,

    -- ---- extra: curve-implied price vs realised price ----
    (SELECT count(*) FROM priced)                                    AS p_trades,
    (SELECT approx_percentile(abs(implied_units - CAST(units AS double))
                              / CAST(units AS double), 0.50) FROM priced) AS p_p50,
    (SELECT approx_percentile(abs(implied_units - CAST(units AS double))
                              / CAST(units AS double), 0.99) FROM priced) AS p_p99,
    (SELECT max(abs(implied_units - CAST(units AS double))
                / CAST(units AS double)) FROM priced)                AS p_max
FROM pairs
