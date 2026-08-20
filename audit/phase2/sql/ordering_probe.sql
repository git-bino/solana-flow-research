-- Phase 0 ordering-key probe (spec §2.4, decisions.md).
--
-- Question: on bigquery-public-data.crypto_solana_mainnet_us.Instructions, is
-- `index` unique within a block (block_slot), or is it numbered within each
-- transaction?  The answer decides whether (block_slot, index) can serve as the
-- ordering key, or whether a transaction-level index is still required.
--
-- Scope: one day (2026-06-02), pump.fun program only.  Columns deliberately
-- limited to block_slot, index, parent_index — `accounts`, `data` and
-- tx_signature are excluded because they dominate scan cost (see
-- docs/phase0_bigquery_dryrun.md).  tx_signature is added only in Q3, and only
-- if Q1 shows duplicate (block_slot, index) pairs.
--
-- requirePartitionFilter=True: the block_timestamp filter is mandatory.

-- ─────────────────────────────────────────────────────────────────────────────
-- Q1 — A, B, C(partial), D, E, F, G aggregates in one pass
-- ─────────────────────────────────────────────────────────────────────────────
WITH ix AS (
  SELECT block_slot, `index`, parent_index
  FROM `bigquery-public-data.crypto_solana_mainnet_us.Instructions`
  WHERE block_timestamp >= TIMESTAMP '2026-06-02'
    AND block_timestamp <  TIMESTAMP '2026-06-03'
    AND program_id = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
),
pair AS (
  SELECT block_slot, `index`, COUNT(*) AS c
  FROM ix GROUP BY 1, 2
),
per_slot AS (
  SELECT block_slot,
         COUNT(*) AS n,
         MIN(`index`) AS mn,
         MAX(`index`) AS mx,
         COUNT(DISTINCT `index`) AS dix
  FROM ix GROUP BY 1
)
SELECT
  -- A. total pump.fun instruction rows that day
  (SELECT COUNT(*) FROM ix)                                    AS a_rows,
  -- B. is (block_slot, index) unique?
  (SELECT COUNT(*) FROM pair)                                  AS b_distinct_pairs,
  -- C. if not, how many rows share a pair
  (SELECT MAX(c) FROM pair)                                    AS c_max_per_pair,
  (SELECT APPROX_QUANTILES(c, 100)[OFFSET(50)] FROM pair)      AS c_p50_per_pair,
  (SELECT APPROX_QUANTILES(c, 100)[OFFSET(99)] FROM pair)      AS c_p99_per_pair,
  (SELECT COUNTIF(c > 1) FROM pair)                            AS c_pairs_duplicated,
  (SELECT IFNULL(SUM(c), 0) FROM pair WHERE c > 1)             AS c_rows_in_dup_pairs,
  -- D. parent_index null vs not null  (not null => inner/CPI instruction)
  (SELECT COUNTIF(parent_index IS NULL) FROM ix)               AS d_parent_null,
  (SELECT COUNTIF(parent_index IS NOT NULL) FROM ix)           AS d_parent_not_null,
  -- E. pump.fun instructions per block
  (SELECT APPROX_QUANTILES(n, 100)[OFFSET(50)] FROM per_slot)  AS e_per_block_p50,
  (SELECT APPROX_QUANTILES(n, 100)[OFFSET(99)] FROM per_slot)  AS e_per_block_p99,
  (SELECT MAX(n) FROM per_slot)                                AS e_per_block_max,
  -- F. distinct blocks
  (SELECT COUNT(*) FROM per_slot)                              AS f_distinct_slots,
  -- G. index value range and contiguity within a block
  (SELECT MIN(mn) FROM per_slot)                               AS g_index_min,
  (SELECT MAX(mx) FROM per_slot)                               AS g_index_max,
  (SELECT COUNTIF(mn = 0) FROM per_slot)                       AS g_slots_starting_at_0,
  (SELECT COUNTIF(mx - mn + 1 = dix) FROM per_slot)            AS g_slots_index_contiguous,
  (SELECT COUNTIF(dix < n) FROM per_slot)                      AS g_slots_with_repeated_index
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Q2 — G example: every pump.fun row of one busy block, ordered
-- ─────────────────────────────────────────────────────────────────────────────
WITH ix AS (
  SELECT block_slot, `index`, parent_index
  FROM `bigquery-public-data.crypto_solana_mainnet_us.Instructions`
  WHERE block_timestamp >= TIMESTAMP '2026-06-02'
    AND block_timestamp <  TIMESTAMP '2026-06-03'
    AND program_id = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
),
target AS (
  SELECT block_slot FROM ix GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1
)
SELECT i.block_slot, i.`index`, i.parent_index
FROM ix i JOIN target t USING (block_slot)
ORDER BY i.`index`, i.parent_index
LIMIT 20
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Q3 — C: do rows sharing a (block_slot, index) belong to different transactions?
-- Run only if Q1 shows b_distinct_pairs < a_rows.  Adds tx_signature, which is
-- the second most expensive column in this table, so it is isolated here.
-- ─────────────────────────────────────────────────────────────────────────────
WITH ix AS (
  SELECT block_slot, `index`, tx_signature
  FROM `bigquery-public-data.crypto_solana_mainnet_us.Instructions`
  WHERE block_timestamp >= TIMESTAMP '2026-06-02'
    AND block_timestamp <  TIMESTAMP '2026-06-03'
    AND program_id = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
),
pair AS (
  SELECT block_slot, `index`,
         COUNT(*) AS c,
         COUNT(DISTINCT tx_signature) AS d_tx
  FROM ix GROUP BY 1, 2
)
SELECT
  COUNT(*)                                              AS pairs,
  COUNTIF(c > 1)                                        AS pairs_duplicated,
  COUNTIF(c > 1 AND d_tx = c)                           AS dup_pairs_all_distinct_tx,
  COUNTIF(c > 1 AND d_tx < c)                           AS dup_pairs_with_repeated_tx,
  MAX(d_tx)                                             AS max_distinct_tx_per_pair,
  (SELECT COUNT(DISTINCT tx_signature) FROM ix)         AS distinct_tx_total,
  (SELECT COUNT(*) FROM ix)                             AS rows_total
FROM pair
;
