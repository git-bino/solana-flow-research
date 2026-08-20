-- A.1 -- token-level path summary after `x` first reaches a level.
--
-- ONE ROW PER (token, level).  Levels 60 and 115 are produced in the SAME
-- execution so the 98-day `tradeevent` scan is paid ONCE, not twice.
--
-- Built as a MATERIALIZED VIEW.  Retrieval is billed per byte of result
-- (measured 11.75 cr/MB on chunk 1: 165,829,366 bytes -> 1,948.0 cr), so the
-- token-level rows are NOT pulled through the API here; the §3 aggregates read
-- them back on Dune and return ~100 rows instead.
-- ЭНЭ БОЛ CLAUDE CODE-ИЙН ШИЙДВЭР (cost engineering only -- no research
-- semantics change: the same rows, the same definitions, just not downloaded
-- until the download has been priced).
--
-- DEFINITIONS (research lead, 2026-08-21):
--   final_x  = `x` after the LAST trade of the token
--   the full path is NOT exported -- one row per token
--
-- ANCHOR.  `t_60` / `t_115` come from dune.quantbino1695.result_flow_token_base,
-- which defines them as the first `evt_block_time` at which
-- virtual_sol_reserves/1e9 >= the level.
--
-- WINDOW.  Events [2026-05-10, 2026-08-15]; the cohort is launches in
-- [2026-05-10, 2026-05-19) with createevent.virtual_sol_reserves = 30000000000,
-- which is exactly what the matview already holds.
--
-- CENSORING.  `dur_above` is NULL when `x` never fell back below the level
-- inside the event window; `dur_to_window_end` gives the time from the anchor to
-- the window edge for those rows, so the censoring is explicit and never
-- silently coded as zero or as a finite duration.

WITH base AS (
    SELECT token_mint, launch_time, max_x, t_60, t_115
    FROM dune.quantbino1695.result_flow_token_base
),
anchors AS (
    SELECT token_mint, launch_time, max_x, 60  AS lvl, t_60  AS t_anchor
    FROM base WHERE t_60 IS NOT NULL
    UNION ALL
    SELECT token_mint, launch_time, max_x, 115 AS lvl, t_115 AS t_anchor
    FROM base WHERE t_115 IS NOT NULL
),
ev AS (
    SELECT t.mint,
           t.evt_block_time AS bt,
           t.evt_block_slot AS sl,
           t.evt_tx_index   AS txi,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT a.token_mint, a.lvl, a.launch_time, a.t_anchor, a.max_x,
           e.bt, e.sl, e.txi, e.x
    FROM anchors a
    JOIN ev e ON e.mint = a.token_mint
),
agg AS (
    SELECT token_mint, lvl,
           max(launch_time) AS launch_time,
           max(t_anchor)    AS t_anchor,
           max(max_x)       AS max_x,
           -- first fall back below the level, at or after the anchor
           min(if(bt >= t_anchor AND x < lvl, bt))          AS t_below,
           -- lowest reserve seen from the anchor onward
           min(if(bt >= t_anchor, x))                        AS min_x_after,
           -- EARLIEST time at which the maximum reserve was reached
           min_by(bt, ROW(-x, bt))                           AS t_max_x,
           -- reserve after the LAST trade, ordered deterministically
           max_by(x, ROW(bt, sl, txi))                       AS final_x,
           max(bt)                                           AS t_final,
           count_if(bt >= t_anchor)                          AS n_trades_after,
           min(if(bt >= t_anchor AND x >= 70,  bt))          AS t_70,
           min(if(bt >= t_anchor AND x >= 80,  bt))          AS t_80,
           min(if(bt >= t_anchor AND x >= 100, bt))          AS t_100,
           min(if(bt >= t_anchor AND x >= 115, bt))          AS t_115x
    FROM j
    GROUP BY token_mint, lvl
)
SELECT
    token_mint,
    lvl,
    to_unixtime(t_anchor) - to_unixtime(launch_time)          AS t_anchor_s,
    to_unixtime(t_below)  - to_unixtime(t_anchor)             AS dur_above_s,
    to_unixtime(TIMESTAMP '2026-08-15 23:59:00')
        - to_unixtime(t_anchor)                               AS dur_to_window_end_s,
    min_x_after,
    max_x,
    to_unixtime(t_max_x)  - to_unixtime(t_anchor)             AS t_max_x_s,
    final_x,
    to_unixtime(t_final)  - to_unixtime(t_anchor)             AS t_final_s,
    to_unixtime(t_70)     - to_unixtime(t_anchor)             AS t_70_s,
    to_unixtime(t_80)     - to_unixtime(t_anchor)             AS t_80_s,
    to_unixtime(t_100)    - to_unixtime(t_anchor)             AS t_100_s,
    to_unixtime(t_115x)   - to_unixtime(t_anchor)             AS t_115_s,
    n_trades_after
FROM agg
