-- Token fate baseline — FOUR statements, run separately on 2026-08-21.
--
-- WHY FOUR AND NOT ONE.  The task caps each query at estimate x 3 <= 35 credits.
-- A combined statement calibrated at 0.1399 cr/day over 3 days, i.e. 13.7 cr
-- for the 98-day window, whose x3 is 41.1 and fails the rule.  Split, each
-- part passes and the total cost is the same; a smaller execution also has a
-- smaller blast radius if it hangs.  ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР.
--
-- COST CALIBRATION, measured rather than guessed: the plain GROUP BY form ran
-- 3 days for 0.1833 credits (0.0611/day), so the earlier ~100-120 credit
-- estimate for this window was wrong by ~20x -- that figure came from chunk
-- 1's extract, which carried 80 columns, a transfer join and window
-- functions.  Actual totals below.
--
-- Cohort: launch [2026-05-10, 2026-05-19), createevent.virtual_sol_reserves
-- = 30000000000; event window to 2026-08-15 23:59 UTC.  Aggregates only.
--
-- A  max_x, lifetime, trade counts            query 8390439   2.150 cr
-- B  creator holdings, completeevent          query 8390470   1.393 cr
-- C  rug/clean/migrated labels + crosstab     query 8390483   3.038 cr
-- D  prior_count buckets (createevent only)   query 8390502   6.018 cr
-- calibration runs 8390400 + 8390425                          0.603 cr
-- failed draft (syntax, 0 cr)                 8390456         0
--                                             TOTAL          20.847 cr
--
-- KNOWN DEFECT in C, found after the run and corrected in the text below but
-- NOT re-run: `dev_dump` was left NULL when the creator never traded, and
-- `NULL OR false` is NULL, so 296 tokens (0.11%) fall into neither rug nor
-- clean.  Those creators cannot have sold, so the fix makes them clean:
-- clean is 1,904 (0.73%) as measured and 2,200 (0.84%) once corrected.  The
-- registered 5% stop rule fires either way, so it was not worth 3 more
-- credits to re-run.  The coalesce is present below for any future run.

