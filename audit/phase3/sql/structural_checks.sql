-- 1 + 2a -- per-token migration and floor facts.  Built ONCE as a matview
-- because §1 and §2 both need the same 98-day tradeevent scan; the aggregates
-- then read this table for ~0.2 cr each instead of rescanning.
--
-- `x_at_complete` DEFINITION.  The reserve "at the moment of completeevent" is
-- taken as the reserve on the LAST tradeevent at or before the completeevent
-- time.  completeevent's own payload is not read: the quantity wanted is the
-- state of the bonding curve when it closed, and that is what the last curve
-- trade carries.  Stated here rather than assumed silently.
--
-- `max_x_pre` is the maximum reserve over events at or before completeevent
-- (all events, when the token never completed).  Comparing it against
-- `max_x_all` is the whole point of §1: it separates what was reachable ON the
-- curve from what the data shows after the curve closed.
WITH base AS (
    SELECT token_mint, launch_time
    FROM dune.quantbino1695.result_flow_token_base
),
ce AS (
    SELECT mint, min(evt_block_time) AS t_c
    FROM pumpdotfun_solana.pump_evt_completeevent
    WHERE evt_block_date >= DATE '2026-05-10'
      AND evt_block_date <= DATE '2026-08-15'
    GROUP BY mint
),
ev AS (
    SELECT t.mint,
           CAST(t.evt_block_slot AS bigint) * 1000000000
             + CAST(t.evt_tx_index AS bigint) * 10000 AS seq,
           t.evt_block_time AS bt,
           CAST(t.virtual_sol_reserves AS bigint) / 1e9 AS x
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN base b ON b.token_mint = t.mint
    WHERE t.evt_block_date >= DATE '2026-05-10'
      AND t.evt_block_date <= DATE '2026-08-15'
),
j AS (
    SELECT e.mint, e.seq, e.bt, e.x, c.t_c
    FROM ev e LEFT JOIN ce c ON c.mint = e.mint
)
SELECT mint AS token_mint,
       CAST(count(*) AS bigint)                              AS n_ev,
       max(x)                                                AS max_x_all,
       min(x)                                                AS min_x_all,
       max(if(t_c IS NULL OR bt <= t_c, x))                  AS max_x_pre,
       min(if(t_c IS NULL OR bt <= t_c, x))                  AS min_x_pre,
       CAST(count_if(x > 115) AS bigint)                     AS n_gt115,
       CAST(count_if(t_c IS NOT NULL AND bt >  t_c) AS bigint) AS n_after_c,
       CAST(count_if(t_c IS NOT NULL AND bt <= t_c) AS bigint) AS n_upto_c,
       max_by(x, if(t_c IS NOT NULL AND bt <= t_c, seq))     AS x_at_complete,
       max(t_c) IS NOT NULL                                  AS has_complete,
       max(if(x > 115, 1, 0)) = 1                            AS ever_gt115
FROM j
GROUP BY mint
