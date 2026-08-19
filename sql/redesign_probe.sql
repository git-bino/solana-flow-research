-- Re-extract design probes (2026-08-19).  AGGREGATE ONLY, no rows exported.
--
-- Cell unless stated: launch [2026-06-06, 2026-06-15) (chunk 4's window, the
-- middle of the dev range), events to 2026-08-15 23:59, universe filter
-- createevent.virtual_sol_reserves = 30000000000.
--
-- Every probe below ran through ONE reusable saved query: the account is at its
-- private-query cap, so a new saved query per probe returns 402.
--
-- STATE (updated 2026-08-20, API restored on a 4,000-credit cycle):
--   A1, B1, B2, C  ran 2026-08-19.
--   D windows 3 and 5  ran and PASSED (23.141 + 18.200 credits).
--   E + F  ran as one pass (3.365 credits).
--   A2  FAILED: Dune's 30-minute execution limit, 164.755 credits for no result.
--       The query as written is kept below with the post-mortem attached.


-- ===========================================================================
-- A1 / B1 — what exists.  Metadata only, ~0.5 credits for all of it.
-- `information_schema` is deliberately avoided: a LIKE over it once ran to the
-- 30-minute limit and cost 180 credits for nothing (docs/phase0_measurements.md).
-- ===========================================================================
SHOW SCHEMAS;
SHOW TABLES FROM spl_token_solana;
SHOW TABLES FROM tokens_solana;
SHOW TABLES FROM solana_utils;
SHOW TABLES FROM solana;
DESCRIBE tokens_solana.spl_token_transfers;
DESCRIBE solana_utils.token_accounts;
DESCRIBE solana_utils.daily_balances;
DESCRIBE solana_utils.latest_balances;


-- ===========================================================================
-- A2 calibration — one day of the transfers table, to size the real probe.
-- ===========================================================================
SELECT count(*) AS transfers_1day,
       count(DISTINCT token_mint_address) AS mints,
       count(DISTINCT outer_executing_account) AS distinct_outer_programs,
       count_if(action = 'transfer') AS action_transfer,
       count_if(inner_instruction_index IS NULL) AS inner_null,
       max(inner_instruction_index) AS inner_max,
       max(outer_instruction_index) AS outer_max
FROM tokens_solana.spl_token_transfers
WHERE block_date = DATE '2026-06-10';


