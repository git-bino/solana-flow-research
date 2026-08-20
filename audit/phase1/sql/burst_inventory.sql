-- Phase 0 — burst inventory: age x mayhem cross-tab.  Counting only.
--
-- Cohort is the §0.1 probe cohort (docs/phase0_size_estimate.md), reused
-- verbatim so the numbers stay comparable.  NOTE the window below: the previous
-- measurement used creates in [2026-06-01, 2026-06-04) = 3 days = 81,052 tokens.
-- The date literals are the single place to change if a 4-day cohort is wanted.
--
-- Filters: quote_mint = SOL only (decisions.md).  Nothing else — no activity,
-- volume, lifetime or migration filter (spec §2.2).  Tokens with zero events are
-- counted in the cohort totals.
--
-- Burst = spec §4.1 in slots (v1.2):
--   net_flow_5slot(t) >= max(3 SOL, 0.10 * x(t)),  x(t) read straight from the
--   row's virtual_sol_reserves (no replay, spec §2.3), and no burst in the
--   previous 25 slots.
--
-- Two implementation notes, both stated rather than hidden:
--
-- 1. net_flow_5slot is built as (prefix sum through this row) minus (prefix sum
--    over all rows with slot <= s-5).  The first sum is ordered by the full key
--    (slot, tx_index, ix_index) so it stops AT the current row; the second is a
--    SUM over a RANGE frame, so it is peer-deterministic.  This gives exactly
--    slot in (s-5, s] with no intra-slot lookahead — a plain
--    `RANGE 4 PRECEDING ... CURRENT ROW` would silently include same-slot rows
--    that execute after the current one (spec §6.1).
--
-- 2. "no burst active in the previous 25 slots" is implemented as 25-slot
--    sessionisation of qualifying events: a qualifying event opens a burst when
--    the previous *qualifying* event is more than 25 slots back.  The spec does
--    not define how long a burst stays "active", so this is the same
--    approximation used for the 42,094 figure in docs/phase0_size_estimate.md,
--    kept identical for comparability.
--
-- ix_index = outer_instruction_index * 64 + inner_instruction_index, matching
-- the composite ordering key recorded in decisions.md.