-- ============================= A =============================
WITH cohort AS (
    SELECT mint FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
tok AS (
    SELECT t.mint,
           CAST(max(CAST(t.virtual_sol_reserves AS bigint)) AS double) / 1e9 AS max_x,
           count(*) AS n_trades,
           min(t.evt_block_time) AS first_t,
           max(t.evt_block_time) AS last_t
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN cohort c ON c.mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
      AND t.evt_block_time < TIMESTAMP '2026-08-15 23:59:00 UTC'
    GROUP BY t.mint
),
lifetime AS (
    SELECT mint, max_x, n_trades,
           date_diff('second', first_t, last_t) AS life_s,
           date_diff('hour', last_t, TIMESTAMP '2026-08-15 23:59:00 UTC') AS idle_h
    FROM tok
)
SELECT (SELECT count(*) FROM cohort)                       AS cohort_tokens,
       count(*)                                            AS tokens_with_trades,
       approx_percentile(max_x, 0.10) AS max_x_p10,
       approx_percentile(max_x, 0.25) AS max_x_p25,
       approx_percentile(max_x, 0.50) AS max_x_p50,
       approx_percentile(max_x, 0.75) AS max_x_p75,
       approx_percentile(max_x, 0.90) AS max_x_p90,
       approx_percentile(max_x, 0.95) AS max_x_p95,
       approx_percentile(max_x, 0.99) AS max_x_p99,
       max(max_x)                     AS max_x_max,
       count_if(max_x > 40)  AS gt40,
       count_if(max_x > 60)  AS gt60,
       count_if(max_x > 80)  AS gt80,
       count_if(max_x >= 115) AS ge115,
       approx_percentile(CAST(life_s AS double), 0.5) AS life_s_p50,
       approx_percentile(CAST(life_s AS double), 0.9) AS life_s_p90,
       max(life_s)                                    AS life_s_max,
       approx_percentile(CAST(n_trades AS double), 0.5) AS trades_p50,
       approx_percentile(CAST(n_trades AS double), 0.9) AS trades_p90,
       max(n_trades)                                    AS trades_max,
       count_if(idle_h >= 6)                            AS idle_ge6h,
       count_if(idle_h >= 6 AND max_x < 60)             AS dead_tokens
FROM lifetime

-- ============================= B =============================
WITH cohort AS (
    SELECT mint, min(user) AS creator FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
base AS (   -- зөвхөн creator-ийн арилжаа
    SELECT t.mint, t.is_buy,
           if(t.is_buy, CAST(t.token_amount AS bigint),
                        -CAST(t.token_amount AS bigint)) AS d,
           t.evt_block_slot AS sl, t.evt_tx_index AS ti,
           coalesce(t.evt_outer_instruction_index,0) AS oi,
           coalesce(t.evt_inner_instruction_index,0) AS ii
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN cohort c ON c.mint = t.mint AND c.creator = t.user
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
      AND t.evt_block_time < TIMESTAMP '2026-08-15 23:59:00 UTC'
),
run AS (
    SELECT mint, is_buy, d,
           sum(d) OVER (PARTITION BY mint ORDER BY sl, ti, oi, ii
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS held
    FROM base
),
cagg AS (
    -- peak нь гүйлгээний дээд цэг; эцсийн эзэмшил нь бүх дельтийн нийлбэр
    SELECT mint, max(held) AS peak_units, sum(d) AS last_held,
           count_if(NOT is_buy) AS sells, count(*) AS creator_trades
    FROM run GROUP BY mint
),
comp AS (
    SELECT DISTINCT mint FROM pumpdotfun_solana.pump_evt_completeevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date <= DATE '2026-08-15'
),
lab AS (
    SELECT c.mint,
           coalesce(a.peak_units, 0) AS peak_units,
           coalesce(a.last_held, 0)  AS last_held,
           coalesce(a.sells, 0)      AS sells,
           if(cp.mint IS NULL, 0, 1) AS has_complete
    FROM cohort c
    LEFT JOIN cagg a ON a.mint = c.mint
    LEFT JOIN comp cp ON cp.mint = c.mint
)
SELECT count(*)                                     AS cohort_tokens,
       count_if(peak_units > 0)                     AS creator_ever_held,
       count_if(sells > 0)                          AS creator_ever_sold,
       count_if(peak_units > 0 AND sells > 0
                AND last_held <= 0.10 * peak_units) AS dev_dump,
       count_if(peak_units <= 0)                    AS creator_no_position,
       count_if(has_complete = 1)                   AS has_completeevent,
       approx_percentile(if(peak_units > 0,
            CAST(last_held AS double) / CAST(peak_units AS double), NULL), 0.5) AS ratio_p50,
       approx_percentile(if(peak_units > 0,
            CAST(last_held AS double) / CAST(peak_units AS double), NULL), 0.9) AS ratio_p90
FROM lab

-- ============================= C =============================
WITH cohort AS (
    SELECT mint, min(user) AS creator FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
tr AS (
    SELECT t.mint, t.user, t.is_buy,
           CAST(t.virtual_sol_reserves AS bigint) AS vsol,
           if(t.is_buy, CAST(t.token_amount AS bigint), -CAST(t.token_amount AS bigint)) AS d,
           t.evt_block_time AS bt, t.evt_block_slot AS sl, t.evt_tx_index AS ti,
           coalesce(t.evt_outer_instruction_index,0) AS oi,
           coalesce(t.evt_inner_instruction_index,0) AS ii
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN cohort c ON c.mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
      AND t.evt_block_time < TIMESTAMP '2026-08-15 23:59:00 UTC'
),
tok AS (
    SELECT mint, CAST(max(vsol) AS double)/1e9 AS max_x, count(*) AS n_trades,
           date_diff('hour', max(bt), TIMESTAMP '2026-08-15 23:59:00 UTC') AS idle_h
    FROM tr GROUP BY mint
),
crun AS (
    SELECT tr.mint, tr.is_buy, tr.d,
           sum(tr.d) OVER (PARTITION BY tr.mint ORDER BY tr.sl, tr.ti, tr.oi, tr.ii
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS held
    FROM tr JOIN cohort c ON c.mint = tr.mint AND c.creator = tr.user
),
cagg AS (
    SELECT mint, max(held) AS peak_units, sum(d) AS last_held,
           count_if(NOT is_buy) AS sells
    FROM crun GROUP BY mint
),
comp AS (
    SELECT DISTINCT mint FROM pumpdotfun_solana.pump_evt_completeevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date <= DATE '2026-08-15'
),
lab AS (
    SELECT c.mint,
           coalesce(k.max_x, 0.0) AS max_x,
           coalesce(k.idle_h, 999999) AS idle_h,
           (coalesce(a.peak_units, 0) > 0 AND coalesce(a.sells, 0) > 0
            AND a.last_held <= 0.10 * a.peak_units)   -- coalesce: 2026-08-21 fix      AS dev_dump,
           (coalesce(k.idle_h, 999999) >= 6
            AND coalesce(k.max_x, 0.0) < 60)             AS dead,
           (coalesce(k.max_x, 0.0) >= 115 OR cp.mint IS NOT NULL) AS migrated
    FROM cohort c
    LEFT JOIN tok k  ON k.mint = c.mint
    LEFT JOIN cagg a ON a.mint = c.mint
    LEFT JOIN comp cp ON cp.mint = c.mint
),
fin AS (SELECT *, (dev_dump OR dead) AS rug FROM lab)
SELECT count(*)                                   AS cohort_tokens,
       count_if(dev_dump)                         AS dev_dump,
       count_if(dead)                             AS dead,
       count_if(rug)                              AS rug,
       count_if(NOT rug)                          AS clean,
       count_if(migrated)                         AS migrated,
       count_if(dev_dump AND dead)                AS both_labels,
       count_if(migrated AND rug)                 AS migrated_and_rug,
       count_if(max_x > 40)                       AS gt40,
       count_if(max_x > 40 AND rug)               AS gt40_rug,
       count_if(max_x > 40 AND NOT rug)           AS gt40_clean,
       count_if(max_x > 60)                       AS gt60,
       count_if(max_x > 60 AND rug)               AS gt60_rug,
       count_if(max_x > 60 AND NOT rug)           AS gt60_clean,
       count_if(max_x > 80)                       AS gt80,
       count_if(max_x > 80 AND rug)               AS gt80_rug,
       count_if(max_x > 80 AND NOT rug)           AS gt80_clean,
       count_if(max_x >= 115)                     AS ge115,
       count_if(max_x >= 115 AND rug)             AS ge115_rug,
       count_if(max_x >= 115 AND NOT rug)         AS ge115_clean
FROM fin

-- ============================= D =============================
WITH cohort AS (
    SELECT mint, min(user) AS creator, min(evt_block_time) AS created_at
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
all_tokens AS (
    SELECT c.user AS creator, c.mint, c.evt_block_time AS created_at
    FROM pumpdotfun_solana.pump_evt_createevent c
    JOIN (SELECT DISTINCT creator FROM cohort) k ON k.creator = c.user
),
prior AS (
    -- зөвхөн тухайн токен төрөхөӨС ӨМНӨХ токенууд; ирээдүйн токен ОРОХГҮЙ
    SELECT co.mint,
           count(a.mint) FILTER (WHERE a.created_at < co.created_at) AS n_prior
    FROM cohort co
    LEFT JOIN all_tokens a ON a.creator = co.creator
    GROUP BY co.mint
)
SELECT count(*)                                AS cohort_tokens,
       count_if(n_prior = 0)                   AS p0_new,
       count_if(n_prior = 1)                   AS p1,
       count_if(n_prior BETWEEN 2 AND 5)       AS p2_5,
       count_if(n_prior BETWEEN 6 AND 10)      AS p6_10,
       count_if(n_prior BETWEEN 11 AND 100)    AS p11_100,
       count_if(n_prior >= 101)                AS p101p,
       approx_percentile(CAST(n_prior AS double), 0.5) AS prior_p50,
       approx_percentile(CAST(n_prior AS double), 0.9) AS prior_p90,
       max(n_prior)                            AS prior_max,
       -- фабрик (11+) vs давтагч (2–10) vs шинэ, brief-ийн ангиллаар
       count_if(n_prior >= 11)                 AS factory_tokens,
       count_if(n_prior BETWEEN 1 AND 10)      AS repeater_tokens
FROM prior
