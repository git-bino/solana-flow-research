-- Phase 0 — Dune cost-structure probe.  Counting only.
--
-- Goal: separate what credits are charged for — bytes scanned, rows returned,
-- or both.  Prior data points disagreed: 6,632,789 events were aggregated for
-- 2.78 credits (docs/phase0_burst_inventory.md) while §0.1 projected 691,084
-- credits for the same kind of data, via the published 20 credits/MB export rate.
--
-- The instrument that made this measurable: POST /api/v1/usage returns
-- {credits_used, credits_included, bytes_used, bytes_allowed} for the current
-- billing period.  It is not in the docs index we had read; it was found by
-- probing (GET returns 405, POST returns 200).  credits_included = 2500
-- confirms the Free plan is active, i.e. no Plus trial.
--
-- Cohort is the burst_inventory cohort; only the create-window end date moves.

-- ─────────────────────────────────────────────────────────────────────────────
-- MEASUREMENT A — scan cost with the result held at 2 rows.
-- sql/burst_inventory.sql is run verbatim three times, changing only:
--     AND evt_block_date <  DATE '2026-06-02'   -- 1-day cohort
--     AND evt_block_date <  DATE '2026-06-03'   -- 2-day cohort
--     AND evt_block_date <  DATE '2026-06-04'   -- 3-day cohort (already run)
-- Events read comes from the query's own einf columns.
-- ─────────────────────────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────────────────────────────────────
-- MEASUREMENT B — output cost at constant scan.  ORDER BY forces a full scan
-- and sort regardless of LIMIT, so LIMIT cannot short-circuit the read; the
-- only thing varying is how much result is materialised.
-- Run with n = 100, 10000, 100000 for the 3-column select, and n = 100000 for
-- the 15-column select.
-- ─────────────────────────────────────────────────────────────────────────────
WITH created AS (
    SELECT mint, min(evt_block_time) AS launch_time
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-06-01' AND evt_block_date < DATE '2026-06-02'
      AND quote_mint = '11111111111111111111111111111111'
    GROUP BY mint
),
ev AS (
    SELECT c.mint, t.evt_block_time AS bt, t.evt_block_slot AS slot,
           t.evt_tx_index AS txi,
           coalesce(t.evt_outer_instruction_index,0)*64
             + coalesce(t.evt_inner_instruction_index,0) AS ixi,
           t.is_buy,
           CAST(t.sol_amount AS double)/1e9            AS sol,
           CAST(t.token_amount AS double)/1e6          AS tok,
           CAST(t.virtual_sol_reserves AS double)/1e9  AS x,
           CAST(t.virtual_token_reserves AS double)/1e6 AS y,
           CAST(t.fee AS double)/1e9                   AS fee,
           CAST(t.creator_fee AS double)/1e9           AS cfee,
           coalesce(t.mayhem_mode,false)               AS mayhem,
           t.user   AS wallet,
           t.evt_tx_id AS txid
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN created c ON t.mint = c.mint
    WHERE t.evt_block_date >= DATE '2026-06-01'
      AND t.evt_block_date <= DATE '2026-06-11'
      AND t.evt_block_time <  TIMESTAMP '2026-06-11 23:59:00'
      AND t.quote_mint = '11111111111111111111111111111111'
)
-- 3-column variant:
SELECT mint, slot, txi FROM ev ORDER BY slot, txi, ixi LIMIT 100000
-- 15-column variant (same CTEs):
-- SELECT mint, bt, slot, txi, ixi, is_buy, sol, tok, x, y, fee, cfee, mayhem,
--        wallet, txid FROM ev ORDER BY slot, txi, ixi LIMIT 100000
;

-- ─────────────────────────────────────────────────────────────────────────────
-- MEASUREMENT C — retrieval.  No SQL: the two executions produced by B are
-- re-read through
--     GET /api/v1/execution/{id}/results       (paginated JSON, limit+offset)
--     GET /api/v1/execution/{id}/results/csv   (single request)
-- with POST /api/v1/usage polled before and after each.  Ladder 100 -> 1,000 ->
-- 10,000 first, so the published-rate hypothesis could be falsified cheaply
-- before spending on the 100,000-row retrievals.
-- ─────────────────────────────────────────────────────────────────────────────
