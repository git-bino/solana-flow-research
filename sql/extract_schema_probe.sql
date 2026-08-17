-- Phase 0 — candidate burst-row extract schema.  Inventory and measurement only.
-- Nothing is dropped: doubtful columns are included and marked in
-- docs/phase0_extract_schema.md rather than decided here.
--
-- Cohort: tokens created 2026-06-01, SOL-quote, events to 2026-06-11 23:59 —
-- the same 1-day cohort every other measurement used.
--
-- Row set = the §4.1 primary cell (0.10x, 5-slot window, 25-slot
-- sessionisation), so the row count is comparable with burst_inventory.
-- qual_005 / qual_020 flag whether the SAME event also clears the other two
-- thresholds; that is NOT the same as independently sessionising each threshold
-- (§3d), and the report says so.
--
-- Windows are slot-based (spec v1.2).  Trailing flows are differences of prefix
-- sums so the window cuts AT the current row (spec §6.1); forward windows are
-- labels, where lookahead is the point.

WITH sel AS (
    SELECT mint,
           min(evt_block_time) AS created_at,
           max(CAST(virtual_sol_reserves   AS bigint)) AS x0_lam,
           max(CAST(virtual_token_reserves AS bigint)) AS y0_units,
           bool_or(is_mayhem_mode) AS mayhem_at_launch
    FROM pumpdotfun_solana.pump_evt_createevent
    WHERE evt_block_date >= DATE '2026-06-01'
      AND evt_block_date <  DATE '2026-06-02'
      AND quote_mint = '11111111111111111111111111111111'
    GROUP BY mint
),
ev AS (
    SELECT s.mint, s.created_at, s.x0_lam, s.y0_units, s.mayhem_at_launch,
           t.evt_block_time AS bt,
           t.evt_block_slot AS slot,
           t.evt_tx_index   AS txi,
           coalesce(t.evt_outer_instruction_index, 0) * 64
             + coalesce(t.evt_inner_instruction_index, 0) AS ixi,
           t.user AS wallet,
           t.is_buy,
           CAST(t.sol_amount   AS bigint) AS lam,
           CAST(t.token_amount AS bigint) AS units,
           CAST(t.virtual_sol_reserves AS bigint) AS vsol,
           coalesce(t.mayhem_mode, false) AS mayhem
    FROM pumpdotfun_solana.pump_evt_tradeevent t
    JOIN sel s ON t.mint = s.mint
    WHERE t.evt_block_date >= DATE '2026-06-01'
      AND t.evt_block_date <= DATE '2026-06-11'
      AND t.evt_block_time <  TIMESTAMP '2026-06-11 23:59:00'
      AND t.quote_mint = '11111111111111111111111111111111'
),
seqd AS (
    SELECT *,
           row_number() OVER (PARTITION BY mint ORDER BY slot, txi, ixi) AS seq,
           if(is_buy, lam, -lam) AS signed_lam,
           CAST(vsol AS double) / 1e9 AS x_sol,
           CAST(lam  AS double) / 1e9 AS sol_abs
    FROM ev
),
flows AS (
    SELECT *,
           -- trailing net flow, prefix-sum difference: slot in (s-w, s], cut at this row
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 3 PRECEDING), 0)  AS nf3_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 5 PRECEDING), 0)  AS nf5_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 12 PRECEDING), 0) AS nf12_lam,
           sum(signed_lam) OVER pfx
             - coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
                 RANGE BETWEEN UNBOUNDED PRECEDING AND 25 PRECEDING), 0) AS nf25_lam,
           -- f3: distinct buyers over the trailing 12 slots.  count(DISTINCT) is
           -- not allowed as a window function in Trino, so the window collects
           -- the wallets and cardinality(array_distinct(...)) counts them.
           cardinality(array_distinct(array_agg(if(is_buy, wallet)) OVER (
               PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 12 PRECEDING AND CURRENT ROW))) AS n_buyers_12slot,
           -- f8 / f9 over the trailing 25 slots
           stddev_pop(sol_abs) OVER trail25 AS size_sd_25,
           avg(sol_abs)        OVER trail25 AS size_mean_25,
           avg(if(abs(sol_abs - 0.1) < 1e-9 OR abs(sol_abs - 0.5) < 1e-9
                  OR abs(sol_abs - 1.0) < 1e-9, 1.0, 0.0)) OVER trail25 AS round_frac_25,
           count(*) OVER trail25 AS n_trades_25,
           -- forward labels (§4.2): lookahead is intended here
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 5 FOLLOWING), 0)  AS fwd_nf5_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 12 FOLLOWING), 0) AS fwd_nf12_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 37 FOLLOWING), 0) AS fwd_nf37_lam,
           -- x at t+tau: last observed reserve inside the forward window
           last_value(vsol) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 5 FOLLOWING)  AS vsol_p5,
           last_value(vsol) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 12 FOLLOWING) AS vsol_p12,
           last_value(vsol) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN CURRENT ROW AND 37 FOLLOWING) AS vsol_p37,
           -- §5: V = flow landing during latency.  L1 = 1 slot, L2 = 1000ms
           -- ~ 2.5 slots (2 and 3 both kept), L3 = 3000ms ~ 7.5 slots (7 and 8).
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 1 FOLLOWING), 0) AS v_lat1_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 2 FOLLOWING), 0) AS v_lat2_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 3 FOLLOWING), 0) AS v_lat3_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 7 FOLLOWING), 0) AS v_lat7_lam,
           coalesce(sum(signed_lam) OVER (PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 8 FOLLOWING), 0) AS v_lat8_lam
    FROM seqd
    WINDOW pfx AS (PARTITION BY mint ORDER BY slot, txi, ixi
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
           trail25 AS (PARTITION BY mint ORDER BY slot
                       RANGE BETWEEN 25 PRECEDING AND CURRENT ROW)
),
-- §4.3 / §3c: the first future slot at which the trailing 3-slot flow is no
-- longer positive.  One scalar reconstructs the whole hazard curve, provided
-- "still positive" is absorbing; the 75-value trajectory is measured separately.
deaths AS (
    SELECT *,
           min(if(nf3_lam <= 0, slot)) OVER (
               PARTITION BY mint ORDER BY slot, txi, ixi
               ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS death_slot,
           array_agg(CAST(nf3_lam AS double) / 1e9) OVER (
               PARTITION BY mint ORDER BY slot
               RANGE BETWEEN 1 FOLLOWING AND 75 FOLLOWING) AS nf3_traj_75
    FROM flows
),
qual AS (
    SELECT *,
           lag(slot) OVER (PARTITION BY mint ORDER BY slot, txi, ixi) AS prev_q_slot
    FROM deaths
    WHERE CAST(nf5_lam AS double) / 1e9 >= greatest(3.0, 0.10 * x_sol)
),
bursts AS (
    SELECT * FROM qual WHERE prev_q_slot IS NULL OR slot - prev_q_slot > 25
),
wstate AS (
    SELECT mint, wallet, seq,
           sum(if(is_buy, lam,   0))      OVER w AS buy_lam,
           sum(if(is_buy, units, 0))      OVER w AS buy_units,
           sum(if(is_buy, units, -units)) OVER w AS held_units,
           lead(seq) OVER (PARTITION BY mint, wallet ORDER BY seq) AS next_seq
    FROM seqd
    WINDOW w AS (PARTITION BY mint, wallet ORDER BY seq
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
contrib AS (
    SELECT b.mint, b.seq,
           w.wallet,
           (CAST(w.held_units AS double) / 1e6)
             * ((CAST(b.vsol AS double) * CAST(b.vsol AS double))
                  / (CAST(b.x0_lam AS double) * CAST(b.y0_units AS double) * 1000.0)
                - CAST(w.buy_lam AS double) / (CAST(w.buy_units AS double) * 1000.0)) AS oh_w
    FROM bursts b
    JOIN wstate w
      ON w.mint = b.mint AND w.seq <= b.seq
     AND (w.next_seq IS NULL OR w.next_seq > b.seq)
    WHERE w.held_units > 0 AND w.buy_units > 0
      AND CAST(w.buy_lam AS double) / (CAST(w.buy_units AS double) * 1000.0)
          < (CAST(b.vsol AS double) * CAST(b.vsol AS double))
            / (CAST(b.x0_lam AS double) * CAST(b.y0_units AS double) * 1000.0)
),
oh AS (
    SELECT mint, seq,
           sum(oh_w) AS oh,
           sum(if(rnk <= 3, oh_w, 0)) AS oh_top3,
           count(*) AS oh_n_wallets
    FROM (SELECT *, row_number() OVER (PARTITION BY mint, seq ORDER BY oh_w DESC) AS rnk
          FROM contrib)
    GROUP BY mint, seq
)
SELECT
    -- identity and context
    b.mint                                              AS token_mint,
    b.slot,
    b.txi                                               AS tx_index,
    b.ixi                                               AS ix_index,
    b.bt                                                AS block_time,
    b.seq                                               AS event_seq,
    b.created_at                                        AS token_created_at,
    date_diff('second', b.created_at, b.bt) / 60.0      AS age_min,
    date_trunc('minute', b.bt)                          AS minute_bucket,
    b.mayhem, b.mayhem_at_launch,
    b.x0_lam, b.y0_units,
    b.wallet                                            AS trigger_wallet,
    b.is_buy                                            AS trigger_is_buy,
    CAST(b.lam AS double) / 1e9                         AS trigger_sol,
    CAST(b.units AS double) / 1e6                       AS trigger_tokens,
    -- f1, f2
    CAST(b.nf3_lam  AS double) / 1e9                    AS net_flow_3slot,
    CAST(b.nf5_lam  AS double) / 1e9                    AS net_flow_5slot,
    CAST(b.nf12_lam AS double) / 1e9                    AS net_flow_12slot,
    CAST(b.nf25_lam AS double) / 1e9                    AS net_flow_25slot,
    CAST(b.nf5_lam AS double)
      / nullif(CAST(b.nf25_lam AS double) / 5.0, 0)     AS accel,
    -- f3, f4, f5, f6
    b.n_buyers_12slot,
    b.x_sol                                             AS depth_x,
    (b.x_sol - 30.0) / 85.0                             AS curve_progress,
    0                                                   AS burst_age_slot,
    -- f7, f7b
    coalesce(o.oh, 0)                                   AS oh,
    coalesce(o.oh, 0) / b.x_sol                         AS oh_ratio,
    o.oh_top3 / nullif(o.oh, 0)                         AS oh_conc,
    coalesce(o.oh_n_wallets, 0)                         AS oh_n_wallets,
    -- f8, f9
    b.size_sd_25 / nullif(b.size_mean_25, 0)            AS size_cv_25slot,
    b.round_frac_25                                     AS round_frac_25slot,
    b.n_trades_25                                       AS n_trades_25slot,
    -- §3d threshold flags on this same event (not independently sessionised)
    CAST(b.nf5_lam AS double)/1e9 >= greatest(3.0, 0.05 * b.x_sol) AS qual_005,
    CAST(b.nf5_lam AS double)/1e9 >= greatest(3.0, 0.20 * b.x_sol) AS qual_020,
    -- §4.2 forward labels
    CAST(b.fwd_nf5_lam  AS double) / 1e9                AS fwd_net_flow_5slot,
    CAST(b.fwd_nf12_lam AS double) / 1e9                AS fwd_net_flow_12slot,
    CAST(b.fwd_nf37_lam AS double) / 1e9                AS fwd_net_flow_37slot,
    CAST(b.vsol_p5  AS double) / 1e9                    AS x_at_plus5,
    CAST(b.vsol_p12 AS double) / 1e9                    AS x_at_plus12,
    CAST(b.vsol_p37 AS double) / 1e9                    AS x_at_plus37,
    -- §5 latency flow V
    CAST(b.v_lat1_lam AS double) / 1e9                  AS v_latency_1slot,
    CAST(b.v_lat2_lam AS double) / 1e9                  AS v_latency_2slot,
    CAST(b.v_lat3_lam AS double) / 1e9                  AS v_latency_3slot,
    CAST(b.v_lat7_lam AS double) / 1e9                  AS v_latency_7slot,
    CAST(b.v_lat8_lam AS double) / 1e9                  AS v_latency_8slot,
    -- §4.3 hazard
    b.death_slot - b.slot                               AS death_age_slot,
    b.death_slot IS NULL                                AS hazard_censored,
    -- doubtful: only needed if "still positive" is not absorbing
    b.nf3_traj_75
FROM bursts b
LEFT JOIN oh o ON o.mint = b.mint AND o.seq = b.seq
ORDER BY b.mint, b.seq
