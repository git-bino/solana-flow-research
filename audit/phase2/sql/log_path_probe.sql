-- Phase 0 — log_messages path probe (spec §2.1, decisions.md).
--
-- Context: Instructions carries only outer instructions (parent_index NULL on
-- 100% of rows, docs/phase0_ordering_probe.md), and pump.fun emits TradeEvent by
-- self-CPI, so the event payload is not in that table.  The remaining BigQuery
-- path is Transactions.log_messages.  This probe measures whether it works.
--
-- Scope: one day (2026-06-02), transactions whose logs mention the pump.fun
-- bonding-curve program.  Counting only: the first 8 bytes (Anchor event
-- discriminator) and the payload length are inspected, nothing is decoded.
--
-- LIMIT does not reduce scan in BigQuery, so everything below is folded into a
-- single query over the day's partition: one pass, one charge.
--
-- Discriminators are sha256("event:<Name>")[:8], computed locally
-- (src/config.py ANCHOR_EVENT_DISCRIMINATORS):
--   TradeEvent    bddb7fd34ee661ee      CompleteEvent  5f72619cd42e9808
--   CreateEvent   1b72a94ddeeb6376      MigrationEvent bde95db95c94ea94

WITH tx AS (
  SELECT block_slot,
         `index` AS tx_index,
         block_timestamp,
         log_messages
  FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`
  WHERE block_timestamp >= TIMESTAMP '2026-06-02'
    AND block_timestamp <  TIMESTAMP '2026-06-03'
    AND EXISTS (SELECT 1 FROM UNNEST(log_messages) AS l
                WHERE STRPOS(l, '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P') > 0)
),
flags AS (
  SELECT block_slot, tx_index, block_timestamp, log_messages,
         ARRAY_LENGTH(log_messages) AS n_log_lines,
         (SELECT COUNT(*) FROM UNNEST(log_messages) l
          WHERE STARTS_WITH(l, 'Program data: '))                       AS n_data_lines,
         (SELECT COUNT(*) FROM UNNEST(log_messages) l
          WHERE STRPOS(l, 'Log truncated') > 0) > 0                     AS truncated,
         -- self-CPI marker: the program invoking itself at depth >= 2
         (SELECT COUNT(*) FROM UNNEST(log_messages) l
          WHERE STRPOS(l, '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [2]') > 0
             OR STRPOS(l, '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [3]') > 0
         ) > 0                                                          AS self_cpi
  FROM tx
),
payload AS (
  SELECT f.block_slot, f.tx_index,
         REGEXP_EXTRACT(l, r'^Program data: (.+)$') AS b64
  FROM flags f, UNNEST(f.log_messages) AS l
  WHERE STARTS_WITH(l, 'Program data: ')
),
ev AS (
  SELECT block_slot, tx_index,
         TO_HEX(SUBSTR(SAFE.FROM_BASE64(b64), 1, 8)) AS disc_hex,
         BYTE_LENGTH(SAFE.FROM_BASE64(b64))          AS payload_bytes,
         LENGTH(b64)                                 AS b64_len
  FROM payload
  WHERE SAFE.FROM_BASE64(b64) IS NOT NULL
),
per_block AS (
  SELECT block_slot,
         COUNT(*) AS n_pump_tx,
         COUNTIF(truncated) AS n_trunc
  FROM flags GROUP BY 1
),
pair AS (
  SELECT block_slot, tx_index, COUNT(*) AS c FROM flags GROUP BY 1, 2
),
samples AS (
  SELECT * FROM (
    SELECT block_slot, tx_index, n_data_lines, n_log_lines, truncated, log_messages
    FROM flags ORDER BY n_data_lines DESC LIMIT 1)          -- a bundle
  UNION ALL
  SELECT * FROM (
    SELECT block_slot, tx_index, n_data_lines, n_log_lines, truncated, log_messages
    FROM flags WHERE n_data_lines = 1 LIMIT 2)              -- single-trade
)
SELECT
  -- A. transactions mentioning the pump.fun program
  (SELECT COUNT(*) FROM flags)                                      AS a_pump_tx,
  (SELECT COUNT(DISTINCT block_slot) FROM flags)                    AS a_distinct_blocks,
  (SELECT COUNTIF(self_cpi) FROM flags)                             AS a_tx_with_self_cpi,

  -- B. "Program data:" lines
  (SELECT COUNTIF(n_data_lines > 0) FROM flags)                     AS b_tx_with_data_line,
  (SELECT IFNULL(SUM(n_data_lines), 0) FROM flags)                  AS b_total_data_lines,
  (SELECT APPROX_QUANTILES(n_log_lines,100)[OFFSET(50)] FROM flags) AS b_log_lines_p50,
  (SELECT MAX(n_log_lines) FROM flags)                              AS b_log_lines_max,

  -- C. TradeEvent-discriminator payloads (the number to compare against Dune)
  (SELECT COUNTIF(disc_hex = 'bddb7fd34ee661ee') FROM ev)           AS c_tradeevent_payloads,
  (SELECT COUNT(DISTINCT FORMAT('%d|%d', block_slot, tx_index)) FROM ev
     WHERE disc_hex = 'bddb7fd34ee661ee')                           AS c_tx_with_tradeevent,
  (SELECT COUNTIF(disc_hex = '1b72a94ddeeb6376') FROM ev)           AS c_createevent_payloads,
  (SELECT COUNTIF(disc_hex = '5f72619cd42e9808') FROM ev)           AS c_completeevent_payloads,
  (SELECT COUNT(*) FROM ev)                                         AS c_all_payloads,

  -- D. truncated logs
  (SELECT COUNTIF(truncated) FROM flags)                            AS d_truncated_tx,

  -- E. distribution of truncation
  (SELECT COUNTIF(n_trunc > 0) FROM per_block)                      AS e_blocks_with_trunc,
  (SELECT MAX(n_trunc) FROM per_block)                              AS e_max_trunc_per_block,
  (SELECT APPROX_QUANTILES(n_pump_tx,100)[OFFSET(50)] FROM per_block
     WHERE n_trunc > 0)                                             AS e_p50_pumptx_trunc_blocks,
  (SELECT APPROX_QUANTILES(n_pump_tx,100)[OFFSET(50)] FROM per_block
     WHERE n_trunc = 0)                                             AS e_p50_pumptx_clean_blocks,
  (SELECT APPROX_QUANTILES(n_pump_tx,100)[OFFSET(90)] FROM per_block
     WHERE n_trunc > 0)                                             AS e_p90_pumptx_trunc_blocks,
  (SELECT APPROX_QUANTILES(n_pump_tx,100)[OFFSET(90)] FROM per_block
     WHERE n_trunc = 0)                                             AS e_p90_pumptx_clean_blocks,
  (SELECT ARRAY_AGG(STRUCT(h, n_tx, n_trunc) ORDER BY h) FROM (
      SELECT EXTRACT(HOUR FROM block_timestamp) AS h,
             COUNT(*) AS n_tx, COUNTIF(truncated) AS n_trunc
      FROM flags GROUP BY 1))                                       AS e_hourly,

  -- F. is Transactions.index unique within a block?
  (SELECT COUNT(*) FROM pair)                                       AS f_distinct_slot_txindex,
  (SELECT MAX(c) FROM pair)                                         AS f_max_rows_per_pair,
  (SELECT MIN(tx_index) FROM flags)                                 AS f_txindex_min,
  (SELECT MAX(tx_index) FROM flags)                                 AS f_txindex_max,

  -- G. three full log arrays, one of them a bundle
  (SELECT ARRAY_AGG(STRUCT(block_slot, tx_index, n_data_lines, n_log_lines,
                           truncated, log_messages)) FROM samples)  AS g_samples,

  -- H. payload length distribution by discriminator
  (SELECT ARRAY_AGG(STRUCT(disc_hex, payload_bytes, b64_len, c) ORDER BY c DESC LIMIT 25)
     FROM (SELECT disc_hex, payload_bytes, b64_len, COUNT(*) AS c
           FROM ev GROUP BY 1, 2, 3))                               AS h_payload_shapes
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Q2 (diagnostic) — Q1 returned zero for every count, so: is log_messages
-- populated at all?  The pump filter in Q1 is EXISTS over UNNEST(log_messages),
-- which yields nothing when the array carries no usable strings.
-- ─────────────────────────────────────────────────────────────────────────────
WITH t AS (
  SELECT log_messages, block_slot, `index` AS tx_index, status
  FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`
  WHERE block_timestamp >= TIMESTAMP '2026-06-02'
    AND block_timestamp <  TIMESTAMP '2026-06-03'
)
SELECT
  COUNT(*)                                                              AS tx_total,
  COUNTIF(log_messages IS NULL)                                         AS logs_null,
  COUNTIF(log_messages IS NOT NULL AND ARRAY_LENGTH(log_messages) = 0)  AS logs_empty_array,
  COUNTIF(ARRAY_LENGTH(log_messages) > 0)                               AS logs_present,
  APPROX_QUANTILES(ARRAY_LENGTH(log_messages), 100)[OFFSET(50)]         AS len_p50,
  MAX(ARRAY_LENGTH(log_messages))                                       AS len_max,
  SUM(ARRAY_LENGTH(log_messages))                                       AS total_log_lines,
  COUNTIF((SELECT COUNT(*) FROM UNNEST(log_messages) l
           WHERE STRPOS(l, 'invoke') > 0) > 0)                          AS tx_with_invoke,
  COUNTIF((SELECT COUNT(*) FROM UNNEST(log_messages) l
           WHERE STRPOS(l, 'Program ') > 0) > 0)                        AS tx_with_program_word,
  (SELECT ARRAY_AGG(s LIMIT 3) FROM (
     SELECT ARRAY_TO_STRING(log_messages, ' ~~ ') AS s
     FROM t WHERE ARRAY_LENGTH(log_messages) > 0 LIMIT 3))              AS sample_logs