WITH created AS (
    SELECT mint,
           min(evt_block_time) AS launch_time,
           bool_or(is_mayhem_mode) AS mayhem_at_launch
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-06-01'
      AND evt_block_date <  DATE '2026-06-04'
      AND quote_mint = '11111111111111111111111111111111'
    GROUP BY mint
),
ev_raw AS (
    SELECT c.mint,
           c.launch_time,
           t.evt_block_time AS bt,
           t.evt_block_slot AS slot,
           t.evt_tx_index   AS txi,
           coalesce(t.evt_outer_instruction_index, 0) * 64
             + coalesce(t.evt_inner_instruction_index, 0) AS ixi,
           CASE WHEN t.is_buy THEN CAST(t.sol_amount AS double) / 1e9
                ELSE -CAST(t.sol_amount AS double) / 1e9 END AS signed_sol,
           CAST(t.virtual_sol_reserves AS double) / 1e9 AS x,
           coalesce(t.mayhem_mode, false) AS mayhem
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN created c ON t.mint = c.mint
    WHERE t.evt_block_date >= DATE '2026-06-01'
      AND t.evt_block_date <= DATE '2026-06-11'
      AND t.evt_block_time <  TIMESTAMP '2026-06-11 23:59:00'
      AND t.quote_mint = '11111111111111111111111111111111'
),
tok AS (   -- token_mayhem = MAX(mayhem) over the token's events
    SELECT mint,
           max(if(mayhem, 1, 0)) AS m_max,
           min(if(mayhem, 1, 0)) AS m_min
    FROM ev_raw GROUP BY mint
),
ev AS (
    SELECT e.*,
           (tok.m_max = 1) AS token_mayhem,
           date_diff('second', e.launch_time, e.bt) / 60.0 AS age_min
    FROM ev_raw e JOIN tok ON tok.mint = e.mint
),
flow AS (
    SELECT mint, bt, slot, txi, ixi, x, token_mayhem, age_min,
           sum(signed_sol) OVER (
               PARTITION BY mint ORDER BY slot, txi, ixi
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
           - coalesce(sum(signed_sol) OVER (
               PARTITION BY mint ORDER BY slot
               RANGE BETWEEN UNBOUNDED PRECEDING AND 5 PRECEDING), 0) AS nf5
    FROM ev
),
qual AS (
    SELECT mint, bt, slot, x, token_mayhem, age_min,
           lag(slot) OVER (PARTITION BY mint ORDER BY slot, txi, ixi) AS prev_slot
    FROM flow
    WHERE nf5 >= greatest(3.0, 0.10 * x)
),
bursts AS (
    SELECT * FROM qual WHERE prev_slot IS NULL OR slot - prev_slot > 25
),
scalars AS (
    SELECT (SELECT count(*) FROM created)                                AS cohort_tokens,
           (SELECT count_if(mayhem_at_launch) FROM created)              AS cohort_mayhem_at_launch,
           (SELECT count(*) FROM tok)                                    AS tokens_with_events,
           (SELECT count_if(m_min <> m_max) FROM tok)                    AS mayhem_inconsistent_tokens,
           (SELECT count(*) FROM created c
              WHERE NOT EXISTS (SELECT 1 FROM tok WHERE tok.mint = c.mint)) AS tokens_no_events,
           (SELECT count_if(mayhem_at_launch) FROM created c
              WHERE NOT EXISTS (SELECT 1 FROM tok WHERE tok.mint = c.mint)) AS tokens_no_events_mayhem,
           (SELECT min(age_min) FROM ev)                                 AS min_event_age_min
),
ev_agg AS (
    SELECT token_mayhem,
           count_if(age_min <= 5)  AS e5,
           count_if(age_min <= 15) AS e15,
           count_if(age_min <= 30) AS e30,
           count_if(age_min <= 60) AS e60,
           count(*)                AS einf,
           count(DISTINCT if(age_min <= 5,  mint)) AS te5,
           count(DISTINCT if(age_min <= 15, mint)) AS te15,
           count(DISTINCT if(age_min <= 30, mint)) AS te30,
           count(DISTINCT if(age_min <= 60, mint)) AS te60,
           count(DISTINCT mint)                    AS teinf,
           approx_percentile(age_min, 0.10) AS ea_p10,
           approx_percentile(age_min, 0.25) AS ea_p25,
           approx_percentile(age_min, 0.50) AS ea_p50,
           approx_percentile(age_min, 0.75) AS ea_p75,
           approx_percentile(age_min, 0.90) AS ea_p90,
           approx_percentile(age_min, 0.99) AS ea_p99
    FROM ev GROUP BY token_mayhem
),
b_agg AS (
    SELECT token_mayhem,
           -- 1.0 minute buffer so tau=37 slot and the 75-slot hazard window fit
           count_if(age_min <= 4)  AS b5,
           count_if(age_min <= 14) AS b15,
           count_if(age_min <= 29) AS b30,
           count_if(age_min <= 59) AS b60,
           count(*)                AS binf,
           count(DISTINCT if(age_min <= 4,  mint)) AS tb5,
           count(DISTINCT if(age_min <= 14, mint)) AS tb15,
           count(DISTINCT if(age_min <= 29, mint)) AS tb30,
           count(DISTINCT if(age_min <= 59, mint)) AS tb60,
           count(DISTINCT mint)                    AS tbinf,
           count(DISTINCT if(age_min <= 4,  date_trunc('minute', bt))) AS mw5,
           count(DISTINCT if(age_min <= 14, date_trunc('minute', bt))) AS mw15,
           count(DISTINCT if(age_min <= 29, date_trunc('minute', bt))) AS mw30,
           count(DISTINCT if(age_min <= 59, date_trunc('minute', bt))) AS mw60,
           count(DISTINCT date_trunc('minute', bt))                    AS mwinf,
           approx_percentile(age_min, 0.10) AS ba_p10,
           approx_percentile(age_min, 0.25) AS ba_p25,
           approx_percentile(age_min, 0.50) AS ba_p50,
           approx_percentile(age_min, 0.75) AS ba_p75,
           approx_percentile(age_min, 0.90) AS ba_p90,
           approx_percentile(age_min, 0.99) AS ba_p99,
           approx_percentile(x, 0.50)       AS x_med_at_burst
    FROM bursts GROUP BY token_mayhem
)
SELECT coalesce(e.token_mayhem, b.token_mayhem) AS token_mayhem,
       e.*, b.*, s.*
FROM ev_agg e
FULL OUTER JOIN b_agg b ON e.token_mayhem = b.token_mayhem
CROSS JOIN scalars s
ORDER BY 1
