-- pump.fun bonding-curve SPL token transfers -- research ledger input
--
-- PURPOSE.  Wallet-to-wallet SPL transfers on pump.fun bonding-curve tokens.
-- A cost-basis ledger built from TradeEvent alone is blind to these: tokens move
-- without a trade, so a sender keeps credit for a balance it no longer holds and
-- a recipient that sells goes negative.  This query supplies the missing rows.
--
-- SCOPE.  Tokens created in [2026-05-10, 2026-07-03) whose createevent declares
-- virtual_sol_reserves = 30000000000 (the SOL-quote curve).  Transfers over the
-- event window [2026-05-10, 2026-08-15 23:59 UTC), i.e. 98 `block_date`
-- partitions.  Built as a MATERIALIZED VIEW, one per slice.
--
-- EXCLUSION.  A pump.fun trade moves SPL tokens itself, so the curve's own legs
-- appear in this table and are dropped by outer_executing_account.  Legs invoked
-- by other AMMs and routers are deliberately KEPT: they are real movements of a
-- holder's balance away from the curve.
--
-- Date: 2026-08-19 (header), 2026-08-20 (materialized-view rewrite)
--
-- WHY MATERIALISE.  `tokens_solana.spl_token_transfers` partitions only on
-- `block_date`, so filtering to our mints does not shrink the scan -- the event
-- window is ~6.9 billion rows however few of them survive.  extract_v2
-- references `xf` three times, so the full extract would pay that scan up to
-- three times.
--
-- A saved query is NOT a way to avoid that: `query_<id>` inlines the query text
-- and re-executes it (measured 2026-08-20 -- a stored result of 1 read back as 2
-- after the text was edited without being run).  A Dune MATERIALIZED VIEW is a
-- real table: the same marker test read back 1 after the source text was changed
-- to 2, and only changed to 2 once the view was explicitly refreshed.
--
-- THE 23:59 CUT IS BAKED IN.  extract_v2's `xf` bounds the window with
-- `block_time < TIMESTAMP '{{EVENT_TO}} 23:59:00 UTC'`, but `block_time` is not
-- among the nine projected columns, so a consumer of this table cannot apply it.
-- It is therefore applied here.  This is exact rather than approximate because
-- `{{EVENT_TO}}` is the same literal (2026-08-15) in every extract chunk -- only
-- the launch bounds move -- so one baked cut serves all of them.  Consumers
-- still re-apply their own `block_date >= {{LAUNCH_FROM}}` lower bound.
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (a column list without block_time leaves no
-- other way to preserve extract_v2's semantics).
--
-- ALL COLUMNS ARE EXPLICITLY NAMED, as the materialized-view API requires;
-- there is no `SELECT *` anywhere in this statement.
--
-- SLICE SIZE.  A 9-day slice fails with "Query exceeds cluster capacity
-- (memory/pages)" both as a plain query and as a materialized view -- the view
-- relaxes the limit for *readers*, not for the statement that builds it.  Six
-- days works; the window is 16 six-day slices plus a two-day tail, one
-- materialized view each, unioned in sql/xf_union.sql.  Slices are NOT
-- refreshable into one table: refresh is a full rebuild, not an append.
--
-- SIZE, built and counted rather than assumed
-- (docs/transfer_materialization.md, 2026-08-20): 1,773,265 rows over 98
-- block_date partitions, 39,189,151 bytes stored = 22.1 B/row -- the stored form
-- is compressed roughly 7x against the 160 B/row uncompressed result set, so
-- table_size_bytes is not a row proxy.  That is 3.65% of the 1 GB Analyst quota.
-- Total build cost 140.34 credits, i.e. 1.43 credits per block_date partition;
-- cost tracks the partition scan, not the surviving row count (a 561,444-row
-- slice and a 32,792-row slice both cost ~7.1).

SELECT x.block_slot                             AS block_slot,
       x.tx_index                               AS tx_index,
       coalesce(x.outer_instruction_index, 0)   AS outer_ix_index,
       coalesce(x.inner_instruction_index, 0)   AS inner_ix_index,
       x.token_mint_address                     AS token_mint_address,
       x.from_owner                             AS from_owner,
       x.to_owner                               AS to_owner,
       CAST(x.amount AS bigint)                 AS amount,
       x.block_date                             AS block_date
FROM tokens_solana.spl_token_transfers x
JOIN (
    SELECT mint FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10'
      AND evt_block_date <  DATE '2026-07-03'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
) s ON x.token_mint_address = s.mint
WHERE x.block_date >= DATE '{{SLICE_FROM}}'
  AND x.block_date <= DATE '{{SLICE_TO}}'
  AND x.block_time <  TIMESTAMP '2026-08-15 23:59:00 UTC'
  AND x.action = 'transfer'
  AND x.outer_executing_account <> '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
  AND x.from_owner <> x.to_owner