FROM t
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Q3 (diagnostic) — is the emptiness specific to one day, or is the column
-- simply never populated?  Four days spanning 18 months, chosen to include the
-- oldest sampled Dune row (2025-02-01) and the end of the study window.
-- ─────────────────────────────────────────────────────────────────────────────
WITH t AS (
  SELECT DATE(block_timestamp) AS d, log_messages
  FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`
  WHERE (block_timestamp >= TIMESTAMP '2025-02-01' AND block_timestamp < TIMESTAMP '2025-02-02')
     OR (block_timestamp >= TIMESTAMP '2026-06-02' AND block_timestamp < TIMESTAMP '2026-06-03')
     OR (block_timestamp >= TIMESTAMP '2026-07-15' AND block_timestamp < TIMESTAMP '2026-07-16')
     OR (block_timestamp >= TIMESTAMP '2026-08-14' AND block_timestamp < TIMESTAMP '2026-08-15')
)
SELECT d,
  COUNT(*)                                                              AS tx,
  APPROX_QUANTILES(ARRAY_LENGTH(log_messages), 100)[OFFSET(50)]         AS arr_len_p50,
  MAX(ARRAY_LENGTH(log_messages))                                       AS arr_len_max,
  COUNTIF((SELECT COUNTIF(l IS NULL) FROM UNNEST(log_messages) l) > 0)  AS tx_with_null_element,
  COUNTIF((SELECT COUNTIF(l = '')   FROM UNNEST(log_messages) l) > 0)   AS tx_with_empty_string,
  MAX((SELECT MAX(CHAR_LENGTH(l)) FROM UNNEST(log_messages) l))         AS max_element_chars,
  SUM((SELECT IFNULL(SUM(CHAR_LENGTH(l)), 0) FROM UNNEST(log_messages) l)) AS total_chars
FROM t GROUP BY d ORDER BY d
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Q4 — measurement F on its own.  F does not depend on logs, so it survives the
-- log path being empty: is `Transactions.index` unique within a block, i.e. is
-- it the tx_index that §2.4 requires and Instructions lacks?
-- ─────────────────────────────────────────────────────────────────────────────
WITH t AS (
  SELECT block_slot, `index` AS tx_index
  FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`
  WHERE block_timestamp >= TIMESTAMP '2026-06-02'
    AND block_timestamp <  TIMESTAMP '2026-06-03'
),
pair AS (SELECT block_slot, tx_index, COUNT(*) AS c FROM t GROUP BY 1, 2),
per_block AS (SELECT block_slot, COUNT(*) n, MIN(tx_index) mn, MAX(tx_index) mx,
                     COUNT(DISTINCT tx_index) d FROM t GROUP BY 1)
