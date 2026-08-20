-- Token-fate baseline, part 2 only: CREATOR RECURRENCE.
--
-- PURPOSE.  Two numbers were registered as deciding the next direction
-- (decisions.md, 2026-08-20): the base rate of the token-level targets, and the
-- share of cohort tokens whose creator already had a token.  This statement
-- answers the SECOND.  The first needs a 98-day `tradeevent` scan and is
-- estimated at ~100-120 credits, which fails the task's own stop rule
-- (estimate x 3 <= 35), so it is NOT run here.
--
-- SCOPE.  Cohort = tokens created in [2026-05-10, 2026-05-19) whose createevent
-- declares virtual_sol_reserves = 30000000000 -- identical to extract chunk 1.
-- Creator history deliberately looks OUTSIDE the cohort window: a creator's
-- earlier tokens may predate 2026-05-10, and the whole point is to find them.
-- `pump_evt_createevent` is scanned from its earliest partition, and the
-- observed range is reported rather than assumed.
--
-- Aggregates only; no rows are exported.
--
-- Date: 2026-08-20

WITH cohort AS (
    SELECT mint, min(user) AS creator, min(evt_block_time) AS created_at
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10'
      AND evt_block_date <  DATE '2026-05-19'
      AND CAST(virtual_sol_reserves AS bigint) = 30000000000
    GROUP BY mint
),
all_tokens AS (
    -- every token by any cohort creator, over the table's whole history
    SELECT c.user AS creator, c.mint, c.evt_block_time AS created_at
    FROM pumpdotfun_solana.pump_evt_createevent c
    JOIN (SELECT DISTINCT creator FROM cohort) k ON k.creator = c.user
),
span AS (
    SELECT min(evt_block_date) AS first_date, max(evt_block_date) AS last_date,
           count(*) AS n_create_rows
    FROM pumpdotfun_solana.pump_evt_createevent
),
per_creator AS (
    SELECT creator, count(*) AS n_tokens_all_time
    FROM all_tokens GROUP BY creator
),
-- for each cohort token: how many tokens the same creator made BEFORE it
prior AS (
    SELECT co.mint, co.creator,
           count(a.mint) FILTER (WHERE a.created_at < co.created_at) AS n_prior
    FROM cohort co
    LEFT JOIN all_tokens a ON a.creator = co.creator
    GROUP BY co.mint, co.creator
),
-- One-row aggregates, CROSS JOINed.  NOT twenty scalar subqueries over the same
-- CTEs: probe A2 died at Dune's 30-minute limit for 164.755 credits with twelve
-- of those over one heavy CTE (docs/redesign_probe.md).
cohort_agg AS (
    SELECT count(*) AS cohort_tokens,
           count(DISTINCT creator) AS cohort_creators
    FROM cohort
),
tokens_agg AS (
    SELECT count(*) AS tokens_by_cohort_creators FROM all_tokens
),
creator_agg AS (
    SELECT count_if(n = 1) AS creators_1,
           count_if(n = 2) AS creators_2,
           count_if(n BETWEEN 3 AND 5) AS creators_3_5,
           count_if(n BETWEEN 6 AND 10) AS creators_6_10,
           count_if(n >= 11) AS creators_11p,
           count(*) AS creators_total,
           max(n) AS creator_max_tokens,
           approx_percentile(CAST(n AS double), 0.5) AS creator_tokens_p50,
           approx_percentile(CAST(n AS double), 0.9) AS creator_tokens_p90
    FROM (SELECT creator, count(*) AS n FROM all_tokens GROUP BY creator)
),
prior_agg AS (
    SELECT count_if(n_prior > 0) AS cohort_tokens_with_history,
           count(*) AS cohort_tokens_checked,
           approx_percentile(CAST(n_prior AS double), 0.5)
               FILTER (WHERE n_prior > 0) AS prior_p50,
           approx_percentile(CAST(n_prior AS double), 0.9)
               FILTER (WHERE n_prior > 0) AS prior_p90,
           max(n_prior) AS prior_max
    FROM prior
)
SELECT * FROM cohort_agg
CROSS JOIN tokens_agg
CROSS JOIN creator_agg
CROSS JOIN prior_agg
CROSS JOIN span