-- ===========================================================================
-- C — raw (outer, inner) and whether the packing collides.  RAN: 8.755 credits.
-- ===========================================================================
WITH sel AS (
    SELECT mint FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-06-06' AND evt_block_date < DATE '2026-06-15'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
ev AS (
    SELECT s.mint, t.evt_block_slot AS slot, t.evt_tx_index AS txi,
           t.evt_outer_instruction_index AS o, t.evt_inner_instruction_index AS i
    FROM pumpdotfun_solana.pump_evt_tradeevent t JOIN sel s ON t.mint = s.mint
    WHERE t.evt_block_date >= DATE '2026-06-06' AND t.evt_block_date <= DATE '2026-08-15'
      AND t.evt_block_time < TIMESTAMP '2026-08-15 23:59:00'
),
grp AS (
    -- one group per packed key; `n_raw_pairs` > 1 means the packing lost information
    SELECT mint, slot, txi,
           coalesce(o,0)*64 + coalesce(i,0) AS packed,
           count(*) AS n_rows,
           count(DISTINCT coalesce(o,-1)*100000 + coalesce(i,-1)) AS n_raw_pairs
    FROM ev GROUP BY 1,2,3,4
)
SELECT (SELECT count(*) FROM ev)                        AS events,
       (SELECT max(i) FROM ev)                          AS inner_max,
       (SELECT max(o) FROM ev)                          AS outer_max,
       (SELECT count_if(i IS NULL) FROM ev)             AS inner_null,
       (SELECT count_if(o IS NULL) FROM ev)             AS outer_null,
       (SELECT count_if(i >= 64) FROM ev)               AS inner_ge_64,
       (SELECT approx_percentile(CAST(i AS double), 0.50) FROM ev) AS inner_p50,
       (SELECT approx_percentile(CAST(i AS double), 0.99) FROM ev) AS inner_p99,
       (SELECT approx_percentile(CAST(o AS double), 0.99) FROM ev) AS outer_p99,
       count(*)                                         AS packed_keys,
       count_if(n_raw_pairs > 1)                        AS packed_keys_with_collision,
       count_if(n_rows > 1)                             AS packed_keys_with_multiple_rows,
       sum(n_raw_pairs)                                 AS raw_keys
FROM grp;


-- ===========================================================================
-- D — KILL gate 1a/1b/1c for launch windows 3 and 5.  Body is
-- sql/phase0_kill_gate.sql verbatim, only the two date literals substituted:
--     window 3: [2026-05-28, 2026-06-06)
--     window 5: [2026-06-15, 2026-06-24)
-- Window 3 FAILED after 14.424 credits: "Query execution has exceeded the user
-- defined maximum amount of resources".  The same query completed on 2026-08-18
-- at performance=medium for windows 2, 4 and 6.  Window 5 was never reached.
-- ===========================================================================


-- ===========================================================================
-- E + F — one pass serving both.  WRITTEN, NOT RUN (datapoint limit).
-- E: does createevent.is_mayhem_mode agree with the trade-side max over the
--    whole dev launch window, not just the trade-active probe cohort.
-- F: every distinct declared virtual_sol_reserves, with quote and activity
--    breakdown — purity was established, completeness was not.
-- Scope: launch [2026-05-10, 2026-07-03), events to 2026-08-15 23:59, and
--    deliberately NO x0 filter, since the point is what the filter excludes.
-- ===========================================================================
WITH cre AS (
    SELECT mint,
           max(CAST(virtual_sol_reserves AS bigint)) AS x0,
           bool_or(is_mayhem_mode) AS create_mayhem
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-07-03'
    GROUP BY mint
),
tr AS (
    SELECT t.mint,
           count(*) AS n_trades,
           bool_or(coalesce(t.mayhem_mode, false)) AS trade_mayhem,
           count_if(t.mayhem_mode IS NULL) AS mayhem_null_rows,
           max(t.quote_mint) AS trade_quote
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN cre c ON t.mint = c.mint
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
      AND t.evt_block_time < TIMESTAMP '2026-08-15 23:59:00'
    GROUP BY t.mint
),
tok AS (
    SELECT c.mint, c.x0, c.create_mayhem,
           coalesce(t.n_trades, 0) AS n_trades,
           t.trade_mayhem, coalesce(t.mayhem_null_rows, 0) AS mayhem_null_rows,
           t.trade_quote
    FROM cre c LEFT JOIN tr t ON t.mint = c.mint
)
SELECT x0,
       count(*)                                            AS tokens,
       count_if(n_trades > 0)                              AS tokens_with_trades,
       count_if(n_trades = 0)                              AS tokens_without_trades,
       count_if(create_mayhem)                             AS create_mayhem_tokens,
       count_if(n_trades = 0 AND create_mayhem)            AS no_trade_and_mayhem,
       -- E: the reconciliation the audit asked for
       count_if(n_trades > 0 AND create_mayhem <> trade_mayhem) AS mayhem_disagreements,
       sum(mayhem_null_rows)                               AS trade_rows_with_null_mayhem,
       sum(n_trades)                                       AS trade_rows,
       -- F: quote breakdown within each declared reserve
       count_if(trade_quote IS NULL AND n_trades > 0)      AS quote_null_active,
       count_if(trade_quote = '11111111111111111111111111111111') AS quote_sol,
       count_if(trade_quote IS NOT NULL
                AND trade_quote <> '11111111111111111111111111111111') AS quote_other
FROM tok
GROUP BY x0
ORDER BY tokens DESC;


-- ===========================================================================
-- A2 — transfers on pump.fun curve tokens.  RAN 2026-08-20, FAILED at Dune's
-- 30-minute execution limit after 164.755 credits.  Kept verbatim as the thing
-- that failed, not repaired here.
--
-- EXCLUSION RULE (unchanged): a pump.fun trade moves SPL tokens itself, so the
-- curve's own legs are dropped by `outer_executing_account`.  Legs invoked by
-- other AMMs are deliberately kept -- they are real movements of a holder's
-- balance away from the curve (decisions.md).  `keep` is a column rather than a
-- WHERE clause so the before/after counts come from one scan.
--
-- POST-MORTEM, stated as a hypothesis and NOT measured (measuring it costs
-- another run): the final SELECT issues twelve independent scalar subqueries
-- over the `xf` CTE plus a UNION ALL that doubles it.  Trino does not guarantee
-- a CTE is materialised once, so the 71-day scan of
-- tokens_solana.spl_token_transfers may have been repeated per subquery.  A
-- single aggregation pass would be the obvious rewrite.
--
-- `_dummy` in the projection is a leftover and should not be there.
-- ===========================================================================
WITH sel AS (
    SELECT mint FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-06-06' AND evt_block_date < DATE '2026-06-15'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
-- One scan.  `keep` marks the rows that survive the pump.fun exclusion, so the
-- before/after counts come from the same pass.
xf AS (
    SELECT x.token_mint_address AS mint,
           x.from_owner, x.to_owner,
           CAST(x.amount AS double) AS amount,
           x.outer_executing_account AS prog,
           x.block_slot AS slot, x.tx_index AS txi,
           coalesce(x.outer_instruction_index,0) AS oix,
           coalesce(x.inner_instruction_index,0) AS iix,
           x.outer_executing_account <> '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
             AS keep
    FROM tokens_solana.spl_token_transfers x
    JOIN sel s ON x.token_mint_address = s.mint
    WHERE x.block_date >= DATE '2026-06-06' AND x.block_date <= DATE '2026-08-15'
      AND x.block_time < TIMESTAMP '2026-08-15 23:59:00 UTC'
      AND x.action = 'transfer'
),
progs AS (
    SELECT prog, count(*) AS n,
           row_number() OVER (ORDER BY count(*) DESC) AS rk
    FROM xf GROUP BY prog
),
-- Per (mint, owner): did it receive before it sent?  min(incoming key) <
-- max(outgoing key) is a NECESSARY condition for forwarding received tokens,
-- not a sufficient one: the outgoing amount could be tokens bought on the
-- curve.  Reported as an UPPER BOUND on chain length.
own AS (
    SELECT mint, owner,
           max(if(dir = 1, k)) AS max_out,
           min(if(dir = 0, k)) AS min_in,
           count_if(dir = 1) AS n_out,
           count_if(dir = 0) AS n_in
    FROM (
        SELECT mint, to_owner AS owner, 0 AS dir,
               (slot, txi, oix, iix) AS k FROM xf WHERE keep
        UNION ALL
        SELECT mint, from_owner AS owner, 1 AS dir,
               (slot, txi, oix, iix) AS k FROM xf WHERE keep
    ) GROUP BY mint, owner
),
per_owner_token AS (
    SELECT mint, owner, n_in + n_out AS n_xf FROM own
)
SELECT
    (SELECT count(*) FROM xf)                                   AS transfers_before_exclusion,
    (SELECT count_if(keep) FROM xf)                             AS transfers_after_exclusion,
    (SELECT count(DISTINCT mint) FROM xf)                       AS tokens_before,
    (SELECT count_if(keep) FROM xf WHERE true)                  AS _dummy,
    (SELECT count(DISTINCT mint) FROM xf WHERE keep)            AS tokens_after,
    (SELECT count(DISTINCT owner) FROM own)                     AS owners_after,
    (SELECT approx_percentile(amount / 1073000000000000.0, 0.50) FROM xf WHERE keep) AS amt_over_y0_p50,
    (SELECT approx_percentile(amount / 1073000000000000.0, 0.90) FROM xf WHERE keep) AS amt_over_y0_p90,
    (SELECT max(amount / 1073000000000000.0) FROM xf WHERE keep)                     AS amt_over_y0_max,
    (SELECT approx_percentile(CAST(n_xf AS double), 0.50) FROM per_owner_token)      AS xf_per_owner_token_p50,
    (SELECT approx_percentile(CAST(n_xf AS double), 0.90) FROM per_owner_token)      AS xf_per_owner_token_p90,
    (SELECT max(n_xf) FROM per_owner_token)                                          AS xf_per_owner_token_max,
    (SELECT count(*) FROM own WHERE n_in > 0)                                        AS owners_that_received,
    (SELECT count(*) FROM own WHERE n_in > 0 AND n_out > 0 AND max_out > min_in)     AS owners_that_forwarded,
    (SELECT array_agg(ROW(prog, n) ORDER BY n DESC) FROM progs WHERE rk <= 20)       AS top20_programs,
    (SELECT sum(n) FROM progs WHERE prog = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P') AS pumpfun_rows,
    (SELECT count(*) FROM progs)                                                     AS distinct_programs

