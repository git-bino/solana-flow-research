-- Re-extract design probes (2026-08-19).  AGGREGATE ONLY, no rows exported.
--
-- Cell unless stated: launch [2026-06-06, 2026-06-15) (chunk 4's window, the
-- middle of the dev range), events to 2026-08-15 23:59, universe filter
-- createevent.virtual_sol_reserves = 30000000000.
--
-- Every probe below ran through ONE reusable saved query: the account is at its
-- private-query cap, so a new saved query per probe returns 402.
--
-- STATE: A1, B1, C ran.  D (windows 3, 5) failed on a Dune resource limit.
-- A2, B2-cost, E, F are written but NOT run: the API began refusing executions
-- with "would exceed your configured datapoint limit per billing cycle".


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
-- A2 — transfers on pump.fun curve tokens.  WRITTEN, NOT RUN.
-- DEX-internal legs are excluded by `outer_executing_account`: a swap's token
-- movement is invoked by the AMM/router program, so restricting to transfers
-- whose outer executing account is NOT a program isolates wallet-to-wallet
-- moves.  The pump.fun program itself is excluded by name.
-- Window deliberately equal in LENGTH to the trade-side anchor (decisions.md,
-- 2026-08-18), which is why both sides read the same date range.
-- ===========================================================================
WITH sel AS (
    SELECT mint FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-06-06' AND evt_block_date < DATE '2026-06-15'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
xf AS (
    SELECT x.token_mint_address AS mint, x.from_owner, x.to_owner, x.amount,
           x.outer_executing_account
    FROM tokens_solana.spl_token_transfers x
    JOIN sel s ON x.token_mint_address = s.mint
    WHERE x.block_date >= DATE '2026-06-06' AND x.block_date <= DATE '2026-08-15'
      AND x.action = 'transfer'
      AND x.outer_executing_account <> '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
)
SELECT count(*)                              AS transfers,
       count(DISTINCT mint)                  AS tokens_touched,
       count(DISTINCT from_owner)            AS senders,
       count(DISTINCT to_owner)              AS recipients,
       approx_percentile(CAST(amount AS double) / 1e6, 0.50) AS amount_tokens_p50,
       approx_percentile(CAST(amount AS double) / 1e6, 0.90) AS amount_tokens_p90
FROM xf;