SELECT (SELECT COUNT(*) FROM t)                                    AS rows_total,
       (SELECT COUNT(*) FROM pair)                                 AS distinct_pairs,
       (SELECT MAX(c) FROM pair)                                   AS max_rows_per_pair,
       (SELECT COUNT(*) FROM per_block)                            AS blocks,
       (SELECT MIN(mn) FROM per_block)                             AS txindex_min,
       (SELECT MAX(mx) FROM per_block)                             AS txindex_max,
       (SELECT COUNTIF(mn = 0) FROM per_block)                     AS blocks_starting_at_0,
       (SELECT COUNTIF(mx - mn + 1 = d) FROM per_block)            AS blocks_contiguous,
       (SELECT COUNTIF(d < n) FROM per_block)                      AS blocks_with_repeated_index,
       (SELECT APPROX_QUANTILES(n,100)[OFFSET(50)] FROM per_block)  AS tx_per_block_p50,
       (SELECT MAX(n) FROM per_block)                              AS tx_per_block_max
FROM (SELECT 1)
;

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 0 — schema, free (INFORMATION_SCHEMA is not billed)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT column_name, data_type, is_nullable
FROM `bigquery-public-data.crypto_solana_mainnet_us.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'Transactions' ORDER BY ordinal_position
;

SELECT field_path, data_type
FROM `bigquery-public-data.crypto_solana_mainnet_us.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS`
WHERE table_name = 'Transactions' AND STRPOS(field_path, '.') > 0 ORDER BY field_path
;
