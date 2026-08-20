-- 2 (rug) -- dev_dump / dead / clean / migrated on the clean universe, using the
-- SAME definitions as sql/token_fate_baseline.sql query C so the numbers are
-- comparable to rug = 99.16%:
--   dev_dump : creator ever held (peak_units > 0) and last_held <= 0.10 * peak
--   dead     : idle >= 6h at the window edge AND max_x < 60
--   migrated : max_x >= 115 OR a completeevent exists
--   rug      : dev_dump OR dead ;  clean_token : NOT rug AND NOT migrated
-- `dev_dump` uses the coalesce fix (a creator that never traded cannot have sold).
--
-- The running peak needs ONE window, over the CREATOR's trades only -- a small
-- subset, which is why token_fate_baseline query C cost 3.038 cr.
WITH cu AS (
    SELECT token_mint, t_last, max_x,
           CASE WHEN k0 IS NULL OR k0 <= 0 THEN NULL
                ELSE greatest(abs(xy_max / k0 - 1.0), abs(xy_min / k0 - 1.0)) END AS dev
    FROM dune.quantbino1695.result_flow_clean
),
u AS (
    SELECT token_mint, t_last, max_x,
           CASE WHEN dev IS NULL THEN 'no_ev' WHEN dev < 1e-6 THEN 'clean' ELSE 'dirty' END AS uni
    FROM cu
),
cr AS (
    SELECT mint, min(user) AS creator
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date < DATE '2026-05-19'
    GROUP BY mint
),
ctr AS (   -- creator trades only
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000 AS seq,
           if(t.is_buy, CAST(t.token_amount AS double), -CAST(t.token_amount AS double)) AS du
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN cr ON cr.mint = t.mint AND cr.creator = t.user
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
run AS (
    SELECT mint, seq,
           sum(du) OVER (PARTITION BY mint ORDER BY seq
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS held
    FROM ctr
),
agg AS (
    SELECT mint, max(held) AS peak_units, max_by(held, seq) AS last_held FROM run GROUP BY mint
),
cp AS (
    SELECT DISTINCT mint FROM pumpdotfun_solana.pump_evt_completeevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date <= DATE '2026-08-15'
),
lab AS (
    SELECT u.uni,
           (coalesce(a.peak_units, 0) > 0
              AND coalesce(a.last_held, 0) <= 0.10 * coalesce(a.peak_units, 0)) AS dev_dump,
           (to_unixtime(TIMESTAMP '2026-08-15 23:59:00') - to_unixtime(u.t_last) >= 21600
              AND coalesce(u.max_x, 0.0) < 60) AS dead,
           (coalesce(u.max_x, 0.0) >= 115 OR cp.mint IS NOT NULL) AS migrated
    FROM u LEFT JOIN agg a ON a.mint = u.token_mint
           LEFT JOIN cp ON cp.mint = u.token_mint
    WHERE u.uni <> 'no_ev'
)
SELECT uni, CAST(count(*) AS double) AS n,
       CAST(count_if(dev_dump) AS double)/count(*) AS s_dev_dump,
       CAST(count_if(dead) AS double)/count(*) AS s_dead,
       CAST(count_if(dev_dump OR dead) AS double)/count(*) AS s_rug,
       CAST(count_if(NOT (dev_dump OR dead) AND NOT migrated) AS double)/count(*) AS s_clean,
       CAST(count_if(migrated) AS double)/count(*) AS s_migrated
FROM lab GROUP BY uni
