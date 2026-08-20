-- Phase 0 — verification of the "quote_mint NULL = SOL" reading.
--
-- Context: dev chunk 01 was extracted after treating NULL quote_mint as SOL for
-- [2026-05-10, 2026-05-21).  This file tests that reading in the form of §7's
-- check 1a — the reserve series has to be internally consistent — with a control
-- on the period where quote_mint IS named, split by quote asset.
--
-- Aggregates only, no rows exported.  Split into four queries so each stays
-- inside the per-query credit guard.
--
-- The discriminating check is C / the initial reserve.  A, B and D would look the
-- same for a USDC curve, because for such a curve `sol_amount` is a USDC amount
-- and `virtual_sol_reserves` is the virtual QUOTE reserve — the arithmetic
-- Δreserve = ±amount still holds.  What cannot look the same is the magnitude of
-- the initial reserve: a SOL curve starts at 30 SOL = 3e10 lamports, a curve
-- quoted in a 6-decimal asset cannot.

-- ─────────────────────────────────────────────────────────────────────────────
-- Q1 — A, B, C, D on the NULL period (2026-05-10 .. 2026-05-19)
-- ─────────────────────────────────────────────────────────────────────────────
WITH creates AS (
    SELECT mint, min(evt_block_time) AS created_at,
           max(CAST(virtual_sol_reserves AS decimal(38,0)))   AS c_x0,
           max(CAST(virtual_token_reserves AS decimal(38,0))) AS c_y0
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
ev AS (
    SELECT t.mint,
           t.evt_block_slot AS slot, t.evt_tx_index AS txi,
           coalesce(t.evt_outer_instruction_index,0)*64
             + coalesce(t.evt_inner_instruction_index,0) AS ixi,
           CAST(t.virtual_sol_reserves   AS decimal(38,0)) AS vsol,
           CAST(t.virtual_token_reserves AS decimal(38,0)) AS vtok,
           CAST(t.sol_amount   AS decimal(38,0)) AS sol,
           CAST(t.token_amount AS decimal(38,0)) AS tok,
           t.is_buy, coalesce(t.mayhem_mode, false) AS mayhem,
           t.quote_mint
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN creates c ON c.mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date < DATE '2026-05-19'
),
seq AS (
    SELECT *,
           lag(vsol) OVER w AS prev_vsol,
           lag(vtok) OVER w AS prev_vtok,
           lag(vsol * vtok) OVER w AS prev_k,
           vsol * vtok AS k,
           row_number() OVER w AS rn
    FROM ev
    WINDOW w AS (PARTITION BY mint ORDER BY slot, txi, ixi)
),
pairs AS (
    SELECT mayhem,
           vsol - prev_vsol AS d_sol,
           vtok - prev_vtok AS d_tok,
           CASE WHEN is_buy THEN sol ELSE -sol END AS want_sol,
           CASE WHEN is_buy THEN -tok ELSE tok END AS want_tok,
           abs(CAST(k - prev_k AS double) / CAST(prev_k AS double)) AS k_rel
    FROM seq WHERE prev_vsol IS NOT NULL
),
firsts AS (
    SELECT count(*) AS n_first,
           count_if(vsol - (CASE WHEN is_buy THEN sol ELSE -sol END)
                    = CAST(30000000000 AS decimal(38,0))) AS first_x0_is_30sol,
           count(DISTINCT CAST(vsol - (CASE WHEN is_buy THEN sol ELSE -sol END) AS varchar))
               AS distinct_implied_x0,
           count_if(quote_mint IS NULL) AS first_rows_quote_null
    FROM seq WHERE rn = 1
)
SELECT 'NULL period 05-10..05-19' AS period,
       count_if(NOT mayhem)                              AS plain_pairs,
       count_if(NOT mayhem AND d_sol = want_sol)         AS a_sol_side_exact,
       count_if(NOT mayhem AND d_tok = want_tok)         AS b_token_side_exact,
       count_if(mayhem)                                  AS mayhem_pairs,
       count_if(mayhem AND d_sol = want_sol)             AS mayhem_sol_exact,
       approx_percentile(if(NOT mayhem, k_rel), 0.50)    AS d_k_rel_p50,
       approx_percentile(if(NOT mayhem, k_rel), 0.99)    AS d_k_rel_p99,
       max(if(NOT mayhem, k_rel))                        AS d_k_rel_max,
       max(f.n_first) AS n_first, max(f.first_x0_is_30sol) AS c_first_x0_is_30sol,
       max(f.distinct_implied_x0) AS c_distinct_implied_x0,
       max(f.first_rows_quote_null) AS c_first_rows_quote_null
FROM pairs CROSS JOIN firsts f
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Q2 — E: the same checks on the NAMED period (2026-05-21 .. 2026-05-30),
-- grouped by quote asset.  This is the control.
-- ─────────────────────────────────────────────────────────────────────────────
WITH creates AS (
    SELECT mint, min(quote_mint) AS quote_mint,
           max(CAST(virtual_sol_reserves AS decimal(38,0))) AS c_x0
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-21' AND evt_block_date < DATE '2026-05-30'
    GROUP BY mint
),
ev AS (
    SELECT t.mint,
           CASE WHEN c.quote_mint = '11111111111111111111111111111111' THEN 'SOL'
                WHEN c.quote_mint = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v' THEN 'USDC'
                WHEN c.quote_mint IS NULL THEN 'NULL'
                ELSE 'OTHER' END AS quote_class,
           t.evt_block_slot AS slot, t.evt_tx_index AS txi,
           coalesce(t.evt_outer_instruction_index,0)*64
             + coalesce(t.evt_inner_instruction_index,0) AS ixi,
           CAST(t.virtual_sol_reserves   AS decimal(38,0)) AS vsol,
           CAST(t.virtual_token_reserves AS decimal(38,0)) AS vtok,
           CAST(t.sol_amount   AS decimal(38,0)) AS sol,
           CAST(t.token_amount AS decimal(38,0)) AS tok,
           t.is_buy, coalesce(t.mayhem_mode, false) AS mayhem
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN creates c ON c.mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-21' AND t.evt_block_date < DATE '2026-05-30'
),
seq AS (
    SELECT *, lag(vsol) OVER w AS prev_vsol, lag(vtok) OVER w AS prev_vtok,
              lag(vsol*vtok) OVER w AS prev_k, vsol*vtok AS k,
              row_number() OVER w AS rn
    FROM ev WINDOW w AS (PARTITION BY mint ORDER BY slot, txi, ixi)
)
SELECT quote_class,
       count_if(prev_vsol IS NOT NULL AND NOT mayhem) AS plain_pairs,
       count_if(prev_vsol IS NOT NULL AND NOT mayhem
                AND vsol - prev_vsol = CASE WHEN is_buy THEN sol ELSE -sol END) AS a_sol_exact,
       count_if(prev_vsol IS NOT NULL AND NOT mayhem
                AND vtok - prev_vtok = CASE WHEN is_buy THEN -tok ELSE tok END) AS b_tok_exact,
       count_if(rn = 1) AS n_first,
       count_if(rn = 1 AND vsol - (CASE WHEN is_buy THEN sol ELSE -sol END)
                = CAST(30000000000 AS decimal(38,0))) AS c_first_x0_is_30sol,
       -- prev_k = 0 would divide to NaN and approx_percentile rejects NaN, so the
       -- ratio is NULL there and simply drops out of the percentile.
       approx_percentile(CASE WHEN prev_vsol IS NOT NULL AND NOT mayhem AND prev_k > 0
           THEN abs(CAST(k - prev_k AS double)/CAST(prev_k AS double)) END, 0.50) AS d_k_rel_p50,
       approx_percentile(CASE WHEN prev_vsol IS NOT NULL AND NOT mayhem AND prev_k > 0
           THEN abs(CAST(k - prev_k AS double)/CAST(prev_k AS double)) END, 0.99) AS d_k_rel_p99
FROM seq GROUP BY quote_class ORDER BY 2 DESC
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Q3 — F: exact transition moment, daily NULL vs named counts around it, and
-- the initial-reserve distribution from createevent (cheap and discriminating).
-- ─────────────────────────────────────────────────────────────────────────────
SELECT evt_block_date AS d,
       count(*) AS creates,
       count_if(quote_mint IS NULL) AS quote_null,
       count_if(quote_mint IS NOT NULL) AS quote_named,
       min(if(quote_mint IS NOT NULL, evt_block_time)) AS first_named_time,
       count_if(CAST(virtual_sol_reserves AS decimal(38,0))
                = CAST(30000000000 AS decimal(38,0))) AS x0_is_30sol,
       count(DISTINCT CAST(virtual_sol_reserves AS varchar)) AS distinct_x0,
       count(DISTINCT quote_mint) AS distinct_quote
FROM pumpdotfun_solana.pump_evt_createevent
WHERE evt_block_date >= DATE '2026-05-14' AND evt_block_date <= DATE '2026-05-28'
GROUP BY 1 ORDER BY 1
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Q4 — G: which OTHER columns are wholly NULL in the NULL period.
-- ─────────────────────────────────────────────────────────────────────────────
SELECT count(*) AS rows_total,
       count_if(quote_mint IS NULL) AS quote_mint,
       count_if(sol_amount IS NULL) AS sol_amount,
       count_if(token_amount IS NULL) AS token_amount,
       count_if(virtual_sol_reserves IS NULL) AS virtual_sol_reserves,
       count_if(virtual_token_reserves IS NULL) AS virtual_token_reserves,
       count_if(real_sol_reserves IS NULL) AS real_sol_reserves,
       count_if(real_token_reserves IS NULL) AS real_token_reserves,
       count_if(fee IS NULL) AS fee,
       count_if(fee_basis_points IS NULL) AS fee_basis_points,
       count_if(fee_recipient IS NULL) AS fee_recipient,
       count_if(creator IS NULL) AS creator,
       count_if(creator_fee IS NULL) AS creator_fee,
       count_if(creator_fee_basis_points IS NULL) AS creator_fee_basis_points,
       count_if(mayhem_mode IS NULL) AS mayhem_mode,
       count_if(is_buy IS NULL) AS is_buy,
       count_if("user" IS NULL) AS user_col,
       count_if(mint IS NULL) AS mint,
       count_if(timestamp IS NULL) AS ts,
       count_if(quote_amount IS NULL) AS quote_amount,
       count_if(track_volume IS NULL) AS track_volume,
       count_if(current_sol_volume IS NULL) AS current_sol_volume,
       count_if(last_update_timestamp IS NULL) AS last_update_timestamp,
       count_if(total_claimed_tokens IS NULL) AS total_claimed_tokens,
       count_if(total_unclaimed_tokens IS NULL) AS total_unclaimed_tokens,
       count_if(buyback_fee IS NULL) AS buyback_fee,
       count_if(cashback IS NULL) AS cashback,
       count_if(solAmount IS NOT NULL) AS v1_camelcase_rows
FROM pumpdotfun_solana.pump_evt_tradeevent
WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
;
