-- 1 (нөхөх) -- `completeevent` is not the only migration marker.  Earlier work
-- measured `migrated` at 3.81% using pump_evt_completepumpammmigrationevent as
-- well, while completeevent alone gives 0.84%.  §1's question -- is the
-- x > 115 data taken on the curve or after it closed -- cannot be answered from
-- completeevent alone, so the second marker is checked the same way.
WITH base AS (
    SELECT token_mint FROM dune.quantbino1695.result_flow_token_base
),
mg AS (
    SELECT mint, min(evt_block_time) AS t_m
    FROM pumpdotfun_solana.pump_evt_completepumpammmigrationevent
    WHERE evt_block_date >= DATE '2026-05-10' AND evt_block_date <= DATE '2026-08-15'
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
    WHERE t.evt_block_date >= DATE '2026-05-10' AND t.evt_block_date <= DATE '2026-08-15'
),
p AS (
    SELECT e.mint,
           max(m.t_m) IS NOT NULL                              AS has_mig,
           CAST(count_if(m.t_m IS NOT NULL AND e.bt > m.t_m) AS bigint) AS n_after,
           max_by(e.x, if(m.t_m IS NOT NULL AND e.bt <= m.t_m, e.seq)) AS x_at_mig,
           max(if(m.t_m IS NULL OR e.bt <= m.t_m, e.x))        AS max_x_pre_mig,
           max(e.x)                                            AS max_x_all,
           max(if(e.x > 115, 1, 0)) = 1                        AS ever_gt115
    FROM ev e LEFT JOIN mg m ON m.mint = e.mint
    GROUP BY e.mint
)
SELECT CAST(count(*) AS double) AS n_tokens,
       CAST(count_if(has_mig) AS double) AS tok_mig,
       CAST(count_if(has_mig AND n_after > 0) AS double) AS tok_trade_after,
       CAST(sum(n_after) AS double) AS n_ev_after,
       CAST(count_if(ever_gt115 AND has_mig) AS double) AS gt115_and_mig,
       CAST(count_if(ever_gt115) AS double) AS tok_gt115,
       CAST(count_if(max_x_pre_mig > 115) AS double) AS pre_mig_gt115,
       approx_percentile(if(has_mig, x_at_mig), 0.10) AS xm_p10,
       approx_percentile(if(has_mig, x_at_mig), 0.50) AS xm_p50,
       approx_percentile(if(has_mig, x_at_mig), 0.90) AS xm_p90,
       min(if(has_mig, x_at_mig)) AS xm_min, max(if(has_mig, x_at_mig)) AS xm_max,
       approx_percentile(max_x_pre_mig, 0.90) AS pre_p90,
       approx_percentile(max_x_pre_mig, 0.99) AS pre_p99,
       max(max_x_pre_mig) AS pre_max
FROM p
