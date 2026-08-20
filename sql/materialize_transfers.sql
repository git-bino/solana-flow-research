-- Transfer materialisation for extract_v2's `xf` CTE.  WRITTEN, NOT RUN.
--
-- Purpose: `tokens_solana.spl_token_transfers` partitions only on `block_date`,
-- so filtering to our mints does not shrink the scan -- 71 days is ~6.9 billion
-- rows however few of them survive.  extract_v2 references `xf` three times, so
-- the full extract would pay that scan up to three times.  Materialising the
-- filtered rows once turns each of those references into a small read.
--
-- The output is small, and that is measured rather than assumed
-- (docs/transfer_materialization.md, 2026-08-20): on 2026-06-06 the dev-window
-- mints carry 7,269 transfers, of which 963 are pump.fun's own legs and 6,306
-- survive, touching 71 distinct mints.  Over 71 days that extrapolates to about
-- 447,726 rows at ~159.5 B, i.e. **0.071 GB** -- well inside a 1 GB budget.
--
-- EXCLUSION RULE: a pump.fun trade moves SPL tokens itself, so the curve's own
-- legs appear here and are dropped by `outer_executing_account`.  Legs invoked
-- by other AMMs are deliberately kept: they are real movements of a holder's
-- balance away from the curve (decisions.md).
--
-- Run once per 9-day slice of the transfer window, then union the slices.

SELECT x.block_slot                             AS block_slot,
       x.tx_index                               AS tx_index,
       coalesce(x.outer_instruction_index, 0)   AS outer_ix_index,
       coalesce(x.inner_instruction_index, 0)   AS inner_ix_index,
       x.token_mint_address                     AS token_mint_address,
       x.from_owner                             AS from_owner,
       x.to_owner                               AS to_owner,
       CAST(x.amount AS bigint)                 AS amount
FROM tokens_solana.spl_token_transfers x
JOIN (
    SELECT mint FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10'
      AND evt_block_date <  DATE '2026-07-03'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
) s ON x.token_mint_address = s.mint
WHERE x.block_date >= DATE '{{SLICE_FROM}}'
  AND x.block_date <  DATE '{{SLICE_TO}}'
  AND x.action = 'transfer'
  AND x.outer_executing_account <> '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
  AND x.from_owner <> x.to_owner
